import socket
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
    def __init__(self, host, port, debug_log, uuid, timeout=0):
        threading.Thread.__init__(self)
        self.interrupted = False
        self._host = host
        self._port = port
        self.debug_log = debug_log
        self.debug_log("Broadcaster.__init__ is running")
        self._timeout = timeout
        broadcast_data = {"broadcast_ip": BCAST_IP, 
                          "upnp_port": UPNP_PORT, 
                          "server_ip": host, 
                          "server_port": port, 
                          "uuid": uuid}
        self.broadcast_packet = broadcast_packet % broadcast_data

    def run(self):
        self.debug_log("Broadcaster.run called")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 20)
        start_time = time.time()
        end_time = start_time + (self._timeout * 60)
        self.debug_log("Broadcaster.run: sending first broadcast:\n%s" % self.broadcast_packet)
        while True:
            sock.sendto(self.broadcast_packet, (BCAST_IP, UPNP_PORT))
            for x in range(BROADCAST_INTERVAL):
                time.sleep(1)
                if self._timeout and time.time() > end_time:
                    self.debug_log("Broadcaster thread timed out")
                    self.stop()
                if self.interrupted:
                    sock.close()
                    return
            #self.debug_log("Broadcaster.run: sending broadcast")

    def stop(self):
        self.debug_log("Broadcaster thread stopped")
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
    def __init__(self, host, port, debug_log, error_log, uuid, timeout=0):
        threading.Thread.__init__(self)
        self.interrupted = False
        self._host = host
        self._port = port
        self.error_log = error_log
        self.debug_log = debug_log
        self.debug_log("Responder.__init__ is running")
        self._timeout = timeout
        response_data = {"server_ip": host, 
                         "server_port": port, 
                         "uuid": uuid}
        self.response_packet = response_packet % response_data

    def run(self):
        self.debug_log("Responder.run called")
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
                        self.debug_log("Responder.run thread timed out")
                        self.stop()
                        raise socket.error
                except socket.error:
                    if self.interrupted:
                        sock.close()
                        return
                else:
                    if M_SEARCH_REQ_MATCH in data:
                        self.debug_log("Responder.run: received: %s" % str(data))
                        self.respond(addr)
        except socket.error, (value, message):
            # This is the exception thrown when someone else has bound to the UPNP port, so write some errors and
            # stop the thread (which really isn't needed, but it logs a nice stop debug message).
            if value == 48:
                self.error_log(u"Responder startup failed because another app or plugin is using the UPNP port.")
                self.error_log(u"Open a terminal window and type 'sudo lsof -i :%i' to see a list of processes that have bound to that port and quit those applications." % UPNP_PORT)
                self.stop()

    def stop(self):
        self.debug_log("Responder thread stopped")
        self.interrupted = True

    def respond(self, addr):
        self.debug_log("Responder.respond called from address %s\n%s" % (str(addr), self.response_packet))
        self.debug_log("Responder.respond: creating output_socket")
        output_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.debug_log("Responder.respond: calling output_socket.sendto")
        output_socket.sendto(self.response_packet, addr)
        self.debug_log("Responder.respond: closing output_socket")
        output_socket.close()
        self.debug_log("Responder.respond: UDP Response sent to %s" % str(addr))


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

