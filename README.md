# Overview

**Note**: this plugin is superceeded by the built-in Alexa integration available as part of Indigo 2021.1 or later, so it is end-of-life.

The Alexa-Hue Bridge is a plugin for version 7+ of the [Indigo Home Automation system][1]. Version 3.0.23+ of this plugin emulates multiple Philips Hue bridges to publish Indigo actions and devices (on/off and dimmer types only) to these Amazon Alexa devices: Echo [Gen 1], Echo Dot [Gen 1 & 2].

Use the latest 1.x release for Indigo 6.

There is a 20 device limit for each emulated Hue Bridge which is imposed by the plugin to handle a limitation in Amazon's Alexa implementation. By supporting more than one emulated Hue Bridge this limit is now effectively bypassed.

Version 3 adds the ability to directly control Indigo Actions in addition to Indigo Devices.

It is **strongly recommended** to read the [Wiki Documentation][4] to familiarise yourself with the new way of working which is substantially different to earlier plugin versions (V1 and V2).

[1]: https://www.indigodomo.com
[4]: https://github.com/IndigoDomotics/alexa-hue-bridge/wiki
[6]: https://github.com/IndigoDomotics/alexa-hue-bridge/releases
