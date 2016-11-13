try:
    import indigo
except:
    pass
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
    def __init__(self, plugin,  globals, ahbDevId):
        threading.Thread.__init__(self)
        global PLUGIN
        PLUGIN = plugin

        try:
            self.globals = globals
            self.ahbDevId = ahbDevId
            self._host = self.globals['hueBridge'][self.ahbDevId]['host']
            self._port = self.globals['hueBridge'][self.ahbDevId]['port']
            self.uuid = self.globals['hueBridge'][self.ahbDevId]['uuid']
            self._timeout = self.globals['hueBridge'][self.ahbDevId]['expireMinutes']

            PLUGIN.broadcasterLogger.debug("Broadcaster.__init__ for '%s' is running" % self.globals['hueBridge'][self.ahbDevId]['hubName'])

            self.interrupted = False


            broadcast_data = {"broadcast_ip": BCAST_IP, 
                              "upnp_port": UPNP_PORT, 
                              "server_ip": self._host, 
                              "server_port": self._port, 
                              "uuid": self.uuid}
            self.broadcast_packet = broadcast_packet % broadcast_data
        except StandardError, e:
            PLUGIN.generalLogger.error(u"StandardError detected in Broadcaster.Init for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))

    def run(self):
        try:
            PLUGIN.broadcasterLogger.debug("Broadcaster.run called")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 20)
            start_time = time.time()
            end_time = start_time + (self._timeout * 60)
            PLUGIN.broadcasterLogger.debug("Broadcaster.run: sending first broadcast:\n%s" % self.broadcast_packet)
            while True:
                sock.sendto(self.broadcast_packet, (BCAST_IP, UPNP_PORT))
                for x in range(BROADCAST_INTERVAL):
                    time.sleep(1)
                    if self._timeout and time.time() > end_time:
                        PLUGIN.broadcasterLogger.debug("Broadcaster thread timed out")
                        self.stop()
                    if self.interrupted:
                        PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
                        sock.close()
                        return
            PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
        except StandardError, e:
            PLUGIN.generalLogger.error(u"StandardError detected in Broadcaster.Run for '%s'. Line '%s' has error='%s'" % (indigo.devices[self.ahbDevId].name, sys.exc_traceback.tb_lineno, e))

    def stop(self):
        PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
        PLUGIN.broadcasterLogger.debug("Broadcaster thread stopped")
        self.interrupted = True

    @property
    def host(self):
        return self._host

    @host.setter
    def host(self, host):
        self._host = host

    @property
    def port(self):
        return self._port

    @port.setter
    def port(self, port):
        self._port = port

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, timeout):
        self._timeout = timeout

class Responder(threading.Thread):
    def __init__(self, plugin,  globals, ahbDevId):
        threading.Thread.__init__(self)
        global PLUGIN
        PLUGIN = plugin

        try:
            self.globals = globals
            self.ahbDevId = ahbDevId
            self._host = self.globals['hueBridge'][self.ahbDevId]['host']
            self._port = self.globals['hueBridge'][self.ahbDevId]['port']
            self.uuid = self.globals['hueBridge'][self.ahbDevId]['uuid']
            self._timeout = self.globals['hueBridge'][self.ahbDevId]['expireMinutes']

            PLUGIN.broadcasterLogger.debug("Broadcaster.__init__ for '%s' is running" % self.globals['hueBridge'][self.ahbDevId]['hubName'])

            self.interrupted = False

            response_data = {"server_ip": self._host, 
                             "server_port": self._port, 
                             "uuid": self.uuid}
            self.response_packet = response_packet % response_data
        except StandardError, e:
            PLUGIN.generalLogger.error(u"StandardError detected in Responder.Init for '%s'. Line '%s' has error='%s'" % (indigo.devices[ahbDevId].name, sys.exc_traceback.tb_lineno, e))

    def run(self):
        try:
            PLUGIN.responderLogger.debug("Responder.run called")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            try:
                sock.bind(('', UPNP_PORT))
                sock.setsockopt(socket.IPPROTO_IP,
                                socket.IP_ADD_MEMBERSHIP,
                                socket.inet_aton(BCAST_IP) + socket.inet_aton(self._host))
                sock.settimeout(1)
                start_time = time.time()
                end_time = start_time + (self._timeout * 60)
                while True:
                    try:
                        data, addr = sock.recvfrom(1024)
                        if self._timeout and time.time() > end_time:
                            PLUGIN.responderLogger.debug("Responder.run thread timed out")
                            self.stop()
                            raise socket.error
                    except socket.error:
                        if self.interrupted:
                            PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
                            sock.close()
                            return
                    else:
                        if M_SEARCH_REQ_MATCH in data:
                            PLUGIN.responderLogger.debug("Responder.run: received: %s" % str(data))
                            self.respond(addr)
            except socket.error, (value, message):
                # This is the exception thrown when someone else has bound to the UPNP port, so write some errors and
                # stop the thread (which really isn't needed, but it logs a nice stop debug message).
                if value == 48:
                    PLUGIN.responderLogger.error(u"Responder startup failed because another app or plugin is using the UPNP port.")
                    PLUGIN.responderLogger.error(u"Open a terminal window and type 'sudo lsof -i :%i' to see a list of processes that have bound to that port and quit those applications." % UPNP_PORT)
                    self.stop()
            PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
        except StandardError, e:
            PLUGIN.generalLogger.error(u"StandardError detected in Responder.Run for '%s'. Line '%s' has error='%s'" % (indigo.devices[self.ahbDevId].name, sys.exc_traceback.tb_lineno, e))

    def stop(self):
        PLUGIN.setDeviceDiscoveryState(False, self.ahbDevId)
        PLUGIN.responderLogger.debug("Responder thread stopped")
        self.interrupted = True

    def respond(self, addr):
        PLUGIN.responderLogger.debug("Responder.respond called from address %s\n%s" % (str(addr), self.response_packet))
        PLUGIN.responderLogger.debug("Responder.respond: creating output_socket")
        output_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        PLUGIN.responderLogger.debug("Responder.respond: calling output_socket.sendto")
        output_socket.sendto(self.response_packet, addr)
        PLUGIN.responderLogger.debug("Responder.respond: closing output_socket")
        output_socket.close()
        PLUGIN.responderLogger.debug("Responder.respond: UDP Response sent to %s" % str(addr))


    @property
    def host(self):
        return self._host

    @host.setter
    def host(self, host):
        self._host = host

    @property
    def port(self):
        return self._port

    @port.setter
    def port(self, port):
        self._port = port

    @property
    def timeout(self):
        return self._timeout

    @timeout.setter
    def timeout(self, timeout):
        self._timeout = timeout

