import threading
import SocketServer
import mimetypes
import re
import json
import time

PLUGIN = None
FILE_LIST = ["/description.xml", "/index.html", "/hue_logo_0.png", "/hue_logo_3.png"]

DESCRIPTION_XML = """<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
	<specVersion>
		<major>1</major>
		<minor>0</minor>
	</specVersion>
	<URLBase>http://%(host)s:%(port)i/</URLBase>
	<device>
		<deviceType>urn:schemas-upnp-org:device:Basic:1</deviceType>
		<friendlyName>Alexa Hue Bridge</friendlyName>
		<manufacturer>Royal Philips Electronics</manufacturer>
		<manufacturerURL>http://www.philips.com</manufacturerURL>
		<modelDescription>Philips hue Personal Wireless Lighting</modelDescription>
		<modelName>Philips hue bridge 2012</modelName>
		<modelNumber>929000226503</modelNumber>
		<modelURL>http://www.meethue.com</modelURL>
		<serialNumber>001788101fe2</serialNumber>
		<UDN>uuid:%(uuid)s</UDN>
		<presentationURL>index.html</presentationURL>
		<iconList>
			<icon>
				<mimetype>image/png</mimetype>
				<height>48</height>
				<width>48</width>
				<depth>24</depth>
				<url>hue_logo_0.png</url>
			</icon>
			<icon>
				<mimetype>image/png</mimetype>
				<height>120</height>
				<width>120</width>
				<depth>24</depth>
				<url>hue_logo_3.png</url>
			</icon>
		</iconList>
	</device>
</root>
"""

INDEX_HTML = """<head>
<title>Alexa Hue Bridge</title>
</head>
<body>
This is the Alexa Hue Bridge plugin for Indigo. It allows some devices in Indigo to present on the local network as Hue
bulbs and makes them discoverable in a way that allows any Alexa device (Echo, FireTV, etc.) to find and control them.
</body>
"""

ICON_SMALL = "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"
ICON_BIG = "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"

########################################
# Utility methods
########################################
def get_response(request_string):
    PLUGIN.threadDebugLog("hue_listener.get_response request string: " + request_string)
    # get device list
    get_match = re.search(r'(\/[^\s^\/]+)$',request_string)
    if get_match:
        request_file=get_match.group(1)
    else:
        request_file=""
    if request_file == "" or request_file == "/":
        request_file = "/index.html"
    PLUGIN.threadDebugLog("hue_listener.get_response request file: " + request_file)
    if re.search(r'/lights$',request_string):
        PLUGIN.threadDebugLog("hue_listener.get_response: discovery request, returning the full list of devices in Hue JSON format")
        return PLUGIN.getHueDeviceJSON()

    # Get individual device status - I'm actually not sure what the last two cases are for, but this is taken directly
    # from the source script so I just left it in.
    get_device_match = re.search(r'/lights/([0-9]+)$',request_string)
    if get_device_match:
        PLUGIN.threadDebugLog("hue_listener.get_response: found /lights/ in request string: %s" % request_string)
        return PLUGIN.getHueDeviceJSON(int(get_device_match.group(1)))
    elif request_file in FILE_LIST:
        PLUGIN.threadDebugLog("hue_listener.get_response: serving from a local file: %s" % request_file)
        if request_file == "/description.xml":
            desc_xml = DESCRIPTION_XML % {'host': PLUGIN.host, 'port': PLUGIN.port, 'uuid': PLUGIN.uuid}
            PLUGIN.threadDebugLog("get_response: returning file description.xml with data:\n%s" % desc_xml)
            return desc_xml
        elif request_file == "/hue_logo_0.png":
            return ICON_SMALL.decode('base64')
        elif request_file == "/hue_logo_3.png":
            return ICON_BIG.decode('base64')
        elif request_file == "/index.html":
            return INDEX_HTML
        else:
            return "HTTP/1.1 404 Not Found"
    elif re.search(r'/api/[^\/]+$',request_string):
        PLUGIN.threadDebugLog("hue_listener.get_response: found /api/ in request string: %s" % request_string)
        return "{}"
    else:
        return "{}"

########################################
def put_response(request_string,request_data):
    PLUGIN.threadDebugLog("put_response request_string: %s" % request_string)
    put_device_match = re.search(r'/lights/([0-9]+)/state$',request_string)
    if put_device_match:
        device_id = int(put_device_match.group(1))
        request = json.loads(request_data)
        #print request
        list = []
        for key in request:
            # Do something for each key here, then return success
            list.append({"success":{key:request[key]}})
            if key.lower() == "on":
                # ON == TRUE, OFF == FALSE
                PLUGIN.turnOnOffDevice(device_id, request[key])
            if key.lower() == "bri":
                PLUGIN.setDeviceBrightness(device_id, int(float(request[key])/254.0*100.0))
        return json.dumps(list)


class Httpd(threading.Thread):
    def __init__(self, host, port, plugin):
        threading.Thread.__init__(self)
        global PLUGIN
        PLUGIN = plugin
        self.host = host
        self.port = port
        self.server = None

    def run(self):
        PLUGIN.threadDebugLog("Httpd.run called")
        retryCount = 3
        while retryCount:
            try:
                PLUGIN.threadDebugLog("Httpd.run SocketServer.ThreadingTCPServer")
                self.server = SocketServer.ThreadingTCPServer((self.host, self.port), HttpdRequestHandler)
                self.server.allow_reuse_address = True
                PLUGIN.threadDebugLog("Httpd.run calling server.serve_forever()")
                self.server.serve_forever()
                retryCount = 0
            except SocketServer.socket.error as exc:
                if exc.args[0] != 48:
                    raise
                PLUGIN.errorLog("HTTP port %i already in use - waiting 15 seconds to try again (will retry %i more times)" % (self.port, retryCount))
                time.sleep(15)
                retryCount -= 1
            except Exception, e:
                PLUGIN.threadDebugLog("Exception in HTTPD run method:\n%s" % str(e))
                raise

    def stop(self):
        PLUGIN.threadDebugLog("Httpd.stop called")
        if self.server:
            self.server.shutdown()
            PLUGIN.infoLog("HTTP server stopped...")
        else:
            PLUGIN.threadDebugLog("Httpd socket was not running...")

class HttpdRequestHandler(SocketServer.BaseRequestHandler):
    def handle(self):
        PLUGIN.threadDebugLog("HttpdRequestHandler.handle called")
        data = self.request.recv(1024)
        get_match = re.search(r'GET (.*?(\/[^\s^\/]*?))\s', data)
        if get_match:
            get_request_full=get_match.group(1).replace("..","")
            self.send_headers(get_request_full)
            self.request.sendall(get_response(get_request_full))
        put_match = re.search(r'PUT (.*?(\/[^\s^\/]*?))\s', data)
        put_data_match = re.search(r'(\{.*\})', data)
        if put_match and put_data_match:
            put_request_full = put_match.group(1).replace("..","")
            put_data = put_data_match.group(1)
            self.send_headers("file.json")
            self.request.sendall(put_response(put_request_full,put_data))

    def send_headers(self,file):
        self.request.sendall("HTTP/1.1 200 OK\r\n")
        self.request.sendall("Cache-Control: no-store, no-cache, must-revalidate, post-check=0, pre-check=0\r\n")
        (type,encoding) = mimetypes.guess_type(file)
        if type is None:
            type = "application/json"
        self.request.sendall("Content-type: "+type+"\r\n\r\n")
        PLUGIN.threadDebugLog("HttpdRequestHandler.send_headers: Sent content type: "+type)

