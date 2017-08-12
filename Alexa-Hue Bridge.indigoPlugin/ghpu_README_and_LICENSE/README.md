# indigo-ghpu

This is an Indigo plugin updater for plugins released on GitHub.  To help illustrate its
usage, this project also happens to be a plugin, although not a very useful one.

When creating releases for your plugins, you should use the `v{major}.{minor}.{revision}`
format.  This will help ensure compatibility with Indigo's [plugin versioning scheme](http://wiki.indigodomo.com/doku.php?id=indigo_6_documentation:plugin_guide#the_infoplist_file).

## Installation

To install this in your plugin, simply copy the latest version of `ghpu.py` to your plugin
folder.  Check back occasionally to see if updates have been made.

## Configuration

In order for the GitHub Plugin Updater to work properly, you will need to configure the
`ghpu.cfg` file.  This file must be placed in the same folder as your `plugin.py` file.

See the [sample configuration file](https://github.com/jheddings/indigo-ghpu/blob/master/Contents/Server%20Plugin/ghpu.cfg)
for more details.

## Usage

In your plugin, initialize the updater during your plugin's `__init__` method:

    from ghpu import GitHubPluginUpdater
    ...
    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        self.updater = GitHubPluginUpdater(self)

Providing the `self` reference to the udpater allows it to use the current plugin's
logging methods and access to plugin properties.  The plugin instannce is also used to
verify several phases of the update process.

Either as a menu option, during `runConcurrentThread`, or by whatever method you choose,
use the following method to check for new versions:

    self.updater.checkForUpdate()

This will instruct the updater to look for updates and notify the error log if any exist.
You may optionally provide the version you want to compare against, like this:

    self.updater.checkForUpdate(str(self.pluginVersion))

This form is required if you do not provide the plugin reference when constructing the
updater.

Similarly, to automatically update the plugin to the latest release (if needed), use the
following command:

    self.updater.update()

This will most often be called from a menu item.  The `update()` method also supports
passing the current version to compare against.

## Ideas for Later

It might be interesting to see if this plugin could be extend to manange other plugins for
Indigo.  Perhaps by adding plugins as "devices", this plugin could check for (and apply)
latest updates.  It may even be able to do the initial installation when adding a device.
