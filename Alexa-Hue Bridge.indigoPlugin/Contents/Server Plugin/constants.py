#! /usr/bin/env python
# -*- coding: utf-8 -*-
#######################
#
# Alexa-Hue Bridge 

# plugin Constants

ALEXA_NEW_DEVICE = '_newalexaname|_NewAlexaName|0'
SELECT_FROM_ALEXA_DEVICE_LIST = '_selectalexadevice|_SelectAlexaDevice|0'
KEY_PREFIX = "ahb-"
PUBLISHED_KEY = "published"
ALT_NAME_KEY = "alternate-name"
ACTION_TYPE = "action-type"
# DEVICE_LIMIT = 5 #  TESTING (30-JUL-2017)
DEVICE_LIMIT = 20 # Imposed by the built-in Hue support in Alexa
EMULATED_HUE_BRIDGE_TYPEID = 'emulatedHueBridge'  # See definition in Devices.xml
EMULATED_HUE_BRIDGE_MODEL = 'Emulated Hue Bridge [Alexa Devices]'  # See definition in Devices.xml 
ECHO_DEVICE_TYPEID = 'echoDevice'  # See definition in Devices.xml
ECHO_DEVICE_TIMER_LIMIT = 15.0  # In seconds - the amount of time an Echo device will show active after a command is received

NETWORK_AVAILABLE_CHECK_REMOTE_SERVER = 'www.google.com'
NETWORK_AVAILABLE_CHECK_LIMIT_ONE = 6  # Retry Count
NETWORK_AVAILABLE_CHECK_LIMIT_TWO = 14 # Retry Count
NETWORK_AVAILABLE_CHECK_LIMIT_THREE = 14 # Retry Count
NETWORK_AVAILABLE_CHECK_RETRY_SECONDS_ONE = 10  # Seconds
NETWORK_AVAILABLE_CHECK_RETRY_SECONDS_TWO = 30  # Seconds
NETWORK_AVAILABLE_CHECK_RETRY_SECONDS_THREE = 300  # 5 Minutes
NETWORK_AVAILABLE_CHECK_RETRY_SECONDS_EVERY = 3600  # 1 Hour