#! /usr/bin/env python
# -*- coding: utf-8 -*-
#######################
#
# Alexa-Hue Bridge 

# Note the "indigo" module is automatically imported and made available inside
# our global name space by the host process. We add it here so that the various
# Python IDEs will not show errors on each usage of the indigo module.
try:
    import indigo
except ImportError, e:
    pass
import inspect
import json
import logging
import Queue
import socket
import sys
import traceback
import uuid

from constants import *
from discovery import Broadcaster, Responder
from discovery_logging import ThreadDiscoveryLogging
from hue_listener import Httpd


################################################################################
class Plugin(indigo.PluginBase):
    ########################################
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        # Initialise dictionary to store plugin Globals
        self.globals = {}

        self.globals['overriddenHostIpAddress'] = ''  # If needed, set in Plugin config

        self.globals['discoveryId'] = 0  # An id (count) of discoveries to be used by discovery logging (if enabled)
        self.globals['discoveryLists'] = {}  # Dictionary of discovery lists (entries will be keyed by 'discoveryId')

        self.globals['debug'] = {}
        self.globals['debug']['debugGeneral']     = logging.INFO  # For general debugging of the main thread
        self.globals['debug']['debugServer']      = logging.INFO  # For general debugging of the Web Server thread(s)
        self.globals['debug']['debugBroadcaster'] = logging.INFO  # For general debugging of the Broadcaster thread(s)
        self.globals['debug']['debugResponder']   = logging.INFO  # For general debugging of the Responder thread(s)
        self.globals['debug']['debugMethodTrace'] = logging.INFO  # For displaying method invocations i.e. trace method

        self.globals['debug']['previousDebugGeneral']     = logging.INFO  # For general debugging of the main thread
        self.globals['debug']['previousDebugServer']      = logging.INFO  # For general debugging of the Web Server thread(s)
        self.globals['debug']['previousDebugBroadcaster'] = logging.INFO  # For general debugging of the Broadcaster thread(s)
        self.globals['debug']['previousDebugResponder']   = logging.INFO  # For general debugging of the Responder thread(s)
        self.globals['debug']['previousDebugMethodTrace'] = logging.INFO  # For displaying method invocations i.e. trace method

        # Setup Logging

        logformat = logging.Formatter('%(asctime)s.%(msecs)03d\t%(levelname)-12s\t%(name)s.%(funcName)-25s %(msg)s', datefmt='%Y-%m-%d %H:%M:%S')
        self.plugin_file_handler.setFormatter(logformat)

        self.plugin_file_handler.setLevel(logging.INFO)  # Master Logging Level for Plugin Log file

        self.indigo_log_handler.setLevel(logging.INFO)   # Logging level for Indigo Event Log

        self.generalLogger = logging.getLogger("Plugin.general")
        self.generalLogger.setLevel(self.globals['debug']['debugGeneral'])

        self.serverLogger = logging.getLogger("Plugin.server")
        self.serverLogger.setLevel(self.globals['debug']['debugServer'])

        self.broadcasterLogger = logging.getLogger("Plugin.broadcaster")
        self.broadcasterLogger.setLevel(self.globals['debug']['debugBroadcaster'])

        self.responderLogger = logging.getLogger("Plugin.responder")
        self.responderLogger.setLevel(self.globals['debug']['debugResponder'])

        self.methodTracer = logging.getLogger("Plugin.method")  
        self.methodTracer.setLevel(self.globals['debug']['debugMethodTrace'])

        # Initialising Message
        self.generalLogger.info(u"Alexa-Hue Bridge initialising . . .")

        self.globals['hueBridge'] = {}
        self.globals['portList'] = []

        AlexaHueBridgeDeviceCount = 0
        for dev in indigo.devices.iter("self"):
            if dev.deviceTypeId == EMULATED_HUE_BRIDGE_TYPEID:
                AlexaHueBridgeDeviceCount += 1
                try:
                    self.globals['portList'].append(int(dev.address))
                except:
                    pass
        self.generalLogger.debug(u'PORTLIST @Plugin INIT: %s' % self.globals['portList'])

        self.globals['ahbConversion'] = {}
        if AlexaHueBridgeDeviceCount == 0:
            # No devices defined - so possible conversion from V1 of the pluginProps
            for dev in indigo.devices:
                # Get the device's props
                props = dev.pluginProps
                if 'published' in props:
                    if 'alternate-name' in props:
                        self.globals['ahbConversion'][dev.id] = props['alternate-name']
                    else:
                        self.globals['ahbConversion'][dev.id] = ''


        # Set Plugin Config Values
        self.closedPrefsConfigUi(pluginPrefs, False)

        # # Validate the Plugin Config
        # self.validatePrefsConfigUi(pluginPrefs)

        # # Check debug options  
        # self.setDebuggingLevels(pluginPrefs)

        # # set possibly updated logging levels
        # self.generalLogger.setLevel(self.globals['debug']['debugGeneral'])
        # self.serverLogger.setLevel(self.globals['debug']['debugServer'])
        # self.broadcasterLogger.setLevel(self.globals['debug']['debugBroadcaster'])
        # self.responderLogger.setLevel(self.globals['debug']['debugResponder'])
        # self.methodTracer.setLevel(self.globals['debug']['debugMethodTrace'])

        # Need to subscribe to device changes here so we can call the refreshDeviceList method
        # in case there was a change or deletion of a device that's published
        indigo.devices.subscribeToChanges()

    def __del__(self):
        indigo.PluginBase.__del__(self)

    def startup(self):
        self.methodTracer.threaddebug(u"CLASS: Plugin")
        self.generalLogger.info(u"Alexa-Hue Bridge initialization complete")

        # Create process queue
        self.globals['queues'] = {}
        self.globals['queues']['discoveryLogging'] = Queue.PriorityQueue()  # Used to queue commands to be sent to discovery logging

        # define and start threads that will send messages to & receive messages from the lifx devices
        self.globals['threads'] = {}
        self.globals['threads']['discoveryLogging'] = ThreadDiscoveryLogging(self)
        self.globals['threads']['discoveryLogging'].start()



    def shutdown(self):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        self.generalLogger.debug(u"shutdown called")

    ########################################
    # Prefs dialog methods
    ########################################
    def validatePrefsConfigUi(self, valuesDict):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if 'overrideHostIpAddress' in valuesDict:
            if bool(valuesDict.get('overrideHostIpAddress', False)):
                if valuesDict.get('overriddenHostIpAddress', '') == '':
                    errorDict = indigo.Dict()
                    errorDict["overriddenHostIpAddress"] = "Host IP Address missing"
                    errorDict["showAlertText"] = "You have elected to override the Host Ip Address but haven't specified it!"
                    return (False, valuesDict, errorDict)

        return True

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if userCancelled == True:
            return

        # Set Host IP Address override
        if bool(valuesDict.get('overrideHostIpAddress', False)): 
            self.globals['overriddenHostIpAddress'] = valuesDict.get('overriddenHostIpAddress', '')
            if self.globals['overriddenHostIpAddress'] != '':
                self.generalLogger.info(u"Host IP Address overridden and specified as: '%s'" % (valuesDict.get('overriddenHostIpAddress', 'INVALID ADDRESS')))


        # Set Discovery Logging
        self.globals['showDiscoveryInEventLog'] = bool(valuesDict.get("showDiscoveryInEventLog", True))
        if self.globals['showDiscoveryInEventLog']:
            self.generalLogger.info(u"Alexa discovery request logging enabled")
        else:
            self.generalLogger.info(u"Alexa discovery request logging disabled")

        # Check debug options  
        self.setDebuggingLevels(valuesDict)

        # set possibly updated logging levels
        self.generalLogger.setLevel(self.globals['debug']['debugGeneral'])
        self.serverLogger.setLevel(self.globals['debug']['debugServer'])
        self.broadcasterLogger.setLevel(self.globals['debug']['debugBroadcaster'])
        self.responderLogger.setLevel(self.globals['debug']['debugResponder'])
        self.methodTracer.setLevel(self.globals['debug']['debugMethodTrace'])

    def setDebuggingLevels(self, valuesDict):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        self.globals['debug']['debugEnabled'] = bool(valuesDict.get("debugEnabled", False))

        self.globals['debug']['debugGeneral']     = logging.INFO  # For general debugging of the main thread
        self.globals['debug']['debugServer']      = logging.INFO  # For general debugging of the Web Server thread(s)
        self.globals['debug']['debugBroadcaster'] = logging.INFO  # For general debugging of the Broadcaster thread(s)
        self.globals['debug']['debugResponder']   = logging.INFO  # For general debugging of the Responder thread(s)

        if self.globals['debug']['debugEnabled'] == False:
            self.plugin_file_handler.setLevel(logging.INFO)
        else:
            self.plugin_file_handler.setLevel(logging.THREADDEBUG)

        debugGeneral     = bool(valuesDict.get("debugGeneral", False))
        debugServer      = bool(valuesDict.get("debugServer", False))
        debugBroadcaster = bool(valuesDict.get("debugBroadcaster", False))
        debugResponder   = bool(valuesDict.get("debugResponder", False))
        debugMethodTrace = bool(valuesDict.get("debugMethodTrace", False))

        if debugGeneral:
            self.globals['debug']['debugGeneral'] = logging.DEBUG 
        if debugServer:
            self.globals['debug']['debugServer'] = logging.DEBUG
        if debugBroadcaster:
            self.globals['debug']['debugBroadcaster'] = logging.DEBUG
        if debugResponder:
            self.globals['debug']['debugResponder'] = logging.DEBUG
        if debugMethodTrace:
            self.globals['debug']['debugMethodTrace'] = logging.THREADDEBUG

        self.globals['debug']['debugActive'] = debugGeneral or debugServer or debugBroadcaster or debugResponder or debugMethodTrace

        if not self.globals['debug']['debugEnabled']:
            self.generalLogger.info(u"No debugging requested")
        else:
            debugTypes = []
            if debugGeneral:
                debugTypes.append('General')
            if debugServer:
                debugTypes.append('Server')
            if debugBroadcaster:
                debugTypes.append('Broadcaster')
            if debugResponder:
                debugTypes.append('Responder')
            if debugMethodTrace:
                debugTypes.append('Method Trace')
            message = self.listActive(debugTypes)   
            self.generalLogger.warning(u"Debugging enabled for Alexa-Hue Bridge: %s" % (message))  

    def listActive(self, debugTypes):            
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        loop = 0
        listedTypes = ''
        for debugType in debugTypes:
            if loop == 0:
                listedTypes = listedTypes + debugType
            else:
                listedTypes = listedTypes + ', ' + debugType
            loop += 1
        return listedTypes

    ################################################
    # start the Alexa-Hue Bridge device (aka ahbDev)
    ################################################
    def deviceStartComm(self, ahbDev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")
        self.generalLogger.debug(u'DEVICE START: %s' % ahbDev.name)
        try:
            self.methodTracer.threaddebug(u"CLASS: Plugin")

            if not ahbDev.id in self.globals['hueBridge']:
                self.globals['hueBridge'][ahbDev.id] = {}
            if not 'publishedDevices' in self.globals['hueBridge'][ahbDev.id]:    
                self.globals['hueBridge'][ahbDev.id]['publishedDevices'] = {}

            if not 'hubName' in self.globals['hueBridge'][ahbDev.id]:    
                self.globals['hueBridge'][ahbDev.id]['hubName'] = ahbDev.name

            uuid_changed = False
            uuidValue = ahbDev.pluginProps.get("uuid", str(uuid.uuid1()))
            if not 'uuid' in self.globals['hueBridge'][ahbDev.id]:
                self.globals['hueBridge'][ahbDev.id]['uuid'] = uuidValue
                uuid_changed = True
            else:
                if self.globals['hueBridge'][ahbDev.id]['uuid'] != uuidValue:
                    self.globals['hueBridge'][ahbDev.id]['uuid'] = uuidValue
                    uuid_changed = True

            host_changed = False
            if self.globals['overriddenHostIpAddress'] != '':
                host = self.globals['overriddenHostIpAddress']
            else:
                host = ahbDev.pluginProps.get("host", "auto")
                if host == "auto":
                    try:
                        host = socket.gethostbyname(socket.gethostname())
                    except socket.gaierror:
                        self.generalLogger.error("Computer has no host name specified. Check the Sharing system preference and restart the plugin once the name is resolved.")
                        host = None

                    # CAN'T START HUB ?

            if not 'host' in self.globals['hueBridge'][ahbDev.id]:
                self.globals['hueBridge'][ahbDev.id]['host'] = host
                host_changed = True
            else:
                if self.globals['hueBridge'][ahbDev.id]['host'] != host:
                    self.globals['hueBridge'][ahbDev.id]['host'] = host
                    host_changed = True

            self.generalLogger.info(u"Hue Bridge '%s' Host: %s" % (self.globals['hueBridge'][ahbDev.id]['hubName'], self.globals['hueBridge'][ahbDev.id]['host']))

            port_changed = False
            port = ahbDev.pluginProps.get("port", "auto")
            if port == "auto":
                port_changed = True
                for port in range(8178, 8200):
                    if port not in self.globals['portList']:
                        self.globals['portList'].append(int(port))
                        break
                else:
                    self.generalLogger.error("No available ports for auto allocation - specify in device Config")
                    port = None

                    # CAN'T START HUB ?

            port = int(port)
            if not 'port' in self.globals['hueBridge'][ahbDev.id]:
                self.globals['hueBridge'][ahbDev.id]['port'] = port
                port_changed = True
            else:
                if self.globals['hueBridge'][ahbDev.id]['port'] != port:
                    self.globals['hueBridge'][ahbDev.id]['port'] = port
                    port_changed = True

            if port_changed or (port not in self.globals['portList']):
                self.globals['portList'].append(port)

                props = ahbDev.pluginProps
                props["port"] = str(port)
                props["address"]= str(port)
                props["version"] = '1.1'
                ahbDev.replacePluginPropsOnServer(props)


            self.globals['hueBridge'][ahbDev.id]['autoStartDiscovery'] = ahbDev.pluginProps.get("autoStartDiscovery", True)

            expireMinutesChanged = False
            expireMinutes = int(ahbDev.pluginProps.get("expireMinutes", "0"))

            if not 'expireMinutes' in self.globals['hueBridge'][ahbDev.id]:
                self.globals['hueBridge'][ahbDev.id]['expireMinutes'] = expireMinutes
                expireMinutesChanged = True
            else:
                if self.globals['hueBridge'][ahbDev.id]['expireMinutes'] != expireMinutes:
                    self.globals['hueBridge'][ahbDev.id]['expireMinutes'] = expireMinutes
                    expireMinutesChanged = True

            self.refreshDeviceList(ahbDev.id)
        
            self.generalLogger.info(u"Starting Hue Bridge '%s' web server thread" % self.globals['hueBridge'][ahbDev.id]['hubName'])

            start_webserver_required = False
            if not 'webServer' in self.globals['hueBridge'][ahbDev.id]:
                start_webserver_required = True
            else:
                if host_changed or port_changed:
                    self.globals['hueBridge'][ahbDev.id]['webServer'].stop()
                    self.sleep(2)  # wait 2 seconds (temporary fix?)
                    del self.globals['hueBridge'][ahbDev.id]['webServer']
                    start_webserver_required = True
            if start_webserver_required == True:
                self.globals['hueBridge'][ahbDev.id]['webServer'] = Httpd(self, ahbDev.id)
                self.globals['hueBridge'][ahbDev.id]['webServer'].start()

            # Only start discovery if auto-start requested
            if not self.globals['hueBridge'][ahbDev.id]['autoStartDiscovery']:
                self.generalLogger.info(u"Hue Bridge '%s' 'Auto Start Discovery' NOT requested" % self.globals['hueBridge'][ahbDev.id]['hubName'])
                self.setDeviceDiscoveryState(False, ahbDev.id)
            else:
                self.generalLogger.info(u"Starting Hue Bridge '%s' discovery thread as 'Auto Start Discovery' requested" % self.globals['hueBridge'][ahbDev.id]['hubName'])

                start_broadcaster_required = False
                if not 'broadcaster' in self.globals['hueBridge'][ahbDev.id]:
                    start_broadcaster_required = True
                else:
                    if not self.globals['hueBridge'][ahbDev.id]['broadcaster'].is_alive():
                        start_broadcaster_required = True
                    elif host_changed or port_changed or uuid_changed or expireMinutesChanged:
                        self.globals['hueBridge'][ahbDev.id]['broadcaster'].stop()
                        self.globals['hueBridge'][ahbDev.id]['broadcaster'].join(5)
                        del self.globals['hueBridge'][ahbDev.id]['broadcaster']
                        start_broadcaster_required = True
                if start_broadcaster_required == True:
                    self.globals['hueBridge'][ahbDev.id]['broadcaster'] = Broadcaster(self, ahbDev.id)
                    self.globals['hueBridge'][ahbDev.id]['broadcaster'].start()

                start_responder_required = False
                if not 'responder' in self.globals['hueBridge'][ahbDev.id]:
                    start_responder_required = True
                else:
                    if not self.globals['hueBridge'][ahbDev.id]['responder'].is_alive():
                        start_responder_required = True
                    elif host_changed or port_changed or uuid_changed or expireMinutesChanged:
                        self.globals['hueBridge'][ahbDev.id]['responder'].stop()
                        self.globals['hueBridge'][ahbDev.id]['broadcaster'].join(5)
                        del self.globals['hueBridge'][ahbDev.id]['responder']
                        start_responder_required = True
                if start_responder_required == True:
                    self.globals['hueBridge'][ahbDev.id]['responder'] = Responder(self, ahbDev.id)
                    self.globals['hueBridge'][ahbDev.id]['responder'].start()

                self.setDeviceDiscoveryState(True, ahbDev.id)
 
        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in deviceStartComm for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDev.id].name, sys.exc_traceback.tb_lineno, e))


    def deviceStopComm(self, ahbDev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        stoppedId = ahbDev.id
        stoppedName = ahbDev.name

        try:
            if 'webServer' in self.globals['hueBridge'][stoppedId]:
                if self.globals['hueBridge'][stoppedId]['webServer']:
                    self.globals['hueBridge'][stoppedId]['webServer'].stop()
            if 'broadcaster' in self.globals['hueBridge'][stoppedId]:
                if self.globals['hueBridge'][stoppedId]['broadcaster']:
                    self.globals['hueBridge'][stoppedId]['broadcaster'].stop()
            if 'responder' in self.globals['hueBridge'][stoppedId]:
                if self.globals['hueBridge'][stoppedId]['responder']:
                    self.globals['hueBridge'][stoppedId]['responder'].stop()
        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in deviceStopComm for '%s'. Line '%s' has error='%s'" % (stoppedName, sys.exc_traceback.tb_lineno, e))


    def didDeviceCommPropertyChange(self, origDev, newDev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")
        self.generalLogger.debug(u'DID-DEVICE-COMM-PROPERTY-CHANGE: Old [%s] vs New [%s]' % (origDev.name, newDev.name))
        if newDev.deviceTypeId == EMULATED_HUE_BRIDGE_TYPEID:
            pass
            # self.generalLogger.debug(u'didDeviceCommPropertyChange: %s' % newDev)
        if newDev.pluginProps['port'] == "auto":
            self.generalLogger.debug(u'DID-DEVICE-COMM-PROPERTY-CHANGE: PORT AUTO')
            return True
        if origDev.pluginProps['expireMinutes'] != newDev.pluginProps['expireMinutes']:
            self.generalLogger.debug(u'DID-DEVICE-COMM-PROPERTY-CHANGE [EXPIRE MINUTES]: Old [%s] vs New [%s]' % (origDev.pluginProps['expireMinutes'], newDev.pluginProps['expireMinutes']))
            self.generalLogger.debug(u'DID-DEVICE-COMM-PROPERTY-CHANGE [AUTO START]: Old [%s] vs New [%s]' % (origDev.pluginProps['autoStartDiscovery'], newDev.pluginProps['autoStartDiscovery']))
            return True
        return False


    def getDeviceConfigUiValues(self, pluginProps, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if typeId == EMULATED_HUE_BRIDGE_TYPEID:
            # Set internal storage for device
            if ahbDevId not in self.globals['hueBridge']:
                self.globals['hueBridge'][ahbDevId] = {}
            if 'publishedDevices' not in self.globals['hueBridge'][ahbDevId]:
                self.globals['hueBridge'][ahbDevId]['publishedDevices'] = {}
            if 'hubName' not in self.globals['hueBridge'][ahbDevId]:
                self.globals['hueBridge'][ahbDevId]['hubName'] = indigo.devices[ahbDevId].name
            self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'] = {}  # Initialise list of newly added devices to publish
            self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList'] = {}  # Initialise list of deleted devices to remove from publication

            self.refreshDeviceList(ahbDevId)          

            # Set default values for Edit Device Settings... (ConfigUI)
            pluginProps["autoStartDiscovery"] = pluginProps.get("autoStartDiscovery", True)
            pluginProps["expireMinutes"] = pluginProps.get("expireMinutes", "0")
            pluginProps["uuid"] = pluginProps.get("uuid", str(uuid.uuid1()))
            pluginProps["host"] = pluginProps.get("host", "auto")
            pluginProps["port"] = pluginProps.get("port", "auto")

            pluginProps["alexaNamesList"] = "0-0"
            pluginProps["alexaNameIndigoDevice"] = ""
            pluginProps["alexaNameHub"] = ""
            pluginProps["sourceDeviceMenu"] = "0"

            # processing to add in devices from Version 1 of the plugin
            if len(self.globals['ahbConversion']) > 0:
                self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'] = {}
                for id, name in self.globals['ahbConversion'].items():
                    self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'][id] = name
            # Only allow conversion immediately following Plugin start-up
            self.globals['ahbConversion'] = {}

        return super(Plugin, self).getDeviceConfigUiValues(pluginProps, typeId, ahbDevId)


    def validateDeviceConfigUi(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if typeId == EMULATED_HUE_BRIDGE_TYPEID:
            self.generalLogger.debug(u"Validating Device config for type: " + typeId)

            errorsDict = indigo.Dict()
            try:
                amount = int(valuesDict["expireMinutes"])
                if amount not in range(0, 11):
                    raise
            except:
                errorsDict["expireMinutes"] = "'Expiration in minutes' must be a positive integer from 0 to 10"
                errorsDict["showAlertText"] = "'Expiration in minutes' is invalid"
            if len(errorsDict) > 0:
                return (False, valuesDict, errorsDict)

        return (True, valuesDict)

    def closedDeviceConfigUi(self, valuesDict, userCancelled, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")
        try:
            self.generalLogger.debug(u"'closePrefsConfigUi' called with userCancelled = %s" % (str(userCancelled)))  

            if userCancelled == True:
                return

            if typeId != EMULATED_HUE_BRIDGE_TYPEID:
                return

            self.globals['hueBridge'][ahbDevId]['autoStartDiscovery'] = valuesDict.get("autoStartDiscovery", True)

            self.globals['hueBridge'][ahbDevId]['expireMinutes'] = int(valuesDict.get("expireMinutes", "0"))

            if (len(self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList']) == 0 and 
                len(self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList']) == 0):
                return

            # Now scan the list of device to delete and update the devices
            for devId in self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList']:
                # Delete the device's properties for this plugin and delete the entry in self.globals['hueBridge'][ahbDev.id]['publishedDevices']
                # del self.globals['hueBridge'][ahbDevId]['publishedDevices'][int(devId)]  # NOT NEEDED ???
                dev = indigo.devices[int(devId)]
                # Setting a device's plugin props to None will completely delete the props for this plugin in the devices'
                # globalProps.
                dev.replacePluginPropsOnServer(None)

            # Now scan the list of device to add and update the devices
            for devId in self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList']:
                # Now we need to add the properties to the selected device for permanent storage
                # Get the device instance
                dev = indigo.devices[devId]
                # Get the device's props
                props = dev.pluginProps
                # Add the flag to the props. May already be there, but no harm done.

                ahbKey = KEY_PREFIX + str(ahbDevId)  # Set key for this Emulated Hue Bridge

                if not ahbKey in props:
                    props[ahbKey] = indigo.Dict()
                ahbProps = props[ahbKey]
                ahbProps[PUBLISHED_KEY] = "True"

                # Add/update/delete the name to the props as appropriate.
                altName = self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'][devId]
                self.generalLogger.debug(u"addDevice: valuesDict['altName']: |%s|" % str(altName))
                if len(altName):
                    ahbProps[ALT_NAME_KEY] = altName
                elif ALT_NAME_KEY in ahbProps:
                    del ahbProps[ALT_NAME_KEY]

                # Replace the props on the server's copy of the device instance.
                props[ahbKey] = ahbProps
                dev.replacePluginPropsOnServer(props)

            # Calculate number of published devices for info message
            idSet = set()
            for devId in self.globals['hueBridge'][ahbDevId]['publishedDevices']:
                idSet.add(devId)
            for devId in self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList']:
                idSet.add(devId)  # Will only add to set if not already in the set
            for devId in self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList']:
                try:
                    idSet.remove(devId)  # Only remove from set if already in the set
                except KeyError:
                    pass
            numberPublished = len(idSet)

            if numberPublished == 0:
                numberPublishedUI = 'no devices'
            elif numberPublished == 1:
                numberPublishedUI = 'one device'
            else:
                numberPublishedUI = str('%s devices' % numberPublished)
            self.generalLogger.info(u"'%s' updated and now has %s published" % (self.globals['hueBridge'][ahbDevId]['hubName'], numberPublishedUI))

            self.updatedPublishedList = self.globals['hueBridge'][ahbDevId]['publishedDevices'].copy()
            self.updatedPublishedList.update(self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'])
            self.globals['hueBridge'][ahbDevId]['publishedDevices'] = self.updatedPublishedList

            self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'] = {}  # Initialise list of newly added devices to publish
            self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList'] = {}  # Initialise list of deleted devices to remove from publication

            self.generalLogger.debug(u"'closePrefsConfigUi' completed for '%s'" % self.globals['hueBridge'][ahbDevId]['hubName'])

        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in closedDeviceConfigUi for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))
    


    ########################################
    # The next two methods should catch when a device name changes in Indigo and when a device we have published
    # gets deleted - we'll just rebuild the device list cache in those situations.
    ########################################
    def deviceDeleted(self, dev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if dev.deviceTypeId != EMULATED_HUE_BRIDGE_TYPEID:
            for ahbDevId in self.globals['hueBridge']:
                if 'publishedDevices' in self.globals['hueBridge'][ahbDevId]:
                    if dev.id in self.globals['hueBridge'][ahbDevId]['publishedDevices']:
                        self.generalLogger.info(u"A device (%s) that was published has been deleted - you'll probably want use the Alexa app to forget that device." % dev.name)
                        self.refreshDeviceList(ahbDevId)

        super(Plugin, self).deviceDeleted(dev)


    def deviceUpdated(self, origDev, newDev):
#        self.methodTracer.threaddebug(u"CLASS: Plugin")

        # If it is not an 'Emulated hue Bridge' device, then check device for changes        
        if newDev.deviceTypeId != EMULATED_HUE_BRIDGE_TYPEID:
            for ahbDevId in self.globals['hueBridge']:
                #self.generalLogger.debug(u"deviceUpdated called with id: %i" % origDev.id)
                if origDev.id in self.globals['hueBridge'][ahbDevId]['publishedDevices']:
                    # Drill down on the change a bit - if the name changed and there's no alternate name OR the alternate
                    # name changed then refresh the device list
                    ahbKey = KEY_PREFIX + str(ahbDevId)  # Set key for this Alexa-Hue Bridge
                    origPubKey = "False"
                    origAltName = None
                    newPubKey = "False"
                    newAltName = None
                    if ahbKey in origDev.pluginProps:
                        origPubKey = origDev.pluginProps[ahbKey].get(PUBLISHED_KEY, "False")
                        origAltName = origDev.pluginProps[ahbKey].get(ALT_NAME_KEY, None)
                    if ahbKey in newDev.pluginProps:
                        newPubKey = newDev.pluginProps[ahbKey].get(PUBLISHED_KEY, "False")
                        newAltName = newDev.pluginProps[ahbKey].get(ALT_NAME_KEY, None)

                    if origAltName != newAltName:
                        self.refreshDeviceLists()
                        self.generalLogger.info(u"A device name changed - you'll most likely want to perform the 'Alexa, discover devices' command on all Alexa devices. #100")
                    elif origDev.name != newDev.name:
                        self.refreshDeviceLists()
                        self.generalLogger.info(u"A device name changed - you'll most likely want to perform the 'Alexa, discover devices' command on all Alexa devices. #101")
                    elif origPubKey != newPubKey:
                        self.refreshDeviceLists()
                        self.generalLogger.info(u"Your published device list changed - you'll most likely want to perform the 'Alexa, discover devices' command on all Alexa devices.")

        super(Plugin, self).deviceUpdated(origDev, newDev)

    ########################################origPubKey
    # This method is called to refresh the list of published devices for all hueBridge devices.
    ########################################
    def refreshDeviceLists(self):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        for dev in indigo.devices.iter("self"):
            if dev.deviceTypeId == EMULATED_HUE_BRIDGE_TYPEID:
                self.refreshDeviceList(dev.id)



    ########################################
    # This method is called to refresh the list of published devices for a hueBridge device.
    ########################################
    def refreshDeviceList(self, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        self.globals['hueBridge'][ahbDevId]['publishedDevices'] = dict()
        for dev in indigo.devices:
            ahbKey = KEY_PREFIX + str(ahbDevId)  # Set key for this Alexa-Hue Bridge
            props = dev.pluginProps
            if ahbKey in props:
                if PUBLISHED_KEY in props[ahbKey]:
                    self.generalLogger.debug(u"found published device: %i - %s" % (dev.id, dev.name))
                    if len(self.globals['hueBridge'][ahbDevId]['publishedDevices']) >= DEVICE_LIMIT:
                        self.generalLogger.error(u"Device limit of %i reached: device %s skipped" % (DEVICE_LIMIT, dev.name))
                    else:
                        self.globals['hueBridge'][ahbDevId]['publishedDevices'][dev.id] = props[ahbKey].get(ALT_NAME_KEY, "")

        numberPublished = len(self.globals['hueBridge'][ahbDevId]['publishedDevices'])
        if numberPublished == 0:
            numberPublishedUI = 'no devices'
        elif numberPublished == 1:
            numberPublishedUI = 'one device'
        else:
            numberPublishedUI = str('%s devices' % numberPublished)
        self.generalLogger.info(u"'%s' has %s published" % (self.globals['hueBridge'][ahbDevId]['hubName'], numberPublishedUI))

    ########################################
    # This method is called to generate a list of devices that support onState only.
    ########################################
    def devicesWithOnState(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.methodTracer.threaddebug(u"CLASS: Plugin")
        # Set a default with id 0
        # Iterates through the device list and only add the device if it has an onState property
        # but don't include any Emulated Hue Bridge devices!

        deviceList = [(0, '-- Select Device --')]
        for dev in indigo.devices:
            if hasattr(dev, "onState") and (dev.deviceTypeId != EMULATED_HUE_BRIDGE_TYPEID):
                deviceList.append((dev.id, dev.name))
        return deviceList


    ########################################
    # This method is called to generate a list of the names of devices defined to Alexa.
    ########################################
    def alexaNamesList(self, filter, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        self.globals['alexaNamesList'] = []

#        allocatedNameList = [(0, '-- Allocated Names --')]
        allocatedNameList = []
        allocatedNameList.append(('0-0', "-- Select name for more detail --"))
        for ahbDevId in self.globals['hueBridge']:
            if 'devicesToAddToPublishedList' in self.globals['hueBridge'][ahbDevId]:
                for id, name in self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'].items():
                    allocatedName = indigo.devices[id].name
                    if len(name) > 0:
                        allocatedName = "%s" % name
                        self.globals['alexaNamesList'].append((name, (ahbDevId, id)))
                    else:
                        self.globals['alexaNamesList'].append((allocatedName, (ahbDevId, id)))

                    allocatedNameList.append((str(ahbDevId) + '-' + str(id), allocatedName))
            else:
                self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'] = {}  # So next bit of logic works!

            if 'devicesToDeleteFromPublishedList' not in self.globals['hueBridge'][ahbDevId]:
                self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList'] = {}  # So next bit of logic works!

            if 'publishedDevices' in self.globals['hueBridge'][ahbDevId]:
                for id, name in self.globals['hueBridge'][ahbDevId]['publishedDevices'].items():
                    if ((id not in self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList']) and
                        (id not in self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList'])):
                        allocatedName = indigo.devices[id].name
                        if len(name) > 0:
                            allocatedName = "%s" % name
                            self.globals['alexaNamesList'].append((name, (ahbDevId, id)))
                        else:
                            self.globals['alexaNamesList'].append((allocatedName, (ahbDevId, id)))
                        allocatedNameList.append((str(ahbDevId) + '-' + str(id), allocatedName))


        self.globals['alexaNamesList'] = sorted(self.globals['alexaNamesList'], key= lambda item: item[0])
        allocatedNameList = sorted(allocatedNameList, key= lambda item: item[1])
        return allocatedNameList

#        return [(dev.id, dev.name) for dev in indigo.devices if ((hasattr(dev, "onState")) and (dev.deviceTypeId != EMULATED_HUE_BRIDGE_TYPEID))]

    ########################################
    # We implement this method (which is from the plugin base) because we want to show/hide the message at the top
    # indicating that the max number of devices has been published.
    ########################################
    # def getMenuActionConfiguiValues(self, menuId):
    #     self.generalLogger.debug(u"getMenuActionConfiguiValues: published device count is %i" % len(self.globals['hueBridge'][ahbDev.id]['publishedDevices']))
    #     valuesDict = indigo.Dict()
    #     # Show the label in the dialog that tells the user they've reached the device limit
    #     if len(self.globals['hueBridge'][ahbDev.id]['publishedDevices']) >= DEVICE_LIMIT:
    #         valuesDict["showLimitMessage"] = True
    #     errorMsgDict = indigo.Dict()
    #     return (valuesDict, errorMsgDict)

    ########################################
    # These are the methods that's called when devices are selected from the various lists/menus. They enable other
    # as necessary.
    ########################################
    def selectDeviceToAdd(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        valuesDict["enableAltNameField"] = True
        if "sourceDeviceMenu" in valuesDict:
            # Get the device ID of the selected device
            deviceId = valuesDict["sourceDeviceMenu"]
            # If the device id isn't empty (should never be)
            if deviceId != "":
                # Get the device instance
                dev = indigo.devices[int(deviceId)]
                try:
                    # Try getting the existing alternate name and set the alt field with the correct name
                    ahbKey = KEY_PREFIX + str(ahbDevId)  # Set key for this Alexa-Hue Bridge
                    altName = dev.pluginProps[ahbKey][ALT_NAME_KEY]
                    valuesDict["altName"] = altName
                except:
                    # It's not there, so just skip
                    pass
        else:
            valuesDict["altName"] = ""
        return valuesDict


    def identifyAssignedDeviceAndHueBridgeForAlexaName(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if "alexaNamesList" in valuesDict:
            hueHubId, devId = valuesDict["alexaNamesList"].split("-")
            if hueHubId == "0" and devId == "0":
                valuesDict["alexaNameIndigoDevice"] = ''
                valuesDict["alexaNameHueBridge"] = ''
            else:
                valuesDict["alexaNameIndigoDevice"] = indigo.devices[int(devId)].name
                valuesDict["alexaNameHueBridge"] = indigo.devices[int(hueHubId)].name

        return valuesDict

    ########################################
    # This is the method that's called by the Add Device button in the config dialog.
    ########################################
    def addDevice(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        # Get the device ID of the selected device - bail if it's not good
        try:
            deviceId = int(valuesDict.get("sourceDeviceMenu", 0))
        except:
            deviceId = 0
        if deviceId == 0:
            return

        # Check if name already allocated

        if valuesDict["altName"] == '':
            nameToCheck = indigo.devices[deviceId].name.lower()
        else:
            nameToCheck = valuesDict["altName"].lower()
        try:
            alexaNameDevId = next(x for x in self.globals['alexaNamesList'] if x[0].lower() == nameToCheck)[1]
            if (ahbDevId == alexaNameDevId[0]) and (alexaNameDevId[1] == deviceId):
                pass
            else:
                # Name is allocated to a different device (possibly managed by a different Hue Bridge)
                # or Name is allocated to the same device but it is managed by a different Hue Bridge)
                # therefore reject as duplicates not allowed
                if ahbDevId == alexaNameDevId[0]:
                    errorText = str("'%s' is already in use by Alexa, for Indigo device: '%s' - Try a different name." % (nameToCheck, indigo.devices[alexaNameDevId[1]].name))
                else:
                    errorText = str("'%s' is already in use by Alexa, for Indigo device: '%s' but on another Hue Hub: '%s' - Try a different name." % (nameToCheck, indigo.devices[alexaNameDevId[1]].name, indigo.devices[alexaNameDevId[0]].name))
                self.generalLogger.error(errorText)
                errorsDict = indigo.Dict()
                errorsDict["showAlertText"] = errorText
                return (valuesDict, errorsDict)

        except StopIteration:
            pass
        except Exception, e:
            self.generalLogger.error(u"addDevice exception: \n%s" % str(traceback.format_exc(10)))


        if deviceId not in self.globals['hueBridge'][ahbDevId]['publishedDevices'] and len(self.globals['hueBridge'][ahbDevId]['publishedDevices']) >= DEVICE_LIMIT:
            errorText = "You can't publish any more devices - you've reached the max of %i imposed by Alexa." % DEVICE_LIMIT
            self.generalLogger.error(errorText)
            errorsDict = indigo.Dict()
            errorsDict["showAlertText"] = errorText
            return (valuesDict, errorsDict)
        # Get the list of devices that have already been added to the list
        # If the key doesn't exist then return an empty string indicating
        # no devices have yet been added. "memberDevices" is a hidden text
        # field in the dialog that holds a comma-delimited list of device
        # ids, one for each of the devices in the scene.
        self.generalLogger.debug(u"adding device: %s" % deviceId)
        # Get the list of devices that are already in the scene
        # Add or update the name to the plugin's cached list
        self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'][deviceId] = valuesDict["altName"]

        self.generalLogger.debug(u"valuesDict = " + str(valuesDict))
        # Clear out the name field and the source device field
        valuesDict["sourceDeviceMenu"] = ""
        valuesDict["enableAltNameField"] = "False"
        # Clear out the alternate name field
        valuesDict["altName"] = ""

        if len(self.globals['hueBridge'][ahbDevId]['publishedDevices']) >= DEVICE_LIMIT:
            # Show the label in the dialog that tells the user they've reached the device limit
            valuesDict["showLimitMessage"] = True

        return valuesDict

    ##########################################################################################
    # This is the method that's called by the 'Delete Devices' button in the device config UI.
    ##########################################################################################
    def deleteDevices(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        # valuesDict['memberDeviceList'] conatins the lsit of devices to delete from the Published Devices List
        #   Which is a combination of 'publishedDevices' and 'devicesToAddToPublishedList'

        # Delete the device's properties for this plugin and delete the entry in self.globals['hueBridge'][ahbDev.id]['publishedDevices']
        for devIdStr in valuesDict['memberDeviceList']:
            devId = int(devIdStr)
            self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList'][devId] = 'DEL' # Signify device to be deleted from 'publishedDevices'
            if devId in self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList']:
                del self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'][devId]  # delete from 'devicesToAddToPublishedList'
        if (len(self.globals['hueBridge'][ahbDevId]['publishedDevices']) + len(self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'])) < DEVICE_LIMIT:
            # Hide the label in the dialog that tells the user they've reached the device limit
            valuesDict["showLimitMessage"] = False
        return valuesDict

    ################################################################################
    # This is the method that's called to build the member device list.
    # Note: valuesDict is read-only so any changes you make to it will be discarded.
    ################################################################################
    def memberDevices(self, filter, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        self.generalLogger.debug(u"memberDevices called with filter: %s  typeId: %s  Hue Hub: %s" % (filter, typeId, str(ahbDevId)))
        returnList = list()
        if ahbDevId in self.globals['hueBridge']:
            if 'devicesToAddToPublishedList' in self.globals['hueBridge'][ahbDevId]:
                for id, name in self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'].items():
                    deviceName = indigo.devices[id].name
                    if len(name) > 0:
                        deviceName += " (%s)" % name
                    returnList.append((id, deviceName))
                    #returnList = sorted(returnList, key= lambda item: item[1])
            else:
                self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList'] = {}  # So next bit of logic works!

            if 'devicesToDeleteFromPublishedList' not in self.globals['hueBridge'][ahbDevId]:
                self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList'] = {}  # So next bit of logic works!

            if 'publishedDevices' in self.globals['hueBridge'][ahbDevId]:
                for id, name in self.globals['hueBridge'][ahbDevId]['publishedDevices'].items():
                    if ((id not in self.globals['hueBridge'][ahbDevId]['devicesToAddToPublishedList']) and
                        (id not in self.globals['hueBridge'][ahbDevId]['devicesToDeleteFromPublishedList'])):
                        deviceName = indigo.devices[id].name
                        if len(name) > 0:
                            deviceName += " (%s)" % name
                        returnList.append((id, deviceName))
                    #returnList = sorted(returnList, key= lambda item: item[1])

            returnList = sorted(returnList, key= lambda item: item[1])
        return returnList

    ########################################
    # This is the method that's called to validate the action config UIs.
    ########################################
    def validateActionConfigUi(self, valuesDict, typeId, devId):
        self.generalLogger.debug(u"Validating action config for type: " + typeId)
        errorsDict = indigo.Dict()
        if typeId == "startDiscovery":
            try:
                amount = int(valuesDict["expireMinutes"])
                if amount not in range(0, 11):
                    raise
            except:
                errorsDict["amount"] = "Amount must be a positive integer from 0 to 10"
        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    ########################################
    # Method called from bridge thread to turn on/off a device
    #
    #   deviceId is the ID of the device in Indigo
    #   turnOn is a boolean to indicate on/off
    ########################################
    def turnOnOffDevice(self, ahbDevId, deviceId, turnOn):
        try:
            if turnOn:
                indigo.device.turnOn(deviceId)
            else:
                indigo.device.turnOff(deviceId)
            name = indigo.devices[deviceId].name
            onOff = 'ON' if turnOn else 'OFF' 
            self.generalLogger.info(u"Set on state of device \"%s\" to %s" % (name, onOff))
        except:
            self.generalLogger.error(u"Device with id %i doesn't exist. The device list will be rebuilt - you should rerun discovery on your Alexa-compatible device." % deviceId)
            self.refreshDeviceList(ahbDevId)

    ########################################
    # Method called from bridge thread to set brightness of a device
    #
    #   deviceId is the ID of the device in Indigo
    #   brightness is the brightness in the range 0-100
    ########################################
    def setDeviceBrightness(self, ahbDevId, deviceId, brightness):
        try:
            dev = indigo.devices[deviceId]
        except:
            self.generalLogger.error(u"Device with id %i doesn't exist. The device list will be rebuilt - you should rerun discovery on your Alexa-compatible device." % deviceId)
            self.refreshDeviceList(ahbDevId)
            return
        name = indigo.devices[deviceId].name
        if isinstance(dev, indigo.DimmerDevice):
            self.generalLogger.info(u"Set brightness of device \"%s\" to %i" % (name, brightness))
            indigo.dimmer.setBrightness(dev, value=brightness)
        else:
            self.generalLogger.error(u"Device \"%s\" [with id %i] doesn't support dimming." % deviceId)


    # Actions invoked to turn discovery on / off and toggle
    #######################################################
    def actionControlDimmerRelay(self, action, ahbDev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        ###### TURN ON DISCOVERY ######
        if action.deviceAction == indigo.kDimmerRelayAction.TurnOn:
            self.generalLogger.info(u"sent \"%s\" %s" % (ahbDev.name, "Discovery on"))
            self.startDiscovery(action, ahbDev)

        ###### TURN OFF DISCOVERY ######
        elif action.deviceAction == indigo.kDimmerRelayAction.TurnOff:
            self.generalLogger.info(u"sent \"%s\" %s" % (ahbDev.name, "Discovery off"))
            self.stopDiscovery(action, ahbDev)

        ###### TOGGLE ######
        elif action.deviceAction == indigo.kDimmerRelayAction.Toggle:
            self.generalLogger.info(u"sent \"%s\" %s" % (ahbDev.name, "Discovery Toggle"))
            desiredOnState = not ahbDev.onState
            if desiredOnState == True:
                self.startDiscovery(action, ahbDev)
            else:
                self.stopDiscovery(action, ahbDev)


    def startDiscovery(self, action, ahbDev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        start_broadcaster_required = False

        if not 'broadcaster' in self.globals['hueBridge'][ahbDev.id]:
            start_broadcaster_required = True
        else:
            if not self.globals['hueBridge'][ahbDev.id]['broadcaster'].is_alive():
                start_broadcaster_required = True
        if start_broadcaster_required == True:
            self.globals['hueBridge'][ahbDev.id]['broadcaster'] = Broadcaster(self, ahbDev.id)
        try:
            self.globals['hueBridge'][ahbDev.id]['broadcaster'].start()

        except StandardError, e:
            # the broadcaster won't start for some reason, so just tell them to try restarting the plugin

            self.generalLogger.error(u"Start Discovery action failed for '%s': broadcaster thread couldn't start. Try restarting the plugin.'" % self.globals['hueBridge'][ahbDev.id]['hubName']) 
            errorLines = traceback.format_exc().splitlines()
            for errorLine in errorLines:
                self.generalLogger.error(u"%s" % errorLine)   
            return


        start_responder_required = False
        if not 'responder' in self.globals['hueBridge'][ahbDev.id]:
            start_responder_required = True
        else:
            if not self.globals['hueBridge'][ahbDev.id]['responder'].is_alive():
                start_responder_required = True
        if start_responder_required == True:
            self.globals['hueBridge'][ahbDev.id]['responder'] = Responder(self, ahbDev.id)
        try:
            self.globals['hueBridge'][ahbDev.id]['responder'].start()
            self.setDeviceDiscoveryState(True, ahbDev.id)
            self.generalLogger.info(u"Starting Hue Bridge '%s' discovery threads as 'Turn On Discovery' requested" % self.globals['hueBridge'][ahbDev.id]['hubName'])

        except:
            self.generalLogger.info(u"Start Discovery action failed")
            self.setDeviceDiscoveryState(False, ahbDev.id)

            # the responder won't start for some reason, so just tell them to try restarting the plugin
            self.generalLogger.error(u"Start Discovery action failed for '%s': responder thread couldn't start. Try restarting the plugin." % self.globals['hueBridge'][ahbDev.id]['hubName']) 
            # If the broadcaster thread started correctly, then we need to shut it down since it won't work
            # without the responder thread.
            if self.globals['hueBridge'][ahbDev.id]['broadcaster']:
                self.globals['hueBridge'][ahbDev.id]['broadcaster'].stop()

    def stopDiscovery(self, action, ahbDev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        # Stop the discovery threads
        self.setDeviceDiscoveryState(False, ahbDev.id)
        self.generalLogger.info(u"Stop Discovery . . . . . . . . . . ")

        if 'broadcaster' in self.globals['hueBridge'][ahbDev.id]:
            if self.globals['hueBridge'][ahbDev.id]['broadcaster']:
                self.globals['hueBridge'][ahbDev.id]['broadcaster'].stop()
        if 'responder' in self.globals['hueBridge'][ahbDev.id]:
            if self.globals['hueBridge'][ahbDev.id]['responder']:
                self.globals['hueBridge'][ahbDev.id]['responder'].stop()
        self.generalLogger.info(u"Stopping Hue Bridge '%s' discovery threads as 'Turn Off Discovery' requested" % self.globals['hueBridge'][ahbDev.id]['hubName'])

    def setDeviceDiscoveryState(self, discoveryOn, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        try:
            self.generalLogger.debug(u'SET DEVICE DISCOVERY STATE = %s' % discoveryOn)
            if discoveryOn:
                indigo.devices[ahbDevId].updateStateOnServer("onOffState", True, uiValue="Discovery: On")
                if self.globals['hueBridge'][ahbDevId]['expireMinutes'] == 0:
                    indigo.devices[ahbDevId].updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                else:
                    indigo.devices[ahbDevId].updateStateImageOnServer(indigo.kStateImageSel.TimerOn)
            else:
                indigo.devices[ahbDevId].updateStateOnServer("onOffState", False, uiValue="Discovery: Off")
                if self.globals['hueBridge'][ahbDevId]['expireMinutes'] == 0:
                    indigo.devices[ahbDevId].updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
                else:
                    indigo.devices[ahbDevId].updateStateImageOnServer(indigo.kStateImageSel.TimerOff)
        except:
            pass  # Handle deleted Alexa-Hue Bridge devices by ignoring