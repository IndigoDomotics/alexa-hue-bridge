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

import errno
import socket
import sys
import time
import threading
import uuid

BCAST_IP = "239.255.255.250"
UPNP_PORT = 1900
BROADCAST_INTERVAL = 10  # Seconds between upnp broadcast
M_SEARCH_REQ_MATCH = "M-SEARCH"
UUID = uuid.uuid1()
TIMEOUT = 60 * 2  # Default seconds that the broadcaster and responder will run before automatically shutting down

# Need to substitute: 
# {"broadcast_ip": BCAST_IP, "upnp_port": UPNP_PORT, "server_ip": Server IP, "server_port": Server Port, "uuid": UUID}
broadcast_packet = """NOTIFY * HTTP/1.1
HOST: %(broadcast_ip)s:%(upnp_port)s
CACHE-CONTROL: max-age=100
LOCATION: http://%(server_ip)s:%(server_port)s/description.xml
SERVER: FreeRTOS/7.4.2, UPnP/1.0, IpBridge/1.7.0
NTS: ssdp:alive
NT: uuid:%(uuid)s
USN: uuid:%(uuid)s

"""

# Need to substitute: {"server_ip": Server IP, "server_port": Server Port, "uuid": UUID}
# response_packet = """HTTP/1.1 200 OK
# CACHE-CONTROL: max-age=100
# EXT:
# LOCATION: http://%(server_ip)s:%(server_port)s/description.xml
# SERVER: AlexaHueBridge/0.1.0, UPnP/1.0, IpBridge/1.7.0
# ST: urn:schemas-upnp-org:device:basic:1
# USN: uuid:%(uuid)s
#
# """
response_packet = """HTTP/1.1 200 OK
CACHE-CONTROL: max-age=100
EXT:
LOCATION: http://%(server_ip)s:%(server_port)s/description.xml
SERVER: FreeRTOS/7.4.2, UPnP/1.0, IpBridge/1.7.0
ST: urn:schemas-upnp-org:device:basic:1
USN: uuid:%(uuid)s

"""


class Broadcaster(threading.Thread):
    def __init__(self, plugin, ahbDevId):
        threading.Thread.__init__(self)
        global PLUGIN
        PLUGIN = plugin

        try:
            self.ahbDevId = ahbDevId

            PLUGIN.broadcasterLogger.debug("Broadcaster.__init__ for '{}' is running".format(PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['hubName']))

            self.interrupted = False

            broadcast_data = {"broadcast_ip": BCAST_IP, 
                              "upnp_port": UPNP_PORT, 
                              "server_ip": PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['host'], 
                              "server_port": PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['port'], 
                              "uuid": PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['uuid']}
            self.broadcast_packet = broadcast_packet % broadcast_data
        except StandardError, e:
            PLUGIN.broadcasterLogger.error(u"StandardError detected in Broadcaster.Init for '{}'. Line '{}' has error='{}'".format(indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))

    def run(self):
        try:
            PLUGIN.broadcasterLogger.debug("Broadcaster.run called")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 20)
            start_time = time.time()
            end_time = start_time + (PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['discoveryExpiration'] * 60)
            PLUGIN.broadcasterLogger.debug("Broadcaster.run: sending first broadcast:\n{}".format(self.broadcast_packet))
            while True:
                sock.sendto(self.broadcast_packet, (BCAST_IP, UPNP_PORT))
                for x in range(BROADCAST_INTERVAL):
                    time.sleep(1)
                    # Following code will only time out the Broadcaster Thread if PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['discoveryExpiration'] > 0 (valid values 0 thru 10 inclusive)
                    # A value of zero means 'always on'
                    if PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['discoveryExpiration'] and time.time() > end_time:
                        PLUGIN.broadcasterLogger.debug("Broadcaster thread timed out")
                        self.stop()
                    if self.interrupted:
                        PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
                        sock.close()
                        return

        except StandardError, e:
            PLUGIN.broadcasterLogger.error(u"StandardError detected in Broadcaster.Run for '{}'. Line '{}' has error='{}'".format(indigo.devices[self.ahbDevId].name, sys.exc_traceback.tb_lineno, e))

    def stop(self):
        PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
        PLUGIN.broadcasterLogger.debug("Broadcaster thread stopped")
        self.interrupted = True


class Responder(threading.Thread):
    def __init__(self, plugin,  ahbDevId):
        threading.Thread.__init__(self)

        global PLUGIN
        PLUGIN = plugin

        try:
            self.ahbDevId = ahbDevId

            PLUGIN.responderLogger.debug("Responder.__init__ for '{}' is running".format(PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['hubName']))

            self.interrupted = False

            response_data = {"server_ip": PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['host'],
                             "server_port": PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['port'],
                             "uuid": PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['uuid']}
            self.response_packet = response_packet % response_data
        except StandardError, e:
            PLUGIN.responderLogger.error(u"StandardError detected in Responder.Init for '{}'. Line '{}' has error='{}'".format(indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))

    def run(self):
        try:
            PLUGIN.responderLogger.debug("Responder.run called")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            try:
                sock.bind(('', UPNP_PORT))
                sock.setsockopt(socket.IPPROTO_IP,
                                socket.IP_ADD_MEMBERSHIP,
                                socket.inet_aton(BCAST_IP) + socket.inet_aton(PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['host']))
                sock.settimeout(1)
                start_time = time.time()
                end_time = start_time + (PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['discoveryExpiration'] * 60)
                while True:
                    try:
                        data, addr = sock.recvfrom(1024)
                        # Following code will only time out the Broadcaster Thread if PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['discoveryExpiration'] > 0 (valid values 0 thru 10 inclusive)
                        # A value of zero means 'always on'
                        if PLUGIN.globals['alexaHueBridge'][self.ahbDevId]['discoveryExpiration'] and time.time() > end_time:
                            PLUGIN.responderLogger.debug("Responder.run thread timed out")
                            self.stop()
                            raise socket.error
                    except socket.error:
                        if self.interrupted:
                            PLUGIN.responderLogger.debug("Responder.run: self.interrupted: True")
                            PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
                            sock.close()
                            return
                    else:
                        if M_SEARCH_REQ_MATCH in data:
                            PLUGIN.responderLogger.debug("Responder.run: received: {}".format(str(data)))
                            self.respond(addr)
            except socket.error as e:
                # This is the exception thrown when someone else has bound to the UPNP port, so write some errors and
                # stop the thread (which really isn't needed, but it logs a nice stop debug message).
                if e.errno == errno.EADDRINUSE:
                    PLUGIN.responderLogger.error(u"'{}' Responder startup failed because another app or plugin is using the UPNP port.".format(indigo.devices[self.ahbDevId].name))
                    PLUGIN.responderLogger.error(u"Open a terminal window and type 'sudo lsof -i :{}}' to see a list of processes that have bound to that port and quit those applications.".format(UPNP_PORT))
                    self.stop()
                elif e.errno == errno.EADDRNOTAVAIL:
                    PLUGIN.responderLogger.error(u"'{}' Responder startup failed because host address is not available.".format(indigo.devices[self.ahbDevId].name))
                    PLUGIN.responderLogger.error(u"Double check that the host is specified correctly in the Plugin Config. Correct if invalid and then reload the plugin.")
                    self.stop()
                else:
                    PLUGIN.responderLogger.error("'{}' Responder.run: socket error: {}".format(indigo.devices[self.ahbDevId].name, e))

            PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
        except StandardError, e:
            PLUGIN.responderLogger.error(u"StandardError detected in Responder.Run for '{}'. Line '{}' has error='{}'".format(indigo.devices[self.ahbDevId].name, sys.exc_traceback.tb_lineno, e))

    def stop(self):
        PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
        PLUGIN.responderLogger.debug("Responder thread stopped")
        self.interrupted = True

    def respond(self, addr):
        PLUGIN.responderLogger.debug("Responder.respond called from address {}\n{}".format(str(addr), self.response_packet))
        PLUGIN.responderLogger.debug("Responder.respond: creating output_socket")
        output_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        PLUGIN.responderLogger.debug("Responder.respond: calling output_socket.sendto")
        output_socket.sendto(self.response_packet, addr)
        PLUGIN.responderLogger.debug("Responder.respond: closing output_socket")
        output_socket.close()
        PLUGIN.responderLogger.debug("Responder.respond: UDP Response sent to {}".format(str(addr)))
