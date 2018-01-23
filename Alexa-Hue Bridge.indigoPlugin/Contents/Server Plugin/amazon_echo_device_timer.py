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

from constants import *
import datetime
import Queue
import sys
import threading
import traceback

PLUGIN = None


class ThreadAmazonEchoDeviceTimer(threading.Thread):

    def __init__(self, plugin):
        threading.Thread.__init__(self)

        global PLUGIN
        PLUGIN = plugin

    def run(self):
        try:
            PLUGIN.serverLogger.debug(u"Amazon Echo Device Timer thread initialised.")

            while True:

                try:
                    aeDevId = PLUGIN.globals['queues']['amazonEchoDeviceTimer'].get(True, 5)

                    try:
                        PLUGIN.globals['amazonEchoDeviceTimers'][aeDevId].cancel()
                        del PLUGIN.globals['amazonEchoDeviceTimers'][aeDevId]
                    except:
                        pass

                    PLUGIN.globals['amazonEchoDeviceTimers'][aeDevId] = threading.Timer(float(ECHO_DEVICE_TIMER_LIMIT), self.handleAmazonEchoDeviceTimer, [aeDevId])
                    PLUGIN.globals['amazonEchoDeviceTimers'][aeDevId].start()

                except Queue.Empty:
                    pass
                except StandardError, e:
                    PLUGIN.serverLogger.error(u"StandardError detected in Amazon Echo Device Timer")
                    errorLines = traceback.format_exc().splitlines()
                    for errorLine in errorLines:
                        PLUGIN.serverLogger.error(u"{}".format(errorLine))

        except StandardError, e:
            PLUGIN.serverLogger.error(u"StandardError detected in Amazon Echo Device Timer thread. Line '{}' has error='{}'".format(sys.exc_traceback.tb_lineno, e))

        PLUGIN.serverLogger.debug(u"Amazon Echo Device Timer thread ended.")

    def handleAmazonEchoDeviceTimer(self, aeDevId):

        try: 
            PLUGIN.serverLogger.debug(u'handleAmazonEchoDeviceTimer invoked for {}'.format(indigo.devices[aeDevId].name))

            try:
                del PLUGIN.globals['amazonEchoDeviceTimers'][aeDevId]
            except:
                pass

            indigo.devices[aeDevId].updateStateOnServer("activityDetected", False, uiValue="No Activity")
            indigo.devices[aeDevId].updateStateImageOnServer(indigo.kStateImageSel.SensorOff)

        except StandardError, e:
            PLUGIN.serverLogger.error(u"handleAmazonEchoDeviceTimer error detected. Line '%s' has error='%s'" % (sys.exc_traceback.tb_lineno, e))   

