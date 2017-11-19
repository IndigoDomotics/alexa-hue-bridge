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
import Queue
import sys
import threading
import traceback

PLUGIN = None

class ThreadDiscoveryLogging(threading.Thread):

    def __init__(self, plugin):
        threading.Thread.__init__(self)

        global PLUGIN
        PLUGIN = plugin

    def run(self):
        try:
            PLUGIN.serverLogger.debug(u"Discovery Logging thread initialised.")

            while True:

                try:
                    discoveryId, discoveryName, discoveryList = PLUGIN.globals['queues']['discoveryLogging'].get(True, 5)
                    if len(discoveryList) > 0:
                        discoveryList.sort()
                        PLUGIN.serverLogger.info(u"Alexa-Hue Bridge '%s' responding to Alexa discovery [request id: %s] ..." % (discoveryName, discoveryId))
                        deviceCount = 0
                        for deviceName in discoveryList:
                            deviceCount += 1
                            PLUGIN.serverLogger.info(u"+ Publishing device '%s' to Alexa" % deviceName)
                        if deviceCount == 0:
                            deviceString = 'No device'  # This probably won't occur ?
                        elif deviceCount == 1:
                            deviceString = 'One device'
                        else:
                            deviceString = '%s devices' % str(deviceCount)
                        PLUGIN.serverLogger.info(u"... %s discovered by Alexa on Alexa-Hue Bridge '%s'." % (deviceString, discoveryName))

                    del PLUGIN.globals['discoveryLists'][discoveryId]

                except Queue.Empty:
                    pass
                except StandardError, e:
                    PLUGIN.serverLogger.error(u"StandardError detected in Discovery Logging")
                    errorLines = traceback.format_exc().splitlines()
                    for errorLine in errorLines:
                        PLUGIN.serverLogger.error(u"%s" % errorLine)

        except StandardError, e:
            PLUGIN.serverLogger.error(u"StandardError detected in Discovery Logging thread. Line '%s' has error='%s'" % (sys.exc_traceback.tb_lineno, e))

        PLUGIN.serverLogger.debug(u"Discovery Logging thread ended.")