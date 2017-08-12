#!/usr/bin/env python2.5

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# for the latest version and documentation:
# https://github.com/jheddings/indigo-ghpu

# incorporates minor changes by Autolog for logging messages [2017-JAN-01]

import os
import tempfile
import subprocess
import shutil
import json
import httplib
import plistlib

import ConfigParser

from urllib2 import urlopen
from StringIO import StringIO
from zipfile import ZipFile
from collections import namedtuple

PluginInfo = namedtuple('PluginInfo', ['id', 'name', 'version'])

################################################################################
class GitHubPluginUpdater(object):

    #---------------------------------------------------------------------------
    def __init__(self, plugin=None, configFile='ghpu.cfg'):
        self.plugin = plugin

        config = ConfigParser.RawConfigParser()
        config.read(configFile)

        self.repo = config.get('repository', 'name')
        self.owner = config.get('repository', 'owner')

        if (config.has_option('repository', 'path')):
            self.path = config.get('repository', 'path')
        else:
            self.path = ''

        # TODO error checking on configuration

    #---------------------------------------------------------------------------
    # install the latest version of the plugin represented by this updater
    def install(self):
        self._log('Installing plugin from %s/%s...' % (self.owner, self.repo))
        latestRelease = self.getLatestRelease()

        if (latestRelease == None):
            self._error('No release available')
            return False

        try:
            self._installRelease(latestRelease)
        except Exception as e:
            self._error(str(e))
            return False

        return True

    #---------------------------------------------------------------------------
    # updates the contained plugin if needed
    def update(self, currentVersion=None):
        update = self._prepareForUpdate(currentVersion)
        if (update == None): return False

        try:
            self._installRelease(update)
        except Exception as e:
            self._error(str(e))
            return False

        return True

    #---------------------------------------------------------------------------
    # returns the URL for an update if there is one
    def checkForUpdate(self, currentVersion=None):
        update = self._prepareForUpdate(currentVersion)

        return (update != None)

    #---------------------------------------------------------------------------
    # returns the update package, if there is one
    def getUpdate(self, currentVersion):
        self._debug('Current version is: %s' % currentVersion)

        update = self.getLatestRelease()

        if (update == None):
            self._debug('No release available')
            return None

        # assume the tag is the release version
        latestVersion = update['tag_name'].lstrip('v')
        self._debug('Latest release is: %s' % latestVersion)

        if (ver(currentVersion) >= ver(latestVersion)):
            return None

        return update

    #---------------------------------------------------------------------------
    # returns the latest release information from a given user / repo
    # https://developer.github.com/v3/repos/releases/
    def getLatestRelease(self):
        self._debug('Getting latest release from %s/%s...' % (self.owner, self.repo))
        return self._GET('/repos/' + self.owner + '/' + self.repo + '/releases/latest')

    #---------------------------------------------------------------------------
    # returns a tuple for the current rate limit: (limit, remaining, resetTime)
    # https://developer.github.com/v3/rate_limit/
    # NOTE this does not count against the current limit
    def getRateLimit(self):
        limiter = self._GET('/rate_limit')

        remain = int(limiter['rate']['remaining'])
        limit = int(limiter['rate']['limit'])
        resetAt = int(limiter['rate']['reset'])

        return (limit, remain, resetAt)

    #---------------------------------------------------------------------------
    # form a GET request to api.github.com and return the parsed JSON response
    def _GET(self, requestPath):
        self._debug('GET %s' % requestPath)

        headers = {
            'User-Agent': 'Indigo-Plugin-Updater',
            'Accept': 'application/vnd.github.v3+json'
        }

        data = None

        conn = httplib.HTTPSConnection('api.github.com')
        conn.request('GET', requestPath, None, headers)

        resp = conn.getresponse()
        self._debug('HTTP %d %s' % (resp.status, resp.reason))

        if (resp.status == 200):
            data = json.loads(resp.read())
        elif (400 <= resp.status < 500):
            error = json.loads(resp.read())
            self._error('%s' % error['message'])
        else:
            self._error('Error: %s' % resp.reason)

        return data

    #---------------------------------------------------------------------------
    # prepare for an update
    def _prepareForUpdate(self, currentVersion=None):
        self._log('Checking for updates...')

        # sort out the currentVersion based on user params
        if ((currentVersion == None) and (self.plugin == None)):
            self._error('Must provide either currentVersion or plugin reference')
            return None
        elif (currentVersion == None):
            currentVersion = str(self.plugin.pluginVersion)
            self._debug('Plugin version detected: %s' % currentVersion)
        else:
            self._debug('Plugin version provided: %s' % currentVersion)

        update = self.getUpdate(currentVersion)

        if (update == None):
            self._log('No updates are available')
            return None

        self._error('A new version is available: %s' % update['html_url'])

        return update

    #---------------------------------------------------------------------------
    # reads plugin info from the given pList
    def _buildPluginInfo(self, plist):
        pid = plist.get('CFBundleIdentifier', None)
        pname = pluginName = plist.get('CFBundleDisplayName', None)
        pver = pluginVersion = plist.get('PluginVersion', None)

        return PluginInfo(id=pid, name=pname, version=pver)

    #---------------------------------------------------------------------------
    # reads the plugin info from the given path
    def _readPluginInfoFromPath(self, path):
        plistFile = os.path.join(path, 'Contents', 'Info.plist')
        self._debug('Loading plugin info: %s' % plistFile)

        plist = plistlib.readPlist(plistFile)

        return self._buildPluginInfo(plist)

    #---------------------------------------------------------------------------
    # finds the plugin information in the zipfile
    def _readPluginInfoFromArchive(self, zipfile):
        topdir = zipfile.namelist()[0]

        # read and the plugin info contained in the zipfile
        plistFile = os.path.join(topdir, self.path, 'Contents', 'Info.plist')
        self._debug('Reading plugin info: %s' % plistFile)

        plistData = zipfile.read(plistFile)
        if (plistData == None):
            raise Exception('Unable to read new plugin info')

        plist = plistlib.readPlistFromString(plistData)

        return self._buildPluginInfo(plist)

    #---------------------------------------------------------------------------
    # verifies the provided plugin info matches what we expect
    def _verifyPluginInfo(self, pInfo):
        self._debug('Verifying plugin info: %s' % pInfo.id)

        if (pInfo.id == None):
            raise Exception('ID missing in source')
        elif (pInfo.name == None):
            raise Exception('Name missing in source')
        elif (pInfo.version == None):
            raise Exception('Version missing in soruce')

        elif (self.plugin and (self.plugin.pluginId != pInfo.id)):
            raise Exception('ID mismatch: %s' % pInfo.id)

        self._debug('Verified plugin: %s' % pInfo.name)

    #---------------------------------------------------------------------------
    # install a given release
    def _installRelease(self, release):
        tmpdir = tempfile.gettempdir()
        self._debug('Workspace: %s' % tmpdir)

        # the zipfile is held in memory until we extract
        zipfile = self._getZipFileFromRelease(release)
        pInfo = self._readPluginInfoFromArchive(zipfile)

        self._verifyPluginInfo(pInfo)

        # the top level directory should be the first entry in the zipfile
        # it is typically a combination of the owner, repo & release tag
        repotag = zipfile.namelist()[0]

        # this is where the repo files will end up after extraction
        repoBaseDir = os.path.join(tmpdir, repotag)
        self._debug('Destination directory: %s' % repoBaseDir)

        if (os.path.exists(repoBaseDir)):
            shutil.rmtree(repoBaseDir)

        # this is where the plugin will be after extracting
        newPluginPath = os.path.join(repoBaseDir, self.path)
        self._debug('Plugin source path: %s' % newPluginPath)

        # at this point, we should have been able to confirm the top-level directory
        # based on reading the pluginId, we know the plugin in the zipfile matches our
        # internal plugin reference (if we have one), temp directories are available
        # and we know the package location for installing the plugin

        self._debug('Extracting files...')
        zipfile.extractall(tmpdir)

        # now, make sure we got what we expected
        if (not os.path.exists(repoBaseDir)):
            raise Exception('Failed to extract plugin')

        self._installPlugin(newPluginPath)
        self._debug('Installation complete')

    #---------------------------------------------------------------------------
    # install plugin from the existing path
    def _installPlugin(self, pluginPath):
        tmpdir = tempfile.gettempdir()

        pInfo = self._readPluginInfoFromPath(pluginPath)
        self._verifyPluginInfo(pInfo)

        # if the new plugin path does not end in .indigoPlugin, we need to do some
        # path shuffling for 'open' to work properly
        if (not pluginPath.endswith('.indigoPlugin')):
            stagedPluginPath = os.path.join(tmpdir, '%s.indigoPlugin' % pInfo.name)
            self._debug('Staging plugin: %s' % stagedPluginPath)

            if (os.path.exists(stagedPluginPath)):
                shutil.rmtree(stagedPluginPath)

            os.rename(pluginPath, stagedPluginPath)
            pluginPath = stagedPluginPath

        self._debug('Installing %s' % pInfo.name)
        subprocess.call(['open', pluginPath])

    #---------------------------------------------------------------------------
    # return the valid zipfile from the release, or raise an exception
    def _getZipFileFromRelease(self, release):
        # download and verify zipfile from the release package
        zipball = release.get('zipball_url', None)
        if (zipball == None):
            raise Exception('Invalid release package: no zipball')

        self._debug('Downloading zip file: %s' % zipball)

        zipdata = urlopen(zipball).read()
        zipfile = ZipFile(StringIO(zipdata))

        self._debug('Verifying zip file (%d bytes)...' % len(zipdata))
        if (zipfile.testzip() != None):
            raise Exception('Download corrupted')

        return zipfile

    #---------------------------------------------------------------------------
    # convenience method for log messages
    def _log(self, msg):
        # FIXME - this is a nasty hack, can't we pass the log call to a plugin method like debug and error?
        if self.plugin:
           self.plugin.generalLogger.info(msg)

    #---------------------------------------------------------------------------
    # convenience method for debug messages
    def _debug(self, msg):
        if self.plugin:
            self.plugin.generalLogger.debug(msg)

    #---------------------------------------------------------------------------
    # convenience method for error messages
    def _error(self, msg):
        if self.plugin:
            self.plugin.generalLogger.error(msg)

################################################################################
# maps the standard version string as a tuple for comparrison
def ver(vstr): return tuple(map(int, (vstr.split('.'))))

################################################################################
## stub plugin class for testing
class TestPluginStub(object):

    #---------------------------------------------------------------------------
    def __init__(self, version='0'):
        self.pluginId = 'com.heddings.indigo.ghpu'
        self.pluginName = 'Plugin Stub'
        self.pluginVersion = version

    #---------------------------------------------------------------------------
    # expected logging methods
    def log(self, msg): print '%s' % msg
    def debugLog(self, msg): print '[DEBUG] %s' % msg
    def errorLog(self, msg): print '[ERROR] %s' % msg

################################################################################
## TEST ENTRY
if __name__ == "__main__":
    plugin = TestPluginStub()

    updater = GitHubPluginUpdater(plugin=plugin)
    updater.update()

