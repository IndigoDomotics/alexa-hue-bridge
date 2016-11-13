# Alexa-Hue Bridge

V2.x of this plugin emulates multiple Philips Hue bridges to publish Indigo devices to any Amazon Alexa device (Echo, FireTV, etc.).

It requires Indigo V7.0+. 

There is a 27 device limit for each emulated Hue Bridge which is a limitation in Amazon's Alexa implementation.
By supporting more than one emulated Hue Bridge this limit is now effectively bypassed.

Consider using a 
[Device Group](<http://wiki.indigodomo.com/doku.php?id=indigo_7_documentation:virtual_devices_interface#device_groups>)
in the [Virtual Devices interface](<http://wiki.indigodomo.com/doku.php?id=indigo_7_documentation:virtual_devices_interface>)
to group devices that you generally control together into a single device and
publish that. This is a good way to create “scenes” that you can turn on/off
rather than control each device individually.

A useful new feature is that you can specify different Alexa names for the same Indigo device by setting up the same Indigo device
on different emulated Hue Bridges, with each bridge having a diferent Alexa name for the Indigo device.

This plugin is **not intended to be an officially supported** Alexa integration,
but rather as a stop-gap until Indigo Domotics can evaluate how best to
officially support Alexa devices. See our [blog post on the subject](<http://www.indigodomo.com/blog/2015/10/28/amazon-echo-and-indigo/>)
and the Terms section below for more information.

## Install


The plugin is quite straight-forward: the first thing you’ll want to do is
install it. Download the version you want from the releases section above (we
always recommend the most recent release but you can go back to previous
releases if you want to). Once downloaded, double-click the plugin file in the
Finder on your Indigo Server Mac. This will install and enable the plugin. 

## Plugin Config

The only configuration options for the plugin are to set monitoring and debugging options - not normally required.

These options in the Plugins’ config menu will help control the
amount of debugging information that’s shown in the Event Log window. This
information will help track down any issues that you may experience using the
plugin. We recommend only turning on debugging if you’re asked to by someone
trying to help with a specific issue. Some of the debugging options are
particularly chatty and will spew a lot of information so that one should really
only be enabled when specifically asked.


## Managing Devices

Create an emulated Hue Bridge by creating a new Indigo device:

New... > Type: Alexa-Hue Bridge, Model: Emulated Hue Bridge

### Configuring the Emulated Hue Bridge

* *Port*

    Default is Auto or specify a port

* *Expiration in minutes*

    This is the number of minutes the discovery process will broadcast and Alexa devices will find Indigo devices when you say "Alexa, iscover devices". 
It must be a whole number from 0 to 10 minutes. During this time, other apps on your Mac may not be able to use UPNP.
If you specify 0, once started, discovery will run until you explicitly stop it. You can start and stop discovery broadcasting by turning the Alexa-Hue Bridge device 'on' and 'off'.

* *Assigned Alexa Names*

    The Assigned Alexa names menu can be used to check if the name is already assigned as an Alexa device. 

    This is a list of all the Alexa names defined across all the Emulated Hue Bridges. These are shown in alphabetical order and are used to check for duplicate names which will be rejected if spotted (as Alexa doesn't like duplicate names!). If an alternate name has been defined for a device, then that will be shown in the list instaed of the Indigo Device name as that is the name that Alexa knows the device by. 

    Selecting a menu entry will identify the corresponding *Indigo Device* and on which *Hue Bridge* it resides, shown in the fields below.

* *Device to publish*

    Select an Indigo device to publish. If the Indigo device has already been published then it will be shown

* *Alternate name*

    If you want Alexa to recognize a different name for this device, enter it above. Otherwise, leave it blank to use the default Indigo device name. For instance, if the name is "034 - HA-02 Appliance Module”,
it’s not going to be easy to say that to
Alexa or for Alexa to interpret. You can use an alternate name that’s more
easily said and recognized by Alexa in the *Alternate name* field. If you’ve
already published a device, you can still select it from the top menu and change
the alternate name.

* *Add/Update*

    When you’re ready to add or update the device name, click
the *Add/Update Device* button. The device will be added into the Published devices list. If you try and add more than 27 devices you will get an error message: "You have reached 27 device limit imposed by Amazon Alexa for this Bridge. Create a new Bridge Device or consider Device Groups to group similar devices into a single device."

    Note: You must click the *Save* button to make the changes permanent; see below.

* *Published devices*

    This is the list of devices currently published to this bridge (including any just added or updated. There is a limit of 27 devices currently imposed by the Amazon implementation for each bridge. If you specified an alternate name, it will show in parenthesis after the Indigo name. If the name is too long to show all the detail, hovering the mouse over the name will show the full anme and alternate name (if specified) after a few seconds.

* *Delete Devices*

    Select one or more devices from the Published devices list and click the *Delete Devices* button. Note: You must click the *Save* button to make the changes permanent; see below. 

* *Save*

    Once you’re finished adding/editing/deleting published devices, click the *Save* button to make the changes permanent. Click the *Cancel* button to discard all changes.  

## Discovery

At this point, the plugin knows about the devices, but Alexa
doesn’t. You need to tell Alexa to discover devices. By default, you can 
just tell Alexa to discover your devices either by saying that or by 
using the Alexa app.

In prior releases of the plugin, you needed to specifically start the discovery process.
This is now done automatically and it can run forever. Thanks to a comment from another 
Indigo user, we've added a switch which allows us to open the UPNP response 
port in a shared mode - so any other app that opens the same port in the 
same way will also work concurrently.

However, there may be other apps/plugins that don't open the port shared, 
and those may still require this plugin to not be in discover mode.

The discovery minutes is defaulted to zero which means discovery is always on. The status of discovery is shown in the state column of the Indigo device UI. A solid green dot means discovery is always on, a green timer means that it is on for a limited time (1 to 10 minutes), a grey timer (or gray for the USA  :wink: ) means discovery is off.

Discovery can be turned on and off by using the Turn On and Turn Off controls in the UI.

Starting discovery (and stopping it) are also available as actions: The emulated Hue Bridges, so if you
can start (and stop if necessary) discovery from Triggers, Schedules, etc.


A quick description of how discovery works: the Hue Bridge uses a technology 
called UPNP to broadcast its presence and information about its devices on 
your local network. This broadcast is what Alexa will look for when performing 
its device discovery. However, UPNP may be use by other apps and plugins on 
your Mac (the Sonos plugin uses it also). But different processes on the same 
Mac can’t run their own UPNP responders unless they open them in a special 
way. This may be the reason you'd need to stop/start discovery yourself.

You can find out if other plugins or applications have the UPNP port open by 
doing the following command in a terminal window:

    sudo lsof -i :1900
    
The output will show you any processes (IndigoPluginHost or or otherwise) that 
have the port open. In order for discovery to work, you may need to temporarily 
quit those apps. You can start them back up after Alexa has discovered your 
devices.

Starting discovery (and stopping it) are also available as actions, so if you
can start (and stop if necessary) discovery from Triggers, Schedules, etc.

**Note**: The plugin does a mapping that is somewhat interesting. If a device
has communication disabled in Indigo (but is still published), then when using
the Alexa app, under Settings\>Connected Home in the Devices section at the
bottom, the device will (mostly) show up in gray indicating that it’s
unavailable. However, if you reenable it will still work and that list (the next
time it’s refreshed) will then turn it normal to indicate it’s online. Also,
when you tell Alexa to discover devices, it will only announce the total count
of devices that are enabled, but if you look in the app at the list above it
will actually have all the devices you published.

## Controlling Devices

That’s basically it. Once Alexa discovers your devices, you can control them
with the standard Alexa commands for home automation:

-   Alexa, turn on Media Fan

-   Alexa, dim Office Wall Lamp to 50% (there is no corresponding brighten)

-   Alexa, turn Media Fan off

Alexa’s vocabulary for home automation is currently limited to turn on, turn
off, and dim. We’re filtering the device list in the Manage Devices dialog to
only show devices that have an on/off state, so things like thermostats and
(most) sensors can’t be added. However, you can use the [Virtual On/Off Device](<http://wiki.indigodomo.com/doku.php?id=indigo_6_documentation:virtual_devices_interface#virtual_on_off_devices>)
type in the [Virtual Devices interface](<http://wiki.indigodomo.com/doku.php?id=indigo_6_documentation:virtual_devices_interface>)
to create your own custom on/off devices that can do pretty much anything you
want. For example, you could create a Virtual On/Off Device with an ON action
group that sets a thermostat in one way, and the OFF action group would set it
another. You could then “turn on” and “turn off” the group to set the
thermostat.


Troubleshooting
------------
We've created a [topic on our forums](<http://forums.indigodomo.com/viewtopic.php?f=65&t=15374>) for getting help with the plugin. Start by posting your
question there to see if anyone can help before filing an issue here on GitHub. 
We're not closely monitoring the issues here but are monitoring the forums.

We've noticed that sometimes when we tapped the Discover devices button in the Alexa iOS app and it shows the progress bar, but when it's done Alexa herself says nothing on the Echo (she usually says either she didn't find or found devices). Using the voice command "Alexa, discover devices" when that happened results in an immediate reply that she couldn't and to try later. We've found that a force quit the Alexa app on the iOS device followed by started it back up and hitting the Discover devices button may get it working again.

So, there appears to be a bug with the Alexa iOS app (there are actually quite a few) that can cause discovery to fail, and once it gets into that state a force-quit restart cycle seems to clear it.

Contributing
------------

If you want to contribute, just clone the repository in your account, make your
changes, and issue a pull request. Make sure that you describe the change you're
making thoroughly - this will help the repository managers accept your request
more quickly.

We've documented the code fairly well, so please do the same for any changes
that you make. This will ensure that future contributors can effectively
contribute in the future.

Terms
-----

Perceptive Automation (aka Indigo Domotics) is hosting this repository and will
do minimal management. Unless a pull request has no description or upon cursory
observation has some obvious issue, pull requests will be accepted without any
testing by us. We may choose to delegate commit privledges to other users at
some point in the future.

We (Perceptive Automation) don't guarantee anything about this plugin - that
this plugin works or does what the description above states, so use at your own
risk. We will attempt to answer questions about the plugin but given the nature
of this plugin, which uses reverse-engineered information provided by other
users out on the net, we can’t guarantee that it will always work since either
Amazon or Philips can change the protocol at any time.

This plugin is a derivative work from a couple of different sources: the
[hueAndMe project](<https://github.com/johnray/hueAndM>), which is itself based
loosely on work from the [hue-upnp project](<https://github.com/sagen/hue-upnp>). We’re grateful that these
developers published these projects so that we could build upon them.

License
-------

This project is licensed using [Unlicense](<http://unlicense.org/>). 


Plugin ID
---------

Here's the plugin ID in case you need to programmatically restart the plugin or
start/stop discovery:

**Plugin ID**: com.indigodomo.opensource.alexa-hue-bridge

Things that are known to use the UPNP port (1900)
---------

The primary issue that users experience is with port conflicts on the UPNP port - several Mac apps open that port as 
part of a UPNP process. The plugin only needs to use the port while the Alexa is discovering devices, but during that 
time other apps may have a problem. This is a list of things users have found on their Macs that use that port. It 
is by no means an exhaustive list.

- The Sonos Indigo Plugin
- The Squeezebox Indigo Plugin
- MythTV
- Sighthound Video

Feel free to add more, or report any other conflicts you find on [the forum thread](<http://forums.indigodomo.com/viewtopic.php?f=65&t=15374>) and we'll add it here.
