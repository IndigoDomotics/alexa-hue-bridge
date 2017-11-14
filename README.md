# Overview

The Alexa-Hue Bridge is a plugin for version 7+ of the [Indigo Home Automation system][1]. Version 3.x of this plugin emulates multiple Philips Hue bridges to publish Indigo actions and devices (on/off and dimmer types only) to most Amazon Alexa devices (Echo, Dot, FireTV, etc.).

Use the latest 1.x release for Indigo 6.

There is a 20 device limit for each emulated Hue Bridge which is imposed by the plugin to handle a limitation in Amazon's Alexa implementation. By supporting more than one emulated Hue Bridge this limit is now effectively bypassed.

Version 3 adds the ability to directly control Indigo Actions in addition to Indigo Devices.

It is **strongly recommended** to read the [Wiki Documentation][4] to familiarise yourself with the new way of working which is substantially different to earlier plugin versions (V1 and V2).

**The latest production release is available here: [https://github.com/IndigoDomotics/alexa-hue-bridge/releases][6]**

[1]: https://www.indigodomo.com
[4]: http://wiki.indigodomo.com/doku.php?id=indigo_7_documentation:virtual_devices_interface#virtual_on_off_devices
[6]: https://github.com/IndigoDomotics/alexa-hue-bridge/releases
