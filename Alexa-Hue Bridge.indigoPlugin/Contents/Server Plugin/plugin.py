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
import hashlib
import json
import logging
import Queue
import socket
import sys
from time import localtime, time, sleep, strftime
import traceback
import uuid

from constants import *
from ghpu import GitHubPluginUpdater
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

        self.globals['networkAvailable'] = {}
        self.globals['networkAvailable']['checkUrl'] = NETWORK_AVAILABLE_CHECK_REMOTE_SERVER
        self.globals['networkAvailable']['online'] = False
        self.globals['networkAvailable']['retryInterval'] = 10  # seconds

        self.globals['overriddenHostIpAddress'] = ''  # If needed, set in Plugin config
        self.globals['hostAddress'] = ''

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

        self.globals['alexaHueBridge'] = {}
        self.globals['alexaHueBridge']['publishedOtherAlexaDevices'] = {}
        self.globals['alexaHueBridge']['publishedHashKeys'] = {}
        self.globals['portList'] = []

        AlexaHueBridgeDeviceCount = 0
        for dev in indigo.devices.iter("self"):
            if dev.deviceTypeId == EMULATED_HUE_BRIDGE_TYPEID:
                if dev.enabled:
                    dev.setErrorStateOnServer(u"no ack")  # Default to 'no ack' status
                    AlexaHueBridgeDeviceCount += 1
                try:
                    self.globals['portList'].append(int(dev.address))  # Do this regardless whether device enabled or not
                except:
                    pass
        self.generalLogger.debug(u'PORTLIST @Plugin INIT: %s' % self.globals['portList'])

        # Initialise dictionary for update checking
        self.globals['update'] = {}

        # Set Plugin Config Values
        self.closedPrefsConfigUi(pluginPrefs, False)

        # Need to subscribe to device changes here so we can call the refreshDeviceList method
        # in case there was a change or deletion of a device that's published
        indigo.devices.subscribeToChanges()

    def __del__(self):
        indigo.PluginBase.__del__(self)

    def updatePlugin(self):
        self.globals['update']['updater'].update()

    def checkForUpdates(self):
        self.globals['update']['updater'].checkForUpdate()

    def forceUpdate(self):
        self.globals['update']['updater'].update(currentVersion='0.0.0')

    def checkRateLimit(self):
        limiter = self.globals['update']['updater'].getRateLimit()
        self.generalLogger.info('RateLimit {limit:%d remaining:%d resetAt:%d}' % limiter)


    def startup(self):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        # Set-up update checker
        self.globals['update']['updater'] = GitHubPluginUpdater(self)
        self.globals['update']['nextCheckTime'] = time()
 
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
    def getPrefsConfigUiValues(self):
        prefsConfigUiValues = self.pluginPrefs
        if "networkCheckURL" in prefsConfigUiValues and prefsConfigUiValues["networkCheckURL"] != '':
            pass
        else:
            prefsConfigUiValues["networkCheckURL"] = NETWORK_AVAILABLE_CHECK_REMOTE_SERVER

        if "showDiscoveryInEventLog" not in prefsConfigUiValues:
            prefsConfigUiValues["showDiscoveryInEventLog"] = True

        return prefsConfigUiValues

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

        self.globals['networkAvailable']['checkUrl'] = valuesDict.get("networkCheckURL", NETWORK_AVAILABLE_CHECK_REMOTE_SERVER)

        self.globals['update']['check'] = bool(valuesDict.get("updateCheck", False))
        self.globals['update']['checkFrequency'] = valuesDict.get("checkFrequency", 'DAILY')


        if self.globals['update']['checkFrequency'] == 'WEEKLY':
            self.globals['update']['checkTimeIncrement'] = (7 * 24 * 60 * 60)  # In seconds
        else:
            # DAILY 
            self.globals['update']['checkTimeIncrement'] = (24 * 60 * 60)  # In seconds

        # Set Host IP Address
        self.globals['overriddenHostIpAddress'] = ''  # Assume not overridden
        if bool(valuesDict.get('overrideHostIpAddress', False)): 
            self.globals['overriddenHostIpAddress'] = valuesDict.get('overriddenHostIpAddress', '')

        if self.globals['overriddenHostIpAddress'] != '':
            self.globals['hostAddress'] = self.globals['overriddenHostIpAddress']
            self.generalLogger.info(u"Plugin Host IP Address overridden and specified as: '{}'".format(self.globals['hostAddress']))
        else:
            try:
                self.globals['hostAddress'] = socket.gethostbyname(socket.gethostname())
            except socket.gaierror:
                self.generalLogger.error("Computer has no host name specified. Check the Sharing system preference and restart the plugin once the name is resolved.")
                self.globals['hostAddress'] = None
            self.generalLogger.info(u"Plugin Host IP Address is discovered as: '{}'".format(self.globals['hostAddress']))

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
            message = self.activeLoggingTypes(debugTypes)   
            self.generalLogger.warning(u"Debugging enabled for Alexa-Hue Bridge: %s" % (message))  

    def activeLoggingTypes(self, debugTypes):            
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

    def runConcurrentThread(self):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        # This thread is used to detect plugin close down and check for updates
        try:
            self.sleep(5) # in seconds - Allow startup to complete


            def is_connected():
                try:
                    # see if we can resolve the host name -- tells us if there is
                    # a DNS listening
                    host = socket.gethostbyname(self.globals['networkAvailable']['checkUrl'])
                    # connect to the host -- tells us if the host is actually
                    # reachable
                    s = socket.create_connection((host, 80), 2)
                    self.generalLogger.info(u"Alexa-Hue Bridge network access check to %s successfully completed." % self.globals['networkAvailable']['checkUrl'])
                    return True
                except:
                    pass
                return False

            isConnectedRetryCount = 0
            self.globals['networkAvailable']['retryInterval'] = NETWORK_AVAILABLE_CHECK_RETRY_SECONDS_ONE
            self.generalLogger.info(u"Alexa-Hue Bridge checking network access by attempting to access '%s'" % self.globals['networkAvailable']['checkUrl'])
            while not is_connected():
                isConnectedRetryCount += 1
                if isConnectedRetryCount > NETWORK_AVAILABLE_CHECK_LIMIT_ONE:
                    self.globals['networkAvailable']['retryInterval'] = NETWORK_AVAILABLE_CHECK_RETRY_SECONDS_TWO
                if isConnectedRetryCount < NETWORK_AVAILABLE_CHECK_LIMIT_TWO:
                    self.generalLogger.error(u"Alexa-Hue Bridge network access check failed - attempt %i - retrying in %i seconds" % (isConnectedRetryCount, self.globals['networkAvailable']['retryInterval']))
                elif isConnectedRetryCount == NETWORK_AVAILABLE_CHECK_LIMIT_TWO:
                    self.globals['networkAvailable']['retryInterval'] = NETWORK_AVAILABLE_CHECK_RETRY_SECONDS_THREE
                    self.generalLogger.error(u"Alexa-Hue Bridge network access check failed - attempt %i - will now silently retry every %i seconds" % (isConnectedRetryCount, self.globals['networkAvailable']['retryInterval']))
                elif isConnectedRetryCount > NETWORK_AVAILABLE_CHECK_LIMIT_TWO and isConnectedRetryCount % 12 == 0:
                    self.generalLogger.error(u"Alexa-Hue Bridge network access check failed - attempt %i - will continue to silently retry every %i seconds" % (isConnectedRetryCount, self.globals['networkAvailable']['retryInterval']))

                self.sleep(self.globals['networkAvailable']['retryInterval'])  # In seconds

            self.globals['networkAvailable']['online'] = True  # Used by runConcurrent Thread which is waiting for this to go True

            while True:
                if self.globals['networkAvailable']['online'] and self.globals['update']['check']:
                    if time() > self.globals['update']['nextCheckTime']:
                        if not 'checkTimeIncrement' in self.globals['update']:
                            self.globals['update']['checkTimeIncrement'] = (24 * 60 * 60)  # One Day In seconds
                        self.globals['update']['nextCheckTime'] = time() + self.globals['update']['checkTimeIncrement']
                        self.generalLogger.info(u"Alexa-Hue Bridge checking for Plugin update")
                        self.globals['update']['updater'].checkForUpdate()

                        nextCheckTime = strftime('%A, %Y-%b-%d at %H:%M', localtime(self.globals['update']['nextCheckTime']))
                        self.generalLogger.info(u"Alexa-Hue Bridge next update check scheduled for: %s" % nextCheckTime)
                self.sleep(60) # in seconds

        except self.StopThread:
            self.generalLogger.info(u"Alexa-Hue Bridge shutdown requested")








    ################################################
    # start the Alexa-Hue Bridge device (aka ahbDev)
    ################################################
    def deviceStartComm(self, ahbDev):
        try:
            self.methodTracer.threaddebug(u"CLASS: Plugin")
            self.generalLogger.debug(u'DEVICE START: %s' % ahbDev.name)

            if not ahbDev.id in self.globals['alexaHueBridge']:
                self.globals['alexaHueBridge'][ahbDev.id] = {}

            if not 'hubName' in self.globals['alexaHueBridge'][ahbDev.id]:    
                self.globals['alexaHueBridge'][ahbDev.id]['hubName'] = ahbDev.name

            props = ahbDev.pluginProps
            if 'alexaDevices' not in props:
                props['alexaDevices'] = json.dumps({})  # Empty dictionary in JSON container
                self.globals['alexaHueBridge'][ahbDev.id]['forceDeviceStopStart'] = False   
                ahbDev.replacePluginPropsOnServer(props)
                # Replacing Plugin Props on Server WILL NOT force a device stop /start

            uuid_changed = False
            uuidValue = ahbDev.pluginProps.get("uuid", str(uuid.uuid1()))
            if not 'uuid' in self.globals['alexaHueBridge'][ahbDev.id]:
                uuid_changed = True
            else:
                if self.globals['alexaHueBridge'][ahbDev.id]['uuid'] != uuidValue:
                    uuid_changed = True
            self.globals['alexaHueBridge'][ahbDev.id]['uuid'] = uuidValue

            host_changed = False
            host = ahbDev.pluginProps.get("host", None)  # host is stored in dev.pluginprops (no user visability)
            if host is None or host != self.globals['hostAddress']:
                host = self.globals['hostAddress']
                host_changed = True

            self.globals['alexaHueBridge'][ahbDev.id]['host'] = host

            port_changed = False
            port = ahbDev.pluginProps.get("port", 'auto')
            try:
                port = int(port)
            except:
                port = 'auto'

            if port == 'auto':
                port_changed = True
                for port in range(8178, 8200):
                    if port not in self.globals['portList']:
                        self.globals['portList'].append(int(port))
                        break
                else:
                    self.generalLogger.error("No available ports for auto allocation - specify in Device Config")
                    port = None
                    # CAN'T START Alexa-Hue Bridge Device !!!
                    return

            if port not in self.globals['portList']:
                self.globals['portList'].append(port)

            try:
                if ahbDev.address is None or ahbDev.address == '' or int(ahbDev.address) != int(port):
                    port_changed = True
            except:
                self.generalLogger.error("Alexa-Hue Bridge '{}' at address {} either has an invalid address or invalid port {} - specify in Device Config".format(ahbDev.name, ahbDev.address, port))
                return

            self.globals['alexaHueBridge'][ahbDev.id]['port'] = port

            if host_changed or port_changed or uuid_changed:
                self.globals['alexaHueBridge'][ahbDev.id]['forceDeviceStopStart'] = False   
                props["host"] = self.globals['alexaHueBridge'][ahbDev.id]['host']
                props["port"] = str(self.globals['alexaHueBridge'][ahbDev.id]['port'])
                props["address"]= str(self.globals['alexaHueBridge'][ahbDev.id]['port'])
                props["uuid"] = self.globals['alexaHueBridge'][ahbDev.id]['uuid']
                props["version"] = '3.0'
                ahbDev.replacePluginPropsOnServer(props)  # Replacing Plugin Props on Server will NOT force a device stop /start

            self.globals['alexaHueBridge'][ahbDev.id]['autoStartDiscovery'] = ahbDev.pluginProps.get("autoStartDiscovery", True)

            discoveryExpirationChanged = False
            discoveryExpiration = int(ahbDev.pluginProps.get("discoveryExpiration", '0'))  # Default 'Discovery Permanently On'

            if not 'discoveryExpiration' in self.globals['alexaHueBridge'][ahbDev.id]:
                discoveryExpirationChanged = True
            else:
                if self.globals['alexaHueBridge'][ahbDev.id]['discoveryExpiration'] != discoveryExpiration:
                    discoveryExpirationChanged = True
            self.globals['alexaHueBridge'][ahbDev.id]['discoveryExpiration'] = discoveryExpiration


            self.globals['alexaHueBridge'][ahbDev.id]['disableAlexaVariableId'] = int(ahbDev.pluginProps.get("disableAlexaVariableList", "0"))

            self.globals['alexaHueBridge'][ahbDev.id]['hideDisableAlexaVariableMessages'] = bool(ahbDev.pluginProps.get("hideDisableAlexaVariableMessages", False))

            if not 'publishedAlexaDevices' in self.globals['alexaHueBridge'][ahbDev.id]:    
                self.globals['alexaHueBridge'][ahbDev.id]['publishedAlexaDevices'] = {}

            props = ahbDev.pluginProps
            self.retrievePublishedDevices(props, ahbDev.id, True, False)  # List Alexa devices in this Alexa-Hue Bridge + output info message + don't Check for V2 definitions
        
            self.generalLogger.info(u"Starting Hue Bridge '%s' web server thread" % self.globals['alexaHueBridge'][ahbDev.id]['hubName'])

            start_webserver_required = False
            if not 'webServer' in self.globals['alexaHueBridge'][ahbDev.id]:
                start_webserver_required = True
            else:
                if host_changed or port_changed:
                    self.globals['alexaHueBridge'][ahbDev.id]['webServer'].stop()
                    self.sleep(5)  # wait 5 seconds (temporary fix?)
                    del self.globals['alexaHueBridge'][ahbDev.id]['webServer']
                    start_webserver_required = True
            if start_webserver_required == True:
                self.globals['alexaHueBridge'][ahbDev.id]['webServer'] = Httpd(self, ahbDev.id)
                self.globals['alexaHueBridge'][ahbDev.id]['webServer'].start()

            # Only start discovery if auto-start requested
            if not self.globals['alexaHueBridge'][ahbDev.id]['autoStartDiscovery']:
                self.generalLogger.info(u"Hue Bridge '%s' 'Auto Start Discovery' NOT requested" % self.globals['alexaHueBridge'][ahbDev.id]['hubName'])
                self.setDeviceDiscoveryState(False, ahbDev.id)
            else:
                self.generalLogger.info(u"Starting Hue Bridge '%s' discovery thread as 'Auto Start Discovery' requested" % self.globals['alexaHueBridge'][ahbDev.id]['hubName'])

                start_broadcaster_required = False
                if not 'broadcaster' in self.globals['alexaHueBridge'][ahbDev.id]:
                    start_broadcaster_required = True
                else:
                    if not self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'].is_alive():
                        start_broadcaster_required = True
                    elif host_changed or port_changed or uuid_changed or discoveryExpirationChanged:
                        self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'].stop()
                        self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'].join(5)
                        del self.globals['alexaHueBridge'][ahbDev.id]['broadcaster']
                        start_broadcaster_required = True
                if start_broadcaster_required == True:
                    self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'] = Broadcaster(self, ahbDev.id)
                    self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'].start()

                start_responder_required = False
                if not 'responder' in self.globals['alexaHueBridge'][ahbDev.id]:
                    start_responder_required = True
                else:
                    if not self.globals['alexaHueBridge'][ahbDev.id]['responder'].is_alive():
                        start_responder_required = True
                    elif host_changed or port_changed or uuid_changed or discoveryExpirationChanged:
                        self.globals['alexaHueBridge'][ahbDev.id]['responder'].stop()
                        self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'].join(5)
                        del self.globals['alexaHueBridge'][ahbDev.id]['responder']
                        start_responder_required = True
                if start_responder_required == True:
                    self.globals['alexaHueBridge'][ahbDev.id]['responder'] = Responder(self, ahbDev.id)
                    self.globals['alexaHueBridge'][ahbDev.id]['responder'].start()

                self.setDeviceDiscoveryState(True, ahbDev.id)
 
            self.generalLogger.info(u"Alexa-Hue Bridge '{}' started: Host: {} Port: {}".format(self.globals['alexaHueBridge'][ahbDev.id]['hubName'], self.globals['alexaHueBridge'][ahbDev.id]['host'], self.globals['alexaHueBridge'][ahbDev.id]['port']))

        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in deviceStartComm for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDev.id].name, sys.exc_traceback.tb_lineno, e))

    def deviceStopComm(self, ahbDev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        stoppedId = ahbDev.id
        stoppedName = ahbDev.name

        try:
            if 'webServer' in self.globals['alexaHueBridge'][stoppedId]:
                if self.globals['alexaHueBridge'][stoppedId]['webServer']:
                    self.globals['alexaHueBridge'][stoppedId]['webServer'].stop()
            if 'broadcaster' in self.globals['alexaHueBridge'][stoppedId]:
                if self.globals['alexaHueBridge'][stoppedId]['broadcaster']:
                    self.globals['alexaHueBridge'][stoppedId]['broadcaster'].stop()
            if 'responder' in self.globals['alexaHueBridge'][stoppedId]:
                if self.globals['alexaHueBridge'][stoppedId]['responder']:
                    self.globals['alexaHueBridge'][stoppedId]['responder'].stop()
        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in deviceStopComm for '%s'. Line '%s' has error='%s'" % (stoppedName, sys.exc_traceback.tb_lineno, e))

    def didDeviceCommPropertyChange(self, origDev, newDev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")
        self.generalLogger.debug(u'DID-DEVICE-COMM-PROPERTY-CHANGE: Old [%s] vs New [%s]' % (origDev.name, newDev.name))
        if newDev.deviceTypeId == EMULATED_HUE_BRIDGE_TYPEID and origDev.enabled and newDev.enabled:
            # if newDev.pluginProps['port'] == "auto" or newDev.pluginProps['port'] != newDev.address:
            #     self.generalLogger.debug(u'DID-DEVICE-COMM-PROPERTY-CHANGE: PORT AUTO OR CHANGED')
            #     return True
            if 'discoveryExpiration' in origDev.pluginProps and 'discoveryExpiration' in newDev.pluginProps:
                if origDev.pluginProps['discoveryExpiration'] != newDev.pluginProps['discoveryExpiration']:
                    self.generalLogger.debug(u'DID-DEVICE-COMM-PROPERTY-CHANGE [EXPIRE MINUTES]: Old [%s] vs New [%s]' % (origDev.pluginProps['discoveryExpiration'], newDev.pluginProps['discoveryExpiration']))
                    self.generalLogger.debug(u'DID-DEVICE-COMM-PROPERTY-CHANGE [AUTO START]: Old [%s] vs New [%s]' % (origDev.pluginProps['autoStartDiscovery'], newDev.pluginProps['autoStartDiscovery']))
                    return True
            if self.globals['alexaHueBridge'][newDev.id]['forceDeviceStopStart']: # If a force device stop start requested turn off request and action 
                self.globals['alexaHueBridge'][newDev.id]['forceDeviceStopStart'] = False
                return True
        return False

    def getDeviceConfigUiValues(self, pluginProps, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if typeId == EMULATED_HUE_BRIDGE_TYPEID:
            # Set internal storage for device
            if ahbDevId not in self.globals['alexaHueBridge']:
                self.globals['alexaHueBridge'][ahbDevId] = {}
            if 'hubName' not in self.globals['alexaHueBridge'][ahbDevId]:
                self.globals['alexaHueBridge'][ahbDevId]['hubName'] = indigo.devices[ahbDevId].name
            if 'publishedAlexaDevices' not in self.globals['alexaHueBridge'][ahbDevId]:
                self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'] = {}

            self.retrieveOtherPublishedDevices(ahbDevId)  # List Alexa devices in other Alexa-Hue Bridges        
            self.retrievePublishedDevices(pluginProps, ahbDevId, False, True)  # List Alexa devices in this Alexa-Hue Bridge + don't output info message + Check for V2 definitions

            # Set default values for Edit Device Settings... (ConfigUI)
            pluginProps["autoStartDiscovery"] = pluginProps.get("autoStartDiscovery", True)
            pluginProps["discoveryExpiration"] = pluginProps.get("discoveryExpiration", "0")
            pluginProps["uuid"] = pluginProps.get("uuid", str(uuid.uuid1()))
            pluginProps["host"] = pluginProps.get("host", "auto")
            pluginProps["port"] = pluginProps.get("port", "auto")

            pluginProps["disableAlexaVariableList"] = pluginProps.get("disableAlexaVariableList", "0")

            pluginProps["alexaDevicesListGlobal"] = SELECT_FROM_ALEXA_DEVICE_LIST
            pluginProps["alexaDevicesList"] = ALEXA_NEW_DEVICE
            pluginProps["alexaNameHueBridge"] = ""
            pluginProps["alexaNameActionDevice"] = "X"
            pluginProps["alexaNameIndigoDevice"] = ""
            pluginProps["alexaNameIndigoOnAction"] = ""
            pluginProps["alexaNameIndigoOffAction"] = ""
            pluginProps["alexaNameIndigoOnOffActionVariable"] = ""
            pluginProps["alexaNameIndigoDimAction"] = ""
            pluginProps["alexaNameIndigoDimActionVariable"] = ""

            pluginProps["newAlexaDevice"] = "NEW"

            pluginProps["actionOrDevice"] = "D"  # Default Device

            pluginProps["sourceDeviceMenu"] = "0"
            pluginProps["newAlexaName"] = ""
            pluginProps["sourceOnActionMenu"] = "0"  # NO ACTION
            pluginProps["sourceOffActionMenu"] = "0"  # NO ACTION
            pluginProps["sourceOnOffActionVariableMenu"] = "0"  # NO VARIABLE
            pluginProps["sourceDimActionMenu"] = "0"  # NO ACTION
            pluginProps["sourceDimActionVariableMenu"] = "0"  # NO VARIABLE

        return super(Plugin, self).getDeviceConfigUiValues(pluginProps, typeId, ahbDevId)

    ########################################
    # This method is called to load the stored json data and make sure the Alexa Name keys are valid before returning data
    # i.e. remove leading/trailing spaces, remove caharcters ',', ';', replace multiple concurrent spaces with one space, force to lower case
    ########################################
    def jsonLoadsProcess(self, dataToLoad):

        publishedAlexaDevices = json.loads(dataToLoad)

        alexaDeviceNameKeyList = []
        for alexaDeviceNameKey, alexaDeviceData in publishedAlexaDevices.iteritems():
            alexaDeviceNameKeyList.append(alexaDeviceNameKey)

        for alexaDeviceNameKey in alexaDeviceNameKeyList:
            alexaDeviceNameKeyProcessed = ' '. join((alexaDeviceNameKey.strip().lower().replace(',',' ').replace(';',' ')).split())
            if alexaDeviceNameKeyProcessed != alexaDeviceNameKey:
                publishedAlexaDevices[alexaDeviceNameKeyProcessed] = publishedAlexaDevices.pop(alexaDeviceNameKey)

        return publishedAlexaDevices

    ########################################
    # This method is called to refresh the list of published Alexa devices for a hueBridge device.
    ########################################
    def retrievePublishedDevices(self, valuesDict, ahbDevId, infoMsg, convertVersionTwoDevices):

        try:
            self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']  = {}
            self.globals['alexaHueBridge'][ahbDevId]['hashKeys'] = {}

            if 'alexaDevices' not in valuesDict:
                valuesDict['alexaDevices'] = json.dumps({})  # Empty dictionary in JSON container

            publishedAlexaDevices = self.jsonLoadsProcess(valuesDict['alexaDevices'])

            for alexaDeviceNameKey, alexaDeviceData in publishedAlexaDevices.iteritems():
                if alexaDeviceData['mode'] == 'D':  # Device
                    hashKey = alexaDeviceData.get('hashKey', self.createHashKey(alexaDeviceNameKey))
                    self.globals['alexaHueBridge'][ahbDevId]['hashKeys'][hashKey] = alexaDeviceNameKey
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey] = {}
                    # self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['hashKey'] = hashKey
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['hashKey'] = alexaDeviceData['hashKey']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['name']    = alexaDeviceData['name']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['mode']    = alexaDeviceData['mode']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['devName'] = alexaDeviceData['devName']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['devId']   = alexaDeviceData['devId']

                    self.globals['alexaHueBridge']['publishedHashKeys'][alexaDeviceData['hashKey']] = ahbDevId

                elif alexaDeviceData['mode'] == 'A':  # Action
                    hashKey = alexaDeviceData.get('hashKey', self.createHashKey(alexaDeviceNameKey))
                    self.globals['alexaHueBridge'][ahbDevId]['hashKeys'][hashKey] = alexaDeviceNameKey
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey] = {}
                    # self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['hashKey'] = hashKey
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['hashKey'] = alexaDeviceData['hashKey']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['name']            = alexaDeviceData['name']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['mode']            = alexaDeviceData['mode']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['actionOnId']      = alexaDeviceData['actionOnId']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['actionOffId']     = alexaDeviceData['actionOffId']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['variableOnOffId'] = alexaDeviceData['variableOnOffId']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['actionDimId']     = alexaDeviceData['actionDimId']
                    self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['variableDimId']   = alexaDeviceData['variableDimId']

                    self.globals['alexaHueBridge']['publishedHashKeys'][alexaDeviceData['hashKey']] = ahbDevId

                else:  # Not used
                    continue

            # If no Alexa Devices defined and not called from Config UI - check if Alexa Devices exist from V2 of the plugin and if so convert to V3 format

            if len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']) == 0 and convertVersionTwoDevices:
                for dev in indigo.devices:
                    if dev.deviceTypeId != 'emulatedHueBridge':
                        props = dev.pluginProps
                        for versionTwoAhbKey, versionTwoAlexaDeviceData in props.iteritems():
                            if versionTwoAhbKey[:4] == 'ahb-':
                                versionTwoAhbId = int(versionTwoAhbKey[4:])
                                # Now check if the Indigo Device was previously referenced by this Alexa-Hue Bridge
                                if versionTwoAhbId == ahbDevId:
                                    # Yes it was!
                                    versionTwoAlexaDeviceName = dev.name
                                    if 'alternate-name' in versionTwoAlexaDeviceData:
                                        versionTwoAlexaDeviceName = versionTwoAlexaDeviceData['alternate-name']
                                    versionTwoAlexaDeviceNameKey = ' '. join((versionTwoAlexaDeviceName.strip().lower()).split())
                                    if 'published' in versionTwoAlexaDeviceData:
                                        if versionTwoAlexaDeviceData['published'].lower() == 'true':
                                            # Do validity checks and discard (with message) if invalid
                                            if ('|' in versionTwoAlexaDeviceName) or (',' in versionTwoAlexaDeviceName) or (';' in versionTwoAlexaDeviceName):
                                                self.generalLogger.error(u"Alexa Device (Plugin V2.x.x) '%s' definition detected in Indigo Device '%s': Unable to convert as Alexa Device Name cannot contain the vertical bar character i.e. '|', the comma character i.e. ',' or the semicolon character i.e. ';'." % (versionTwoAlexaDeviceName, dev.name)) 
                                                continue

                                            duplicateDetected = False
                                            for alexaHueBridgeId, alexaHueBridgeData in self.globals['alexaHueBridge']['publishedOtherAlexaDevices'].iteritems():
                                                for alexaDeviceNameKey, AlexaDeviceData in alexaHueBridgeData.iteritems():
                                                    if versionTwoAlexaDeviceNameKey == alexaDeviceNameKey:
                                                        duplicateDetected = True
                                                        alexaDeviceName = AlexaDeviceData['name']
                                                        if ahbDevId == alexaHueBridgeData:
                                                            # In theory this can't happen as this logic is only executed when the Alexa-Hue bridge has no Alexa devices!
                                                            self.generalLogger.error(u"Alexa Device (Plugin V2.x.x) '%s' definition detected in Indigo Device '%s': Unable to convert as Alexa Device Name this Alexa-Hue Bridge." % (alexaDeviceName, dev.name)) 
                                                        else:
                                                            alexaHueBridgeName = indigo.devices[alexaHueBridgeId].name
                                                            self.generalLogger.error(u"Alexa Device (Plugin V2.x.x) '%s' definition detected in Indigo Device '%s': Unable to convert as Alexa Device Name is already allocated on Alexa-Hue Bridge '%s'" % (alexaDeviceName, dev.name, alexaHueBridgeName)) 
                                            if duplicateDetected:
                                                continue
            
                                            publishedAlexaDevices[versionTwoAlexaDeviceNameKey] = {}
                                            hashKey = self.createHashKey(versionTwoAlexaDeviceNameKey)
                                            publishedAlexaDevices[versionTwoAlexaDeviceNameKey]['hashKey'] = hashKey
                                            publishedAlexaDevices[versionTwoAlexaDeviceNameKey]['name'] = versionTwoAlexaDeviceName 
                                            publishedAlexaDevices[versionTwoAlexaDeviceNameKey]['mode'] = 'D'
                                            publishedAlexaDevices[versionTwoAlexaDeviceNameKey]['devName'] = dev.name
                                            publishedAlexaDevices[versionTwoAlexaDeviceNameKey]['devId'] = dev.id

                                            self.globals['alexaHueBridge'][ahbDevId]['hashKeys'][hashKey] = versionTwoAlexaDeviceNameKey
                                            
                                            self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][versionTwoAlexaDeviceNameKey] = {}
                                            self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][versionTwoAlexaDeviceNameKey]['hashKey'] = hashKey
                                            self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][versionTwoAlexaDeviceNameKey]['name']    = versionTwoAlexaDeviceName 
                                            self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][versionTwoAlexaDeviceNameKey]['mode']    = 'D'
                                            self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][versionTwoAlexaDeviceNameKey]['devName'] = dev.name
                                            self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][versionTwoAlexaDeviceNameKey]['devId']   = dev.id

                                            self.globals['alexaHueBridge']['publishedHashKeys'][hashKey] = ahbDevId

                                            self.generalLogger.info(u"Alexa Device (Plugin V2.x.x) '%s' definition detected in Indigo Device '%s': Converting to V3 format." % (versionTwoAlexaDeviceName, dev.name)) 

                if len(valuesDict['alexaDevices']) > 0:
                    valuesDict['alexaDevices'] = json.dumps(publishedAlexaDevices)

            numberPublished = len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'])
            if infoMsg or numberPublished > DEVICE_LIMIT:
                # Figure out number of devices to be able to create user friendly message
                if numberPublished == 0:
                    numberPublishedUI = 'no Alexa Devices'
                elif numberPublished == 1:
                    numberPublishedUI = 'one Alexa Device'
                else:
                    numberPublishedUI = str('%s Alexa Devices' % numberPublished)

                if numberPublished <= DEVICE_LIMIT:
                    self.generalLogger.info(u"'%s' has %s published" % (self.globals['alexaHueBridge'][ahbDevId]['hubName'], numberPublishedUI))
                else:
                    self.generalLogger.error(u"'%s' has %s published [LIMIT OF %s DEVICES EXCEEDED - DISCOVERY MAY NOT WORK!!!]" % (self.globals['alexaHueBridge'][ahbDevId]['hubName'], numberPublishedUI, DEVICE_LIMIT))
                    self.generalLogger.error(u"Move excess Alexa devices to another existing or new Alexa-Hue Bridge")

            return valuesDict
        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in retrievePublishedDevices for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))



    ########################################
    # This method is called to refresh the list of published Alexa devices in other hueBridge devices.
    ########################################
    def retrieveOtherPublishedDevices(self, ahbDevId):

        try:
            self.globals['alexaHueBridge']['publishedOtherAlexaDevices'] = {}

            for alexaHueBridge in indigo.devices:
                if alexaHueBridge.deviceTypeId == 'emulatedHueBridge' and alexaHueBridge.id != ahbDevId:
                    # At this point it is an Alexa-Hue Bridge Device and not the current Alexa-Hue Bridge Device
                    props = alexaHueBridge.pluginProps
                    alexaHueBridgeId = alexaHueBridge.id
                    if 'alexaDevices' in props:
                        publishedAlexaDevices = self.jsonLoadsProcess(props['alexaDevices'])
                        self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId] = {}
                        for alexaDeviceNameKey, alexaDeviceData in publishedAlexaDevices.iteritems():
                            if alexaDeviceData['mode'] == 'D':  # Device
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey] = {}
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['name']    = alexaDeviceData['name']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['hashKey'] = alexaDeviceData['hashKey']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['mode']    = alexaDeviceData['mode']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['devName'] = alexaDeviceData['devName']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['devId']   = alexaDeviceData['devId']
                            elif alexaDeviceData['mode'] == 'A':  # Action
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey] = {}
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['name']            = alexaDeviceData['name']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['hashKey']         = alexaDeviceData['hashKey']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['mode']            = alexaDeviceData['mode']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['actionOnId']      = alexaDeviceData['actionOnId']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['actionOffId']     = alexaDeviceData['actionOffId']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['variableOnOffId'] = alexaDeviceData['variableOnOffId']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['actionDimId']     = alexaDeviceData['actionDimId']
                                self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['variableDimId']   = alexaDeviceData['variableDimId']
                            else:  # Not used
                                continue
        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in retrieveOtherPublishedDevices for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))

    def validateDeviceConfigUi(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if typeId == EMULATED_HUE_BRIDGE_TYPEID:
            self.generalLogger.debug(u"Validating Device config for type: " + typeId)
            self.generalLogger.debug(u'validateDeviceConfigUi VALUESDICT = %s' % valuesDict)

            errorsDict = indigo.Dict()

            try:
                amount = int(valuesDict["discoveryExpiration"])
                if amount not in range(-1, 11):  # -1 = No Discovery, 0 = Always Discover, 1 - 10 = Number of minutes to discover
                    raise
            except:
                errorsDict["discoveryExpiration"] = "'Discovery Expiration' must be a positive integer from 1 to 10 (minutes) or 'No Discovery' or 'Discovery Permanently On'"
                errorsDict["showAlertText"] = "'Discovery Expiration' is invalid"
                return (False, valuesDict, errorsDict)

            try:
                disableAlexaVariableId = int(valuesDict.get("disableAlexaVariableList", "0"))
                if disableAlexaVariableId != 0:
                    if indigo.variables[disableAlexaVariableId].value.lower() != 'true' and indigo.variables[disableAlexaVariableId].value.lower() != 'false':
                        raise
            except:
                errorsDict["disableAlexaVariableList"] = "'Disable Alexa Variable' must be 'true' or 'false' or '-- NO SELECTION --'"
                errorsDict["showAlertText"] = "Selected variable is not valid"
                return (False, valuesDict, errorsDict)

            alexaDeviceNameSorted, alexaDeviceName, alexaHueBridgeId = valuesDict["alexaDevicesList"].split("|")
            alexaHueBridgeId = int(alexaHueBridgeId)

            alexaName = ''
            if alexaHueBridgeId == 0:
                alexaName = valuesDict['newAlexaName']
                errorMessage = "'New Alexa Device Name' is present. Have you done an 'Add New Alexa Device' for the new Alexa device? Either Add the Alexa device or clear 'New Alexa Device Name' to enable Save. This check is to prevent any changes being lost."
            else:
                alexaName = valuesDict['updatedAlexaDeviceName']
                errorMessage = "'Alexa Device Name' is present. Have you done an 'Update Alexa Device' for the existing Alexa device? Either Update the Alexa device or clear 'Alexa Device Name' to enable Save. This check is to prevent any changes being lost."

            if alexaName != '':
                errorsDict["alexaDevicesList"] = errorMessage
                errorsDict["showAlertText"] = errorMessage
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

            port = valuesDict.get("port", 'auto')
            port_changed = False
            try:
                if int(indigo.devices[ahbDevId].address) != int(port):
                    port_changed = True
            except:
                port_changed = True
            if port_changed:    
                self.globals['alexaHueBridge'][ahbDevId]['forceDeviceStopStart'] = True 

            self.globals['alexaHueBridge'][ahbDevId]['autoStartDiscovery'] = valuesDict.get("autoStartDiscovery", True)

            self.globals['alexaHueBridge'][ahbDevId]['discoveryExpiration'] = int(valuesDict.get("discoveryExpiration", "0"))

            self.globals['alexaHueBridge'][ahbDevId]['disableAlexaVariableId'] = int(valuesDict.get("disableAlexaVariableList", "0"))

            self.globals['alexaHueBridge'][ahbDevId]['hideDisableAlexaVariableMessages'] = bool(valuesDict.get("hideDisableAlexaVariableMessages", False))

            numberPublished = len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'])

            if numberPublished == 0:
                numberPublishedUI = 'no Alexa Devices'
            elif numberPublished == 1:
                numberPublishedUI = 'one Alexa Device'
            else:
                numberPublishedUI = str('%s Alexa Devices' % numberPublished)

            if numberPublished <= DEVICE_LIMIT:
                self.generalLogger.info(u"'%s' updated and now has %s published" % (self.globals['alexaHueBridge'][ahbDevId]['hubName'], numberPublishedUI))
            else:
                self.generalLogger.error(u"'%s' updated and now has %s published [LIMIT OF %s DEVICES EXCEEDED - DISCOVERY MAY NOT WORK!!!]" % (self.globals['alexaHueBridge'][ahbDevId]['hubName'], numberPublishedUI, DEVICE_LIMIT))
                self.generalLogger.error(u"Move excess Alexa devices to another existing or new Alexa-Hue Bridge")

            self.generalLogger.debug(u"'closePrefsConfigUi' completed for '%s'" % self.globals['alexaHueBridge'][ahbDevId]['hubName'])

            return valuesDict

        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in closedDeviceConfigUi for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))
    


    ########################################
    # The next two methods should catch when a device name changes in Indigo and when a device we have published
    # gets deleted - we'll just rebuild the device list cache in those situations.
    ########################################
    def deviceDeleted(self, dev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if dev.deviceTypeId != EMULATED_HUE_BRIDGE_TYPEID:
            for ahbDevId in self.globals['alexaHueBridge']:
                if 'publishedAlexaDevices' in self.globals['alexaHueBridge'][ahbDevId]:
                    if dev.id in self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']:
                        self.generalLogger.info(u"A device (%s) that was published has been deleted - you'll probably want use the Alexa app to forget that device." % dev.name)
                        self.refreshDeviceList(ahbDevId)

        super(Plugin, self).deviceDeleted(dev)

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
    # This method is called to generate a list of variables.
    ########################################
    def dimVariablesToList(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.methodTracer.threaddebug(u"CLASS: Plugin")
        # Set a default with id 0
        # Iterates through the variable list

        variableList = [(0, 'NO VARIABLE')]
        for variable in indigo.variables:
            variableList.append((variable.id, variable.name))
        return variableList


    ########################################
    # This method is called to generate a list of actions.
    ########################################
    def actionsToList(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.methodTracer.threaddebug(u"CLASS: Plugin")
        # Set a default with id 0
        # Iterates through the action list

        actionList = [(0, '-- Select Action --')]
        for action in indigo.actionGroups:
             actionList.append((action.id, action.name))
        return actionList


    ########################################
    # This method is called to generate a list of actions (Including none i.e. 'NO ACTION".
    ########################################
    def actionsToListIncludingNone(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.methodTracer.threaddebug(u"CLASS: Plugin")
        # Set a default with id 0
        # Iterates through the action list

        actionList = [(0, 'NO ACTION')]
        for action in indigo.actionGroups:
             actionList.append((action.id, action.name))
        return actionList

    def disableAlexaVariableList(self, filter="", valuesDict=None, typeId="", targetId=0):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        disableAlexa_dict = list()
        disableAlexa_dict.append(("0", "-- NO SELECTION --"))

        try:
            disableAlexaVariableId = int(valuesDict.get("disableAlexaVariableList", "0"))
            if disableAlexaVariableId != 0:
                if indigo.variables[disableAlexaVariableId].value.lower() != 'true' and indigo.variables[disableAlexaVariableId].value.lower() != 'false':
                    raise
        except:
            if disableAlexaVariableId in indigo.variables:
                variableName = indigo.variables[disableAlexaVariableId].name
            else:
                variableName = 'VARIABLE IS MISSING'
            disableAlexa_dict.append((str(disableAlexaVariableId), "-- INVALID: {} --".format(variableName)))
        for variable in indigo.variables.iter():
            if variable.value.lower() == 'true' or variable.value.lower() == 'false':
                variable_found = (str(variable.id), str(variable.name))
                disableAlexa_dict.append(variable_found)
        myArray = disableAlexa_dict
        return myArray

    ########################################
    # This method is called to generate a list of the names of "devices" defined to Alexa across all Alexa-Hue bridges defined to Indigo.
    ########################################
    def alexaDevicesListGlobal(self, filter, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        self.globals['alexaDevicesListGlobal'] = {}

        allocatedAlexaDevicesListGlobal = [(SELECT_FROM_ALEXA_DEVICE_LIST, "-- Select Alexa Device to Display Info --")]

        # scan list of other Alexa-Hue Bridges
        for alexaHueBridgeId, alexaHueBridgeData in self.globals['alexaHueBridge']['publishedOtherAlexaDevices'].iteritems():
           for alexaDeviceNameKey, alexaDeviceData in alexaHueBridgeData.iteritems():
                alexaDeviceNameKey = alexaDeviceNameKey.lower().replace(',',' ').replace(';',' ')
                alexaDeviceName = alexaDeviceData['name'].replace(',',' ').replace(';',' ')
                self.globals['alexaDevicesListGlobal'][alexaDeviceNameKey] = int(alexaHueBridgeId)
                alexaDeviceListKey = alexaDeviceNameKey + '|' + alexaDeviceName + '|' + str(alexaHueBridgeId)
                alexaDeviceListKey = str('%s|%s|%s' %(alexaDeviceNameKey, alexaDeviceName, alexaHueBridgeId))
                allocatedAlexaDevicesListGlobal.append((alexaDeviceListKey, alexaDeviceName))

        for alexaDeviceNameKey, alexaDeviceData in self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'].iteritems():
            alexaDeviceNameKey = alexaDeviceNameKey.lower().replace(',',' ').replace(';',' ')
            alexaDeviceName = alexaDeviceData['name'].replace(',',' ').replace(';',' ')
            self.globals['alexaDevicesListGlobal'][alexaDeviceNameKey] = ahbDevId
            alexaDeviceListKey = alexaDeviceNameKey + '|' + alexaDeviceName + '|' + str(ahbDevId)
            allocatedAlexaDevicesListGlobal.append((alexaDeviceListKey, alexaDeviceName))

        if len(allocatedAlexaDevicesListGlobal) == 1:  # No Alexa Devices found
            allocatedAlexaDevicesListGlobal = [(SELECT_FROM_ALEXA_DEVICE_LIST, "No Alexa Devices published")]

        allocatedAlexaDevicesListGlobal = sorted(allocatedAlexaDevicesListGlobal, key= lambda item: item[0])
        return allocatedAlexaDevicesListGlobal

    def alexaDevicesListGlobalSelection(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if "alexaDevicesListGlobal" in valuesDict:
            alexaDeviceNameKey, alexaDeviceName, alexaHueBridgeId = valuesDict["alexaDevicesListGlobal"].split("|")
            # mode: 'A' = Action, 'D' = Device
            # Action has 4 ids: On,Off,DIM,VAR x 2
            # Device has 1 id: device

            alexaHueBridgeId = int(alexaHueBridgeId)
            if alexaHueBridgeId == 0:  # = (SELECT_FROM_ALEXA_DEVICE_LIST, "-- Select Alexa Device to Display Info --")
                valuesDict["alexaNameActionDevice"] = "X"
                valuesDict["alexaNameHueBridge"] = ''
            else:
                if alexaHueBridgeId != ahbDevId:
                    mode = self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['mode']
                    valuesDict["alexaNameIndigoHashKey"] = self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['hashKey']  
                    if mode == 'A':
                        valuesDict["alexaNameActionDevice"] = "A"
                        actionOnId = int(self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['actionOnId'])
                        actionOffId = int(self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['actionOffId'])
                        variableOnOffId = int(self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['variableOnOffId'])
                        actionDimId = int(self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['actionDimId'])
                        variableDimId = int(self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['variableDimId'])
                        
                        if actionOnId == 0:
                            valuesDict["alexaNameIndigoOnAction"] = 'NO ACTION'
                        else:
                            if actionOnId in indigo.actionGroups:
                                valuesDict["alexaNameIndigoOnAction"] = indigo.actionGroups[actionOnId].name
                            else:
                                valuesDict["alexaNameIndigoOnAction"] = 'Action #%s not found' % actionOnId
                        
                        if actionOffId == 0:
                            valuesDict["alexaNameIndigoOffAction"] = 'NO ACTION'
                        else:
                            if actionOffId in indigo.actionGroups:
                                valuesDict["alexaNameIndigoOffAction"] = indigo.actionGroups[actionOffId].name
                            else:
                                valuesDict["alexaNameIndigoOffAction"] = 'Action #%s not found' % actionOffId
                        
                        if variableOnOffId == 0:
                            valuesDict["alexaNameIndigoOnOffActionVariable"] = 'NO VARIABLE'
                        else:
                            if variableOnOffId in indigo.variables:
                                valuesDict["alexaNameIndigoOnOffActionVariable"] = indigo.variables[variableOnOffId].name
                            else:
                                valuesDict["alexaNameIndigoOnOffActionVariable"] = 'Variable #%s not found' % variableOnOffId
                        
                        if actionDimId == 0:
                            valuesDict["alexaNameIndigoDimAction"] = 'NO ACTION'
                        else:
                            if actionDimId in indigo.actionGroups:
                                valuesDict["alexaNameIndigoDimAction"] = indigo.actionGroups[actionDimId].name
                            else:
                                valuesDict["alexaNameIndigoDimAction"] = 'Action #%s not found' % actionDimId
                        
                        if variableDimId == 0:
                            valuesDict["alexaNameIndigoDimActionVariable"] = 'NO VARIABLE'
                        else:
                            if variableDimId in indigo.variables:
                                valuesDict["alexaNameIndigoDimActionVariable"] = indigo.variables[variableDimId].name
                            else:
                                valuesDict["alexaNameIndigoDimActionVariable"] = 'Variable #%s not found' % variableDimId

                    else:
                        valuesDict["alexaNameActionDevice"] = "D"
                        deviceName = self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['devName'].replace(',',' ').replace(';',' ')
                        deviceId = int(self.globals['alexaHueBridge']['publishedOtherAlexaDevices'][alexaHueBridgeId][alexaDeviceNameKey]['devId'])
                        if deviceId in indigo.devices:
                            valuesDict["alexaNameIndigoDevice"] = deviceName
                        else:
                            valuesDict["alexaNameIndigoDevice"] = 'Device #%s not found (\'%s\' )' % (deviceId, deviceName)

                else:
                    mode = self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['mode'] 
                    valuesDict["alexaNameIndigoHashKey"] = self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]['hashKey'] 
                    if mode == 'A':
                        valuesDict["alexaNameActionDevice"] = "A"

                        actionOnId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['actionOnId'])
                        actionOffId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['actionOffId'])
                        variableOnOffId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['variableOnOffId'])
                        actionDimId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['actionDimId'])
                        variableDimId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['variableDimId'])
                        
                        if actionOnId == 0:
                            valuesDict["alexaNameIndigoOnAction"] = 'NO ACTION'
                        else:
                            if actionOnId in indigo.actionGroups:
                                valuesDict["alexaNameIndigoOnAction"] = indigo.actionGroups[actionOnId].name
                            else:
                                valuesDict["alexaNameIndigoOnAction"] = 'Action #%s not found' % actionOnId

                        if actionOffId == 0:
                            valuesDict["alexaNameIndigoOffAction"] = 'NO ACTION'
                        else:
                            if actionOffId in indigo.actionGroups:
                                valuesDict["alexaNameIndigoOffAction"] = indigo.actionGroups[actionOffId].name
                            else:
                                valuesDict["alexaNameIndigoOffAction"] = 'Action #%s not found' % actionOffId
                        
                        if variableOnOffId == 0:
                            valuesDict["alexaNameIndigoOnOffActionVariable"] = 'NO VARIABLE'
                        else:
                            if variableOnOffId in indigo.variables:
                                valuesDict["alexaNameIndigoOnOffActionVariable"] = indigo.variables[variableOnOffId].name
                            else:
                                valuesDict["alexaNameIndigoOnOffActionVariable"] = 'Variable #%s not found' % variableOnOffId
                        
                        if actionDimId == 0:
                            valuesDict["alexaNameIndigoDimAction"] = 'NO ACTION'
                        else:
                            if actionDimId in indigo.actionGroups:
                                valuesDict["alexaNameIndigoDimAction"] = indigo.actionGroups[actionDimId].name
                            else:
                                valuesDict["alexaNameIndigoDimAction"] = 'Action #%s not found' % actionDimId
                        
                        if variableDimId == 0:
                            valuesDict["alexaNameIndigoDimActionVariable"] = 'NO VARIABLE'
                        else:
                            if variableDimId in indigo.variables:
                                valuesDict["alexaNameIndigoDimActionVariable"] = indigo.variables[variableDimId].name
                            else:
                                valuesDict["alexaNameIndigoDimActionVariable"] = 'Variable #%s not found' % variableDimId
                    else:
                        valuesDict["alexaNameActionDevice"] = "D"
                        deviceName = self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['devName'].replace(',',' ').replace(';',' ')
                        deviceId = self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['devId']
                        if deviceId in indigo.devices:
                            valuesDict["alexaNameIndigoDevice"] = deviceName
                        else:
                            valuesDict["alexaNameIndigoDevice"] = 'Device #%s not found (\'%s\' )' % (deviceId, deviceName)
                valuesDict["alexaNameHueBridge"] = indigo.devices[int(alexaHueBridgeId)].name

        return valuesDict

   ########################################
    # This method is called to generate a list of the names of "devices" defined to Alexa for an Alexa-Hue Bridge device.
    ########################################
    def alexaDevicesListLocal(self, filter, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        allocatedAlexaDevicesList = [(ALEXA_NEW_DEVICE, "-- Add New Alexa Device --")]


        for alexaDeviceNameKey, alexaDeviceData in self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'].iteritems():
            alexaDeviceNameKey = alexaDeviceNameKey.lower().replace(',',' ').replace(';',' ')
            alexaDeviceName = alexaDeviceData['name'].replace(',',' ').replace(';',' ')
            alexaDeviceListKey = alexaDeviceNameKey + '|' + alexaDeviceName + '|' + str(ahbDevId)
            allocatedAlexaDevicesList.append((alexaDeviceListKey, alexaDeviceName))

        allocatedAlexaDevicesList = sorted(allocatedAlexaDevicesList, key= lambda item: item[0])
        return allocatedAlexaDevicesList

    def alexaDevicesListLocalSelection(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if "alexaDevicesList" in valuesDict:
            alexaDeviceNameKey, alexaDeviceName, alexaHueBridgeId = valuesDict["alexaDevicesList"].split("|")
            alexaDeviceNameKey.replace(',',' ').replace(';',' ')
            alexaDeviceName.replace(',',' ').replace(';',' ')

            alexaHueBridgeId = int(alexaHueBridgeId)
            if  alexaHueBridgeId == 0:
                valuesDict["newAlexaDevice"] = 'NEW'
                valuesDict["actionOrDevice"] = "D"
                valuesDict["sourceDeviceMenu"] = 0
                valuesDict["sourceOnActionMenu"] = 0
                valuesDict["sourceOffActionMenu"] = 0
                valuesDict["sourceDimActionMenu"] = 0
                valuesDict["sourceDimActionVariableMenu"] = 0
            else:
                valuesDict["newAlexaDevice"] = 'EXISTING'
                mode = self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['mode'] 
                if mode == 'A':
                    valuesDict["actionOrDevice"] = "A"
                    valuesDict["updatedAlexaDeviceName"] = alexaDeviceName
                    actionOnId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['actionOnId'])
                    actionOffId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['actionOffId'])
                    variableOnOffId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['variableOnOffId'])
                    actionDimId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['actionDimId'])
                    variableDimId = int(self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['variableDimId'])
                    if actionOnId == 0:
                        valuesDict["sourceOnActionMenu"] = 0
                    else:
                        valuesDict["sourceOnActionMenu"] = actionOnId
                    if actionOffId == 0:
                        valuesDict["sourceOffActionMenu"] = 0
                    else:
                        valuesDict["sourceOffActionMenu"] = actionOffId
                    if variableOnOffId == 0:
                        valuesDict["sourceOnOffActionVariableMenu"] = 0
                    else:
                        valuesDict["sourceOnOffActionVariableMenu"] = variableOnOffId
                    if actionDimId == 0:
                        valuesDict["sourceDimActionMenu"] = 0
                    else:
                        valuesDict["sourceDimActionMenu"] = actionDimId
                    if variableDimId == 0:
                        valuesDict["sourceDimActionVariableMenu"] = 0
                    else:
                        valuesDict["sourceDimActionVariableMenu"] = variableDimId
                else:
                    valuesDict["actionOrDevice"] = "D"
                    valuesDict["updatedAlexaDeviceName"] = alexaDeviceName
                    valuesDict["sourceDeviceMenu"] = self.globals['alexaHueBridge'][alexaHueBridgeId]['publishedAlexaDevices'][alexaDeviceNameKey]['devId']
                # valuesDict["alexaNameHueBridge"] = indigo.devices[int(alexaHueBridgeId)].name

        return valuesDict

    ########################################
    # These are the methods that's called when devices are selected from the various lists/menus. They enable other
    # as necessary.
    ########################################
    def selectDeviceToAddUpdate(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        # Get the device ID of the selected device
        deviceId = valuesDict["sourceDeviceMenu"]
        # If the device id isn't empty (should never be)
        if deviceId == '0' or deviceId == '':

            pass

        else:

            dev = indigo.devices[int(deviceId)]

            if valuesDict["newAlexaName"]== '':
                valuesDict["newAlexaName"] = dev.name
        return valuesDict

    ########################################
    # This is the method that's called by the 'Add New Alexa Device' button in the config dialog.
    ########################################
    def addNewAlexaDevice(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        if len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']) >= DEVICE_LIMIT:
            errorText = "You can't publish any more Alexa Devices - you've reached the maximum of %i imposed by the plugin on behalf of Amazon Alexa." % DEVICE_LIMIT
            self.generalLogger.error(errorText)
            errorsDict = indigo.Dict()
            errorsDict["showAlertText"] = errorText
            return (valuesDict, errorsDict)

        if valuesDict["newAlexaName"] == '':
            errorsDict = indigo.Dict()
            errorsDict["newAlexaName"] = "New Alexa Name is missing and must be present."
            errorsDict["showAlertText"] = "New Alexa Name is missing and must be present."
            return (valuesDict, errorsDict)

        if '|' in valuesDict["newAlexaName"]:
            errorsDict = indigo.Dict()
            errorsDict["newAlexaName"] = "New Alexa Name cannot contain the vertical bar character i.e. '|'"
            errorsDict["showAlertText"] = "New Alexa Name cannot contain the vertical bar character i.e. '|'"
            return (valuesDict, errorsDict) 

        if ',' in valuesDict["newAlexaName"]:
            errorsDict = indigo.Dict()
            errorsDict["newAlexaName"] = "New Alexa Name cannot contain the comma character i.e. ','"
            errorsDict["showAlertText"] = "New Alexa Name cannot contain the comma character i.e. ','"
            return (valuesDict, errorsDict) 

        if ';' in valuesDict["newAlexaName"]:
            errorsDict = indigo.Dict()
            errorsDict["newAlexaName"] = "New Alexa Name cannot contain the semicolon character i.e. ';'"
            errorsDict["showAlertText"] = "New Alexa Name cannot contain the semicolon character i.e. ';'"
            return (valuesDict, errorsDict) 

        newAlexaName = valuesDict["newAlexaName"]
        newAlexaNameKey = newAlexaName.lower()
        if newAlexaNameKey in self.globals['alexaDevicesListGlobal']:
            alexaHueBridgeId = self.globals['alexaDevicesListGlobal'][newAlexaNameKey]
            if ahbDevId == alexaHueBridgeId:
                errorsDict = indigo.Dict()
                errorsDict["newAlexaName"] = "Duplicate Alexa Name"
                errorsDict["showAlertText"] = "Alexa Device Name '%s' is already allocated on this Alexa-Hue Bridge" % newAlexaName
            else: 
                alexaHueBridgeName = indigo.devices[alexaHueBridgeId].name
                errorsDict = indigo.Dict()
                errorsDict["newAlexaName"] = "Duplicate Alexa Name"
                errorsDict["showAlertText"] = "Alexa Device Name '%s' is already allocated on Alexa-Hue Bridge '%s'" % (newAlexaName, alexaHueBridgeName)
            return (valuesDict, errorsDict)

        if valuesDict["actionOrDevice"] == 'D':
            devId = int(valuesDict["sourceDeviceMenu"])
            if devId == 0:
                errorsDict = indigo.Dict()
                errorsDict["newAlexaName"] = "Indigo Device not selected"
                errorsDict["showAlertText"] = "No Indigo device selected for Alexa Device Name '%s'" % (newAlexaName)
                return (valuesDict, errorsDict)
        else: # Assume 'A' = Action
            actionOnId = int(valuesDict["sourceOnActionMenu"])
            actionOffId = int(valuesDict["sourceOffActionMenu"])
            if actionOnId == 0 or actionOffId == 0:
                errorsDict = indigo.Dict()
                errorsDict["newAlexaName"] = "Indigo Actions not selected for On or Off or both"
                errorsDict["showAlertText"] = "Indigo Actions not selected for On or Off or both, for Alexa Device Name '%s'" % (newAlexaName)
                return (valuesDict, errorsDict)



        try:
            publishedAlexaDevices = self.jsonLoadsProcess(valuesDict['alexaDevices'])
            publishedAlexaDevices[newAlexaNameKey] = {}                
            publishedAlexaDevices[newAlexaNameKey]['hashKey'] = self.createHashKey(newAlexaNameKey) 
            publishedAlexaDevices[newAlexaNameKey]['name'] = newAlexaName
            if valuesDict["actionOrDevice"] == 'D':
                devId = int(valuesDict["sourceDeviceMenu"])
                dev = indigo.devices[devId]
                publishedAlexaDevices[newAlexaNameKey]['mode'] = 'D' 
                publishedAlexaDevices[newAlexaNameKey]['devId'] = devId 
                publishedAlexaDevices[newAlexaNameKey]['devName'] = dev.name
            else: # Assume 'A' = Action
                publishedAlexaDevices[newAlexaNameKey]['mode'] = 'A' 
                publishedAlexaDevices[newAlexaNameKey]['actionOnId']      = valuesDict["sourceOnActionMenu"]
                publishedAlexaDevices[newAlexaNameKey]['actionOffId']     = valuesDict["sourceOffActionMenu"]
                publishedAlexaDevices[newAlexaNameKey]['variableOnOffId'] = valuesDict["sourceOnOffActionVariableMenu"]
                publishedAlexaDevices[newAlexaNameKey]['actionDimId']     = valuesDict["sourceDimActionMenu"]
                publishedAlexaDevices[newAlexaNameKey]['variableDimId']   = valuesDict["sourceDimActionVariableMenu"]

            valuesDict['alexaDevices'] = json.dumps(publishedAlexaDevices)

            self.generalLogger.debug(u'NUMBER OF DEVICES PRE UPDATE = %s' % len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']))

            self.retrievePublishedDevices(valuesDict, ahbDevId, False, False)  # This picks up the add of the new device + don't output info message + don't Check for V2 definitions

            self.generalLogger.debug(u'NUMBER OF DEVICES POST UPDATE = %s' % len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']))

            valuesDict["newAlexaName"] = ''
            valuesDict["updatedAlexaDeviceName"] = ''
            valuesDict["actionOrDevice"] = 'D'
            valuesDict["sourceDeviceMenu"] = 0
            valuesDict["sourceOnActionMenu"] = 0
            valuesDict["sourceOffActionMenu"] = 0
            valuesDict["sourceDimActionMenu"] = 0
            valuesDict["sourceDimActionVariableMenu"] = 0

            if len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']) == DEVICE_LIMIT:
                valuesDict["showLimitMessage"] = True                

        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in updateAlexaDevice for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))

        self.generalLogger.debug(u'addNewAlexaDevice VALUESDICT = %s' % valuesDict)
        return valuesDict

    ########################################
    # This is the method that's called to create a 64 character hash key generated from the Alexa Device Name Key
    ########################################
    def createHashKey(self, alexaDeviceNameKey):
        hashKey =  hashlib.sha256(alexaDeviceNameKey.encode('ascii', 'ignore')).digest().encode("hex")  # [0:16]
        # hashKey = '12153392101'
        return hashKey

    ########################################
    # This is the method that's called by the 'Update Alexa Device' button in the config dialog.
    ########################################
    def updateAlexaDevice(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        updatedAlexaDeviceName = valuesDict["updatedAlexaDeviceName"]
        updatedAlexaDeviceNameKey = updatedAlexaDeviceName.lower()

        if updatedAlexaDeviceName == '':
            errorsDict = indigo.Dict()
            errorsDict["updatedAlexaDeviceName"] = "Alexa Name is missing and must be present."
            errorsDict["showAlertText"] = "Alexa Name is missing and must be present."
            return (valuesDict, errorsDict)

        if '|' in updatedAlexaDeviceName:
            errorsDict = indigo.Dict()
            errorsDict["updatedAlexaDeviceName"] = "New Alexa Name cannot contain the vertical bar character i.e. '|'"
            errorsDict["showAlertText"] = "New Alexa Name cannot contain the vertical bar character i.e. '|'"
            return (valuesDict, errorsDict)

        if ',' in updatedAlexaDeviceName:
            errorsDict = indigo.Dict()
            errorsDict["updatedAlexaDeviceName"] = "New Alexa Name cannot contain the comma character i.e. ','"
            errorsDict["showAlertText"] = "New Alexa Name cannot contain the comma character i.e. ','"
            return (valuesDict, errorsDict)

        if ';' in updatedAlexaDeviceName:
            errorsDict = indigo.Dict()
            errorsDict["updatedAlexaDeviceName"] = "New Alexa Name cannot contain the semicolon character i.e. ';'"
            errorsDict["showAlertText"] = "New Alexa Name cannot contain the semicolon character i.e. ';'"
            return (valuesDict, errorsDict)

        if valuesDict["actionOrDevice"] == 'D':
            devId = int(valuesDict["sourceDeviceMenu"])
            if devId == 0:
                errorsDict = indigo.Dict()
                errorsDict["updatedAlexaDeviceName"] = "Indigo Device not selected"
                errorsDict["showAlertText"] = "No Indigo device selected for Alexa Device Name '%s'" % (updatedAlexaDeviceName)
                return (valuesDict, errorsDict)
        else: # Assume 'A' = Action
            actionOnId = int(valuesDict["sourceOnActionMenu"])
            actionOffId = int(valuesDict["sourceOffActionMenu"])
            if actionOnId == 0 or actionOffId == 0:
                errorsDict = indigo.Dict()
                errorsDict["updatedAlexaDeviceName"] = "Indigo Actions not selected for On or Off or both"
                errorsDict["showAlertText"] = "Indigo Actions not selected for On or Off or both, for Alexa Device Name '%s'" % (updatedAlexaDeviceName)
                return (valuesDict, errorsDict)

        alexaDeviceNameKey, alexaDeviceName, alexaHueBridgeId = valuesDict["alexaDevicesList"].split("|")

        if updatedAlexaDeviceNameKey != alexaDeviceNameKey:
            if updatedAlexaDeviceNameKey in self.globals['alexaDevicesListGlobal']:
                alexaHueBridgeId = self.globals['alexaDevicesListGlobal'][updatedAlexaDeviceNameKey]
                if ahbDevId == alexaHueBridgeId:
                    errorsDict = indigo.Dict()
                    errorsDict["updatedAlexaDeviceName"] = "Duplicate Alexa Name"
                    errorsDict["showAlertText"] = "Alexa Device Name '%s' is already allocated on this Alexa-Hue Bridge" % updatedAlexaDeviceName
                else: 
                    alexaHueBridgeName = indigo.devices[alexaHueBridgeId].name
                    errorsDict = indigo.Dict()
                    errorsDict["updatedAlexaDeviceName"] = "Duplicate Alexa Name"
                    errorsDict["showAlertText"] = "Alexa Device Name '%s' is already allocated on Alexa-Hue Bridge '%s'" % (updatedAlexaDeviceName, alexaHueBridgeName)
                return (valuesDict, errorsDict)


        try:
            publishedAlexaDevices = self.jsonLoadsProcess(valuesDict['alexaDevices'])

            updatedAlexaDeviceData = {}
            updatedAlexaDeviceData['hashKey'] = self.createHashKey(updatedAlexaDeviceNameKey) 
            updatedAlexaDeviceData['name'] = updatedAlexaDeviceName 
            if valuesDict["actionOrDevice"] == 'D':
                devId = int(valuesDict["sourceDeviceMenu"])
                dev = indigo.devices[devId]
                updatedAlexaDeviceData['mode'] = 'D' 
                updatedAlexaDeviceData['devId'] = devId 
                updatedAlexaDeviceData['devName'] = dev.name.replace(',',' ').replace(';',' ')
            else: # Assume 'A' = Action
                updatedAlexaDeviceData['mode'] = 'A' 
                updatedAlexaDeviceData['actionOnId']      = valuesDict["sourceOnActionMenu"]
                updatedAlexaDeviceData['actionOffId']     = valuesDict["sourceOffActionMenu"]
                updatedAlexaDeviceData['variableOnOffId'] = valuesDict["sourceOnOffActionVariableMenu"]
                updatedAlexaDeviceData['actionDimId']     = valuesDict["sourceDimActionMenu"]
                updatedAlexaDeviceData['variableDimId']   = valuesDict["sourceDimActionVariableMenu"]

            if updatedAlexaDeviceNameKey != alexaDeviceNameKey:
                del publishedAlexaDevices[alexaDeviceNameKey]
            publishedAlexaDevices[updatedAlexaDeviceNameKey] = updatedAlexaDeviceData

            valuesDict["alexaDevicesList"] = ALEXA_NEW_DEVICE

            valuesDict['alexaDevices'] = json.dumps(publishedAlexaDevices)

            self.generalLogger.debug(u'NUMBER OF DEVICES PRE UPDATE = %s' % len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']))

            self.retrievePublishedDevices(valuesDict, ahbDevId, False, False)  # This picks up the update of the existing device + don't output info message + don't Check for V2 definitions

            self.generalLogger.debug(u'NUMBER OF DEVICES POST UPDATE = %s' % len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']))

            valuesDict["newAlexaName"] = ''
            valuesDict["updatedAlexaDeviceName"] = ''
            valuesDict["actionOrDevice"] = 'D'
            valuesDict["sourceDeviceMenu"] = 0
            valuesDict["sourceOnActionMenu"] = 0
            valuesDict["sourceOffActionMenu"] = 0
            valuesDict["sourceDimActionMenu"] = 0
            valuesDict["sourceDimActionVariableMenu"] = 0

            if len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']) == DEVICE_LIMIT:
                valuesDict["showLimitMessage"] = True                

        except StandardError, e:
            self.generalLogger.error(u"StandardError detected in updateAlexaDevice for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))

        self.generalLogger.debug(u'updateAlexaDevice VALUESDICT = %s' % valuesDict)
        return valuesDict

    ##########################################################################################
    # This is the method that's called by the 'Delete Devices' button in the device config UI.
    ##########################################################################################
    def deleteDevices(self, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        # valuesDict['memberDeviceList'] conatins the lsit of devices to delete from the Published Devices List
        #   Which is a combination of 'publishedAlexaDevices' and 'devicesToAddToPublishedList'

        # Delete the device's properties for this plugin and delete the entry in self.globals['alexaHueBridge'][ahbDev.id]['publishedAlexaDevices']

        publishedAlexaDevices = self.jsonLoadsProcess(valuesDict['alexaDevices'])

        for alexaDevice in valuesDict['publishedAlexaDevicesList']:
            alexaDeviceNameKey, alexaDeviceName = alexaDevice.split('|')
            if alexaDeviceNameKey in self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']:
                del self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'][alexaDeviceNameKey]
            if alexaDeviceNameKey in publishedAlexaDevices:
                del publishedAlexaDevices[alexaDeviceNameKey]

        valuesDict['alexaDevices'] = json.dumps(publishedAlexaDevices)

        if len(self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices']) < DEVICE_LIMIT:
            valuesDict["showLimitMessage"] = False

        return valuesDict

    ################################################################################
    # This is the method that's called to build the member device list.
    # Note: valuesDict is read-only so any changes you make to it will be discarded.
    ################################################################################
    def publishedAlexaDevicesList(self, filter, valuesDict, typeId, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        self.generalLogger.debug(u"memberDevices called with filter: %s  typeId: %s  Hue Hub: %s" % (filter, typeId, str(ahbDevId)))

        returnList = list()
        if 'publishedAlexaDevices' in self.globals['alexaHueBridge'][ahbDevId]:
            for alexaDeviceNameKey, alexaData in self.globals['alexaHueBridge'][ahbDevId]['publishedAlexaDevices'].iteritems():
                alexaDeviceNameKey = alexaDeviceNameKey.replace(',',' ').replace(';',' ')
                alexaDeviceName = alexaData['name'].replace(',',' ').replace(';',' ')
                listName = alexaDeviceName
                if alexaData['mode'] == 'D':  # Device
                    if alexaData['devId'] in indigo.devices:
                        dev = indigo.devices[alexaData['devId']]
                        if dev.name != alexaDeviceName:
                            listName += " = %s" % dev.name
                    else:
                        listName += " = MISSING!"
                else:  # Assume 'A' = Action
                    listName += " = ACTIONS"
                alexaDeviceListKey = '%s|%s' % (alexaDeviceNameKey, alexaDeviceName)
                returnList.append((alexaDeviceListKey, listName))
        returnList = sorted(returnList, key= lambda item: item[0])
        return returnList

    ########################################
    # This is the method that's called to validate the action config UIs.
    ########################################
    def validateActionConfigUi(self, valuesDict, typeId, devId):
        self.generalLogger.debug(u"Validating action config for type: " + typeId)
        errorsDict = indigo.Dict()
        if typeId == "startDiscovery":
            try:
                amount = int(valuesDict["discoveryExpiration"])
                if amount not in range(0, 11):
                    raise
            except:
                errorsDict["amount"] = "Amount must be a positive integer from 0 to 10"
        if len(errorsDict) > 0:
            return (False, valuesDict, errorsDict)
        return (True, valuesDict)

    ########################################
    # Method called from bridge thread to turn on/off an Alexa device
    #
    #   ahbDevId is the Indigo Device id of the Alexa-Hue Bridge that owns the Alexa device
    #   alexaDeviceName is the name of the device known to Alexa
    #   turnOn is a boolean to indicate on/off
    ########################################
    def turnOnOffDevice(self, ahbDevId, alexaDeviceNameKey, turnOn):

        ahbDev = indigo.devices[ahbDevId]
        publishedAlexaDevices =  self.jsonLoadsProcess(ahbDev.pluginProps['alexaDevices'])
        alexaDeviceNameKey = alexaDeviceNameKey.lower()
        if alexaDeviceNameKey in publishedAlexaDevices:
            alexaDeviceData = publishedAlexaDevices[alexaDeviceNameKey]
            alexaDeviceName = alexaDeviceData['name']
            if alexaDeviceData['mode'] == 'D':  # Device
                try:
                    devId = int(alexaDeviceData['devId'])
                    name = indigo.devices[devId].name
                    onOff = 'ON' if turnOn else 'OFF' 
                    self.generalLogger.info(u"Set on state of Alexa device \"%s\" [\"%s\"] to %s" % (alexaDeviceName, name, onOff))
                    if turnOn:
                        indigo.device.turnOn(devId)
                    else:
                        indigo.device.turnOff(devId)
                except:
                    self.generalLogger.error(u"Indigo Device with id %i doesn't exist for Alexa Device \"%s\" - Edit Alexa Hue Bridge \"%s\" and correct error." % (devId, alexaDeviceName, ahbDev.name))
            elif alexaDeviceData['mode'] == 'A':  # Action
                onOffVarId = int(alexaDeviceData['variableOnOffId']) 
                actionOnId = int(alexaDeviceData['actionOnId'])
                actionOffId = int(alexaDeviceData['actionOffId'])
                try:
                    onOff = 'ON' if turnOn else 'OFF'
                    trueFalse = 'true' if turnOn else 'false'
                    if onOffVarId != 0: 
                        indigo.variable.updateValue(onOffVarId, value=trueFalse)

                    if turnOn:
                        indigo.actionGroup.execute(actionOnId)
                    else:
                        indigo.actionGroup.execute(actionOffId)
                    self.generalLogger.info(u"Set on state of Alexa device \"%s\" to %s" % (alexaDeviceName, onOff))
                except:
                    self.generalLogger.error(u"Alexa Device \"%s\" doesn't have supporting Indigo Actions." % alexaDeviceName)
                   

    ########################################
    # Method called from bridge thread to set brightness of an Alexa device
    #
    #   ahbDevId is the Indigo Device id of the Alexa-Hue Bridge that owns the Alexa device
    #   alexaDeviceName is the name of the device known to Alexa
    #   brightness is the brightness in the range 0-100
    ########################################
    def setDeviceBrightness(self, ahbDevId, alexaDeviceNameKey, brightness):

        ahbDev = indigo.devices[ahbDevId]
        publishedAlexaDevices =  self.jsonLoadsProcess(ahbDev.pluginProps['alexaDevices'])
        alexaDeviceNameKey = alexaDeviceNameKey.lower()
        if alexaDeviceNameKey in publishedAlexaDevices:
            alexaDevice = publishedAlexaDevices[alexaDeviceNameKey]
            alexaDeviceName = alexaDevice['name']
            if alexaDevice['mode'] == 'D':  # Device
                try:
                    devId = int(alexaDevice['devId'])
                    dev = indigo.devices[devId]
                    name = dev.name
                except:
                    self.generalLogger.error(u"Indigo Device with id %i doesn't exist for Alexa Device \"%s\" - Edit Alexa Hue Bridge \"%s\" and correct error." % (devId, alexaDeviceName, ahbDev.name))
                    return
                if isinstance(dev, indigo.DimmerDevice):
                    self.generalLogger.info(u"Set brightness of Alexa device \"%s\" [\"%s\"] to %i" % (alexaDeviceName, name, brightness))
                    indigo.dimmer.setBrightness(dev, value=brightness)
                else:
                    self.generalLogger.error(u"Alexa Device \"%s\" [\"%s\"] doesn't support dimming." % name)
            elif alexaDevice['mode'] == 'A':  # Action 
                dimVarId = int(alexaDevice['variableDimId'])
                actionDimId = int(alexaDevice['actionDimId'])
                if dimVarId == 0 and actionDimId == 0:
                    self.generalLogger.error(u"Alexa Device \"%s\" doesn't support dimming." % alexaDeviceName)
                else:
                    self.generalLogger.info(u"Set brightness of Alexa device \"%s\" to %i" % (alexaDeviceName, brightness))
                    if dimVarId != 0:
                        brightness = str(brightness)
                        indigo.variable.updateValue(dimVarId, value=brightness)
                    if actionDimId != 0:
                        indigo.actionGroup.execute(actionDimId)

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

        if not 'broadcaster' in self.globals['alexaHueBridge'][ahbDev.id]:
            start_broadcaster_required = True
        else:
            if not self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'].is_alive():
                start_broadcaster_required = True
        if start_broadcaster_required == True:
            self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'] = Broadcaster(self, ahbDev.id)
        try:
            self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'].start()

        except StandardError, e:
            # the broadcaster won't start for some reason, so just tell them to try restarting the plugin

            self.generalLogger.error(u"Start Discovery action failed for '%s': broadcaster thread couldn't start. Try restarting the plugin.'" % self.globals['alexaHueBridge'][ahbDev.id]['hubName']) 
            errorLines = traceback.format_exc().splitlines()
            for errorLine in errorLines:
                self.generalLogger.error(u"%s" % errorLine)   
            return


        start_responder_required = False
        if not 'responder' in self.globals['alexaHueBridge'][ahbDev.id]:
            start_responder_required = True
        else:
            if not self.globals['alexaHueBridge'][ahbDev.id]['responder'].is_alive():
                start_responder_required = True
        if start_responder_required == True:
            self.globals['alexaHueBridge'][ahbDev.id]['responder'] = Responder(self, ahbDev.id)
        try:
            self.globals['alexaHueBridge'][ahbDev.id]['responder'].start()
            self.setDeviceDiscoveryState(True, ahbDev.id)
            self.generalLogger.info(u"Starting Hue Bridge '%s' discovery threads as 'Turn On Discovery' requested" % self.globals['alexaHueBridge'][ahbDev.id]['hubName'])

        except:
            self.generalLogger.info(u"Start Discovery action failed")
            self.setDeviceDiscoveryState(False, ahbDev.id)

            # the responder won't start for some reason, so just tell them to try restarting the plugin
            self.generalLogger.error(u"Start Discovery action failed for '%s': responder thread couldn't start. Try restarting the plugin." % self.globals['alexaHueBridge'][ahbDev.id]['hubName']) 
            # If the broadcaster thread started correctly, then we need to shut it down since it won't work
            # without the responder thread.
            if self.globals['alexaHueBridge'][ahbDev.id]['broadcaster']:
                self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'].stop()

    def stopDiscovery(self, action, ahbDev):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        # Stop the discovery threads
        self.setDeviceDiscoveryState(False, ahbDev.id)
        self.generalLogger.info(u"Stop Discovery . . . . . . . . . . ")

        if 'broadcaster' in self.globals['alexaHueBridge'][ahbDev.id]:
            if self.globals['alexaHueBridge'][ahbDev.id]['broadcaster']:
                self.globals['alexaHueBridge'][ahbDev.id]['broadcaster'].stop()
        if 'responder' in self.globals['alexaHueBridge'][ahbDev.id]:
            if self.globals['alexaHueBridge'][ahbDev.id]['responder']:
                self.globals['alexaHueBridge'][ahbDev.id]['responder'].stop()
        self.generalLogger.info(u"Stopping Hue Bridge '%s' discovery threads as 'Turn Off Discovery' requested" % self.globals['alexaHueBridge'][ahbDev.id]['hubName'])

    def setDeviceDiscoveryState(self, discoveryOn, ahbDevId):
        self.methodTracer.threaddebug(u"CLASS: Plugin")

        try:
            self.generalLogger.debug(u'SET DEVICE DISCOVERY STATE = %s' % discoveryOn)
            if discoveryOn:
                indigo.devices[ahbDevId].updateStateOnServer("onOffState", True, uiValue="Discovery: On")
                if self.globals['alexaHueBridge'][ahbDevId]['discoveryExpiration'] == 0:
                    indigo.devices[ahbDevId].updateStateImageOnServer(indigo.kStateImageSel.SensorOn)
                else:
                    indigo.devices[ahbDevId].updateStateImageOnServer(indigo.kStateImageSel.TimerOn)
            else:
                indigo.devices[ahbDevId].updateStateOnServer("onOffState", False, uiValue="Discovery: Off")
                if self.globals['alexaHueBridge'][ahbDevId]['discoveryExpiration'] == 0:
                    indigo.devices[ahbDevId].updateStateImageOnServer(indigo.kStateImageSel.SensorOff)
                else:
                    indigo.devices[ahbDevId].updateStateImageOnServer(indigo.kStateImageSel.TimerOff)
        except:
            pass  # Handle deleted Alexa-Hue Bridge devices by ignoring