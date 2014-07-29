#!/usr/bin/python

from __future__ import print_function
import argparse
import sys
import os
import json
import subprocess
import StringIO
import fileinput
import re
import smtplib
from email.mime.text import MIMEText
import shlex
from os.path import expanduser
import zipfile
import errno
import hashlib
import getpass
import time
import xml.etree.ElementTree as ET
import datetime

try:
    import dropbox
except ImportError, e:
    log_error('no dropbox python sdk, please install it: \nhttps://www.dropbox.com/developers/core/sdks/python')
    exit(1)

try:
    import pycurl
except ImportError, e:
    log_error('no pycurl, please install it: \nhttp://pycurl.sourceforge.net/doc/install.html')
    exit(1)

try:
    import keyring
except ImportError, e:
    log_error('no pycurl, please install it: \nhttps://pypi.python.org/pypi/keyring')
    exit(1)

try:
    from git import *
except ImportError, e:
    log_error('no GitPython module, please install it: \nhttps://pythonhosted.org/GitPython/0.3.1/intro.html#installing-gitpython')
    exit(1)

verbose = False
settings = None
ignored_files = ['.DS_Store']

class BuildSettings:
    def __init__(self):
        self.config = {}

        self.build_platform = '_all_'
        self.file_name = None
        self.bundle_version = ''
        self.build_number = ''
        self.build_message = ''
        self.build_info = {}

        self.tf_upload_response = {}
        self.dropbox_upload_cache = []

        self.log_file_name = 'build.log'
        self.log_file = None
        self.notification_mail_password = ''
        self.execution_time = 0
        self.execution_time_text = ''
        self.start_time = 0
        self.tests_total = 0
        self.tests_errors = 0

    key_bi_dropbox_link = 'dropbox'
    key_bi_testflight_link = 'testflight'

    key_dp_source = 'source'
    key_dp_destination = 'destination'
    key_dp_zip = 'zip'
    key_dp_platform = 'platform'
    key_dp_store_link = 'store_link'

    key_tf_response_bundle_version = 'bundle_version'
    key_tf_response_install_url = 'install_url'
    key_tf_response_config_url = 'config_url'
    key_tf_response_created_at = 'created_at'
    key_tf_response_device_family = 'device_family'
    key_tf_response_notify = 'notify'
    key_tf_response_team = 'team'
    key_tf_response_minimum_os_version = 'minimum_os_version'
    key_tf_response_release_notes = 'release_notes'
    key_tf_response_binary_size = 'binary_size'

    key_app_name = 'app_name'
    key_project_path = 'project_path'
    key_default_mail = 'default_mail'
    key_default_mail_smtp = 'default_mail_smtp'
    key_notification_mail_title = 'notification_mail_title'
    key_system_notifier_command = 'system_notifier_command'
    key_version_file = 'version_file'
    key_unity_app = 'unity_app'
    key_unity_app_args = 'unity_app_args'
    key_temp_dir = 'temp_dir'
    key_bundle_method = 'bundle_method'
    key_bundle_output_path = 'bundle_output_path'

    key_dropbox_upload = 'dropbox_upload'
    key_dropbox_app_key = 'dropbox_app_key'
    key_dropbox_app_secret = 'dropbox_app_secret'
    key_dropbox_access_token = 'dropbox_access_token'
    key_dropbox_upload_path = 'dropbox_upload_path'
    key_dropbox_zip_upload = 'dropbox_zip_upload'
    key_dropbox_bundle_path = 'dropbox_bundle_path'

    key_platforms = 'platforms'
    key_unity_build_method = 'unity_build_method'
    key_unity_build_path = 'unity_build_path'

    key_mail_notification = 'mail_notification'
    key_mail_recipents = 'mail_recipents'
    key_commit_changes = 'commit_changes'

    key_testflight_upload = 'testflight_upload'
    key_testflight_url = 'testflight_url'
    key_testflight_api_token = 'testflight_api_token'
    key_testflight_team_token = 'testflight_team_token'
    key_testflight_notes = 'testflight_notes'
    key_testflight_distribution_lists = 'testflight_distribution_lists'
    key_testflight_notify = 'testflight_notify'
    key_testflight_replace = 'testflight_replace'

    key_ios_build = 'ios_build'
    key_xcode_profile_name = 'xcode_profile_name'
    key_xcode_profile_file = 'xcode_profile_file'

    def __str__(self):
        output = BuildSettings.print_dict(self.config)
        output = output + '\nbuild_platform : ' + str(self.build_platform)

        return output

    def start_timer(self):
        self.start_time = time.time()

    def end_timer(self):
        execution_time = time.time() - self.start_time
        self.execution_time_text = str(datetime.timedelta(seconds=execution_time))
        log_info('execution time: ' + self.execution_time_text)

    def start_log(self):
        self.log_file = open(self.log_file_name, 'w', buffering=0)

    def end_log(self):
        self.log_file.close()

    def add_build_info(self, platform_name, dropbox_link=None, testflight_link=None):
        if platform_name not in self.build_info:
            self.build_info[platform_name] = {}
        if dropbox_link is not None:
            self.build_info[platform_name][BuildSettings.key_bi_dropbox_link] = dropbox_link
        if testflight_link is not None:
            self.build_info[platform_name][BuildSettings.key_bi_testflight_link] = testflight_link

    def generate_build_info(self):
        info = ''
        dropbox_text = False
        for platform_name in self.build_info.keys():
            if BuildSettings.key_bi_dropbox_link in self.build_info[platform_name]:
                if not dropbox_text:
                    info = 'Dropbox:\n'
                    dropbox_text = True
                info += ' - ' + platform_name + ' ( '
                info += self.build_info[platform_name][BuildSettings.key_bi_dropbox_link]
                info += ' )\n'

        testflight_text = False
        for platform_name in self.build_info.keys():
            if BuildSettings.key_bi_testflight_link in self.build_info[platform_name]:
                if not testflight_text:
                    info += '\nTestFlight:\n'
                    testflight_text = True
                info += ' - ' + platform_name + ' ( '
                info += self.build_info[platform_name][BuildSettings.key_bi_testflight_link]
                info += ' )\n'

        return info

    @staticmethod
    def write_log(message):
        if settings is not None and settings.log_file is not None:
            settings.log_file.write(str(message) + '\n')

    @staticmethod
    def print_dict(values, prefix = ''):
        output = ''
        for key, value in values.items():
            if type(value) is dict:
                output = output + '\n' + prefix + key + ' : ' + BuildSettings.print_dict(value, prefix + '  ')
            else:
                output = output + '\n' + prefix + key + ' : ' + str(value)
        return output

    @staticmethod
    def sample_config(file_name):
        sample = BuildSettings()
        sample.config[BuildSettings.key_app_name] = 'MyPorjectName'
        sample.config[BuildSettings.key_project_path] = '../'
        sample.config[BuildSettings.key_temp_dir] = "/tmp"
        sample.config[BuildSettings.key_platforms] = {\
            "Android": {
                BuildSettings.key_unity_build_method    : "MyNamespace.MyBuildClass.MyStaticBuildMethod_Android",
                BuildSettings.key_unity_build_path      : "my_output_dir/MyPorjectName.apk",
                BuildSettings.key_dropbox_upload        : True,
                BuildSettings.key_dropbox_upload_path   : "Public/MyPorjectName/Android/",
                BuildSettings.key_dropbox_zip_upload    : False,
                BuildSettings.key_bundle_method         : "MyNamespace.MyAssetBundleBuildClass.MyStaticBuildMethod_Android",
                BuildSettings.key_bundle_output_path    : "my_bundles_output_dir/Android",
                BuildSettings.key_dropbox_bundle_path   : "Public/MyPorjectName/Android/AssetBundles/"

            },

            "iOS": {
                BuildSettings.key_unity_build_method    : "MyNamespace.MyBuildClass.MyStaticBuildMethod_iOS",
                BuildSettings.key_unity_build_path      : "my_output_dir/iOS/MyPorjectName",
                BuildSettings.key_ios_build             : True,
                BuildSettings.key_xcode_profile_name    : "iPhone Distribution: Some Developer (some numbers)",
                BuildSettings.key_xcode_profile_file    : "relative_path_to_provisioning_prifile/profile_name.mobileprovision",
                BuildSettings.key_testflight_upload     : True,
                BuildSettings.key_dropbox_upload        : True,
                BuildSettings.key_dropbox_upload_path   : "Public/MyPorjectName/iOS/",
                BuildSettings.key_dropbox_zip_upload    : False,
                BuildSettings.key_bundle_method         : "MyNamespace.MyAssetBundleBuildClass.MyStaticBuildMethod_iOS",
                BuildSettings.key_bundle_output_path    : "my_bundles_output_dir/iOS",
                BuildSettings.key_dropbox_bundle_path   : "Public/MyPorjectName/iOS/AssetBundles/"
            }
        }

        sample.config[BuildSettings.key_default_mail] = 'some.mail@domain'
        sample.config[BuildSettings.key_system_notifier_command] = 'terminal-notifier -message '
        sample.config[BuildSettings.key_version_file] = 'Assets/Resources/version.txt'
        sample.config[BuildSettings.key_unity_app] = '/Applications/Unity/Unity.app/Contents/MacOS/Unity'
        sample.config[BuildSettings.key_unity_app_args] = '-logFile'

        sample.config[BuildSettings.key_dropbox_app_key] = '_dropbox_app_key_ (you need to create app)'
        sample.config[BuildSettings.key_dropbox_app_secret] = '_dropbox_app_secret_'
        sample.config[BuildSettings.key_dropbox_access_token] = None

        sample.config[BuildSettings.key_testflight_url]                 = 'http://testflightapp.com/api/builds.json'
        sample.config[BuildSettings.key_testflight_api_token]           = '_testflight_api_token_'
        sample.config[BuildSettings.key_testflight_team_token]          = '_testflight_team_token_'
        sample.config[BuildSettings.key_testflight_notes]               = 'Build uploaded automatically.'
        sample.config[BuildSettings.key_testflight_distribution_lists]  = ['Your Custom Created Distribution List']
        sample.config[BuildSettings.key_testflight_notify]              = False
        sample.config[BuildSettings.key_testflight_replace]             = False

        sample.config[BuildSettings.key_mail_notification] = False
        sample.config[BuildSettings.key_mail_recipents] = ['some.mail@domain', 'some.other.mail@domain']
        sample.config[BuildSettings.key_default_mail_smtp] = 'smpt server to send mail, i.e.: smtp.gmail.com:587'
        sample.config[BuildSettings.key_notification_mail_title] = '[new build][MyPorjectName]'
        sample.config[BuildSettings.key_commit_changes] = False

        sample.save_config_file(file_name)

        return sample

    def pretty_version(self):
        return self.bundle_version + ' (' + str(self.build_number) + ')'

    def read_config_file(self, file_name):
        self.file_name = file_name
        config_to_read = open(file_name)
        self.config = json.load(config_to_read)
        config_to_read.close()

    def save_config_file(self, file_name = None):
        log_debug(self.file_name)
        file_to_open = file_name
        if file_to_open is None:
            file_to_open = self.file_name

        content = json.dumps(self.config, sort_keys=True, indent=4, separators=(',', ': '))

        f = open(file_to_open, "w")
        try:
            f.write(content)
        except IOError:
            log_error('cannot write to config file: ' + file_to_open)
        finally:
            f.close()

def log_info(message):
    print(str(message))
    BuildSettings.write_log(message)

def log_debug(message):
    debug_message = str(message)
    if verbose:
        print(debug_message)
    BuildSettings.write_log(debug_message)

def log_error(message):
    error_message = 'ERROR: ' + str(message)
    print(error_message, file=sys.stderr)
    BuildSettings.write_log(error_message)

def log_notification(message):
    print(str(message))
    BuildSettings.write_log(str(message))
    execute_command(settings.config[BuildSettings.key_system_notifier_command] +  ' "' + str(message) + '"')

def parse_arguments():
    global settings

    parser = argparse.ArgumentParser(description='builds and optionally uploads unity game')

    parser.add_argument('-c', '--create_config_file', metavar = 'CONFIG_FILE', dest='create_config', action='store', default=None,
                        help='create config file')
    parser.add_argument('-x', '--execute', metavar = 'CONFIG_FILE', dest='execute_config', action='store', default=None,
                        help='read config file')
    parser.add_argument('-p', '--platform', metavar = 'PLATFORM', dest='build_platform', action='store', default=None,
                        help='builds specific platform (default: build all defined platforms)')
    parser.add_argument('-i', '--build_info', metavar = 'MESSAGE', dest='build_message', action='store', default=None,
                        help='message attached to build notificaiton')
    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true', default=False,
                        help='prints debug information')
    args = parser.parse_args()

    global verbose
    verbose = args.verbose

    if args.create_config is not None:
        settings = BuildSettings.sample_config(args.create_config)
        settings.file_name = args.create_config

    if args.execute_config is not None:
        settings = BuildSettings()
        settings.read_config_file(args.execute_config)

    if args.execute_config is None and args.create_config is None:
        log_error('no action specified: -c or -x')
        sys.exit(1)

    if args.build_platform is not None:
        if args.build_platform in settings.config[BuildSettings.key_platforms].keys():
            settings.build_platform = args.build_platform
        else:
            log_error("Wrong platform defined!\nAvailable: " + ", ".join(settings.config[BuildSettings.key_platforms].keys()))
            sys.exit(1)

    if args.build_message is not None:
        settings.build_message = args.build_message

    log_debug('\n' + str(settings) + '\n')

    if args.execute_config is None:
        sys.exit(0)
    elif args.build_message is None:
        log_error("please specify build message (option: -i)")
        sys.exit(1)

def parse_version():
    project_path = settings.config[BuildSettings.key_project_path]
    version_file = settings.config[BuildSettings.key_version_file]

    file_with_version = open(os.path.join(project_path, version_file))
    parsed = json.load(file_with_version)
    file_with_version.close()

    settings.bundle_version = parsed['bundle']
    settings.build_number = parsed['build']

    log_debug('bundle version : ' + settings.bundle_version)
    log_debug('build number   : ' + str(settings.build_number))

def increment_build_number():
    project_path = settings.config[BuildSettings.key_project_path]
    version_file = settings.config[BuildSettings.key_version_file]

    file_with_version = open(os.path.join(project_path, version_file))
    parsed = json.load(file_with_version)
    file_with_version.close()

    parsed['build'] = parsed['build'] + 1
    incremented = json.dumps(parsed)

    file_with_version = open(os.path.join(project_path, version_file), 'w')
    file_with_version.write(incremented)
    file_with_version.close()

    log_debug('increased build number: ' + str(parsed['build']))

def build_unity_projects():
    if settings.build_platform == '_all_':
        log_debug('building all unity platforms')
        for platform in settings.config[BuildSettings.key_platforms].keys():
            build_unity_platform(platform)
    else:
        build_unity_platform(settings.build_platform)

def build_unity_platform(platform_name):
    log_notification('building: ' + platform_name)

    method = settings.config[BuildSettings.key_platforms][platform_name][BuildSettings.key_unity_build_method]
    args = settings.config[BuildSettings.key_unity_app_args]
    unity = settings.config[BuildSettings.key_unity_app]
    execute_command(unity + ' ' + args + ' -batchmode -quit -executeMethod ' + method, dry_run = False)

    platform_settings = settings.config[BuildSettings.key_platforms][platform_name]
    build_asset_bundles(platform_settings, platform_name)

    if BuildSettings.key_ios_build in platform_settings:
        if platform_settings[BuildSettings.key_ios_build]:
            return

    product = platform_settings[BuildSettings.key_unity_build_path]
    product = os.path.join(settings.config[BuildSettings.key_project_path], product)
    destination = platform_settings[BuildSettings.key_dropbox_upload_path]
    zipped = platform_settings[BuildSettings.key_dropbox_zip_upload]
    dropbox_add_file_to_upload(product, destination, zipped, platform=platform_name)

def build_asset_bundles(platform_settings, platform_name):
    if BuildSettings.key_bundle_method not in platform_settings:
        return

    log_notification('creating asset bundles: ' + platform_name)
    method = platform_settings[BuildSettings.key_bundle_method]
    args = settings.config[BuildSettings.key_unity_app_args]
    unity = settings.config[BuildSettings.key_unity_app]
    execute_command(unity + ' ' + args + ' -batchmode -quit -executeMethod ' + method, dry_run = False)

    if BuildSettings.key_dropbox_bundle_path not in platform_settings:
        return

    product = platform_settings[BuildSettings.key_bundle_output_path]
    product = os.path.join(settings.config[BuildSettings.key_project_path], product)
    destination = platform_settings[BuildSettings.key_dropbox_bundle_path]
    dropbox_add_file_to_upload(product, destination, False, platform=platform_name)

def execute_command(command, dry_run=False):
    log_debug('executing command: ' + command)
    if not dry_run:
        p = subprocess.Popen(shlex.split(command), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output, error = p.communicate()
        exit_code = p.returncode

        log_debug('command exit code: ' + str(exit_code))
        log_debug('command output:\n' + str(output))

        if exit_code != 0:
            log_error('command: ' + command + '\nexit code: ' + str(exit_code) + '\nerror: ' + str(error))
            sys.exit(exit_code)
        else:
            return (exit_code, output)
    return (0, '')

def dropbox_authenticate():
    dropbox_access_token = settings.config[BuildSettings.key_dropbox_access_token]
    if dropbox_access_token in (None, ''):
        dropbox_access_token = dropbox_request_for_token()

    success = False
    while not success:
        client = dropbox.client.DropboxClient(dropbox_access_token)
        try:
            client.account_info()
            success = True
        except dropbox.rest.ErrorResponse, e:
            log_error("Wrong or missing Dropbox access token!")
            dropbox_access_token = dropbox_request_for_token()

    dropbox_save_access_token(dropbox_access_token)

    log_debug('linked dropbox account: ' + str(client.account_info()))

    return client

def request_dropbox_password():
    if BuildSettings.key_dropbox_app_key in settings.config and len(settings.config[BuildSettings.key_dropbox_app_key]) > 0:
        log_info('checking dropbox token')
        dropbox_authenticate()

def dropbox_save_access_token(token):
    log_debug('saving access token')
    settings.config[BuildSettings.key_dropbox_access_token] = token
    settings.save_config_file()

def dropbox_request_for_token():
    dropbox_app_key     = settings.config[BuildSettings.key_dropbox_app_key]
    dropbox_app_secret  = settings.config[BuildSettings.key_dropbox_app_secret]

    flow = dropbox.client.DropboxOAuth2FlowNoRedirect(dropbox_app_key, dropbox_app_secret)
    authorize_url = flow.start()
    log_info('1. Go to: ' + authorize_url)
    log_info('2. Click "Allow" (you might have to log in first)')
    log_info('3. Copy the authorization code.')
    code = raw_input("Enter the authorization code here: ").strip()

    try:
        access_token, user_id = flow.finish(code)
        return access_token
    except dropbox.rest.ErrorResponse, e:
        return "wrong"
    except ValueError:
        return None

def dropbox_upload(source, destination):
    client = dropbox_authenticate()

    if os.path.isdir(source):
        for root, dirs, files in os.walk(source):
            for file in files:
                file_name = os.path.join(root, file)
                dest_path = os.path.join(destination, file_name[len(source) + 1:])
                dropbox_upload_single_file(client, file_name, dest_path)
    else:
         dropbox_upload_single_file(client, source, destination)

def dropbox_upload_single_file(client, source, destination):
    if os.path.basename(source) in ignored_files:
        log_debug('ignoring file: ' + source)
        return

    f = open(source, 'rb')
    log_info('uploading file to dropbox: ' + source + ' => ' + destination)
    response = client.put_file(destination, f, overwrite=True)
    f.close()
    log_debug(response)

def dropbox_add_file_to_upload(source, destination, zipped, platform, store_link=True):
    cache = {\
        BuildSettings.key_dp_source : source,
        BuildSettings.key_dp_destination : destination,
        BuildSettings.key_dp_zip : zipped,
        BuildSettings.key_dp_platform: platform,
        BuildSettings.key_dp_store_link: store_link}

    log_debug('adding dropbox file upload: ' + source + ' (zip: ' + str(zipped) + ') => ' + destination);
    settings.dropbox_upload_cache.append(cache)

def upload_files_to_dropbox():
    for cache in settings.dropbox_upload_cache:
        source = cache[BuildSettings.key_dp_source]
        destination = cache[BuildSettings.key_dp_destination]
        zipped = cache[BuildSettings.key_dp_zip]
        platform = cache[BuildSettings.key_dp_platform]
        store = cache[BuildSettings.key_dp_store_link]

        upload_file_to_dropbox(source, destination, zipped, platform, store)

def upload_file_to_dropbox(source, destination, zipped, platform, store_link):
    upload_file = source
    if zipped:
        path, filename = os.path.split(upload_file)
        filename , extension = os.path.splitext(filename)
        zipped_file = os.path.join(settings.config[BuildSettings.key_temp_dir], filename + platform + '.zip')
        zip_file_or_dir(upload_file, zipped_file)
        upload_file = zipped_file

    upload_file_path, upload_file_name = os.path.split(upload_file)
    final_destination = os.path.join(destination, upload_file_name)
    dropbox_upload(upload_file, final_destination)

    link = final_destination
    if os.path.isdir(upload_file):
        link = None
        for file in os.listdir(upload_file):
            if file.endswith('.html') or file.endswith('.apk'):
                link = final_destination + '/' + file

    if store_link and link is not None:
        client = dropbox_authenticate()
        share_link = ''
        public_link = link.startswith('Public/')
        if public_link:
            link = link[len('Public/'):]
            share_link = 'dl.dropboxusercontent.com/u/' + str(client.account_info()['uid']) + '/' + link
        else:
            share_link = client.share(link, short_url=False)
            share_link = share_link['url'].replace('www.dropbox.com', 'dl.dropboxusercontent.com', 1)
        settings.add_build_info(platform, share_link)

def upload_projects_to_testflight():
    if settings.build_platform == '_all_':
        for platform in settings.config[BuildSettings.key_platforms].keys():
            testflight_upload(platform)
    else:
        testflight_upload(settings.build_platform)

def testflight_upload(platform):
    platform_settings = settings.config[BuildSettings.key_platforms][platform]

    if (BuildSettings.key_ios_build not in platform_settings.keys()) or\
        (BuildSettings.key_testflight_upload not in platform_settings) or\
        not platform_settings[BuildSettings.key_testflight_upload]:
        return

    log_info('uploading to testflight ' + platform)

    url                 = settings.config[BuildSettings.key_testflight_url]
    api_token           = settings.config[BuildSettings.key_testflight_api_token]
    team_token          = settings.config[BuildSettings.key_testflight_team_token]
    notes               = settings.config[BuildSettings.key_testflight_notes] + '\n' + settings.build_message
    distribution_lists  = settings.config[BuildSettings.key_testflight_distribution_lists]
    notify              = settings.config[BuildSettings.key_testflight_notify]
    replace             = settings.config[BuildSettings.key_testflight_replace]

    ipa_file, dsym_file = get_ios_build_files(settings.config[BuildSettings.key_temp_dir])

    fout = StringIO.StringIO()

    c = pycurl.Curl()

    post_data = [\
        ('file', (c.FORM_FILE, ipa_file)),
        ('dsym', (c.FORM_FILE, dsym_file)),
        ('api_token', api_token),
        ('team_token', team_token),
        ('notes', notes),
        ('distribution_lists', ','.join(distribution_lists)),
        ('notify', 'true' if notify else 'false'),
        ('replace', 'true' if replace else 'false')]

    c.setopt(c.WRITEFUNCTION, fout.write)
    c.setopt(c.URL, url)
    c.setopt(c.NOPROGRESS, 0)
    c.setopt(c.PROGRESSFUNCTION, curl_progress)
    c.setopt(c.SSL_VERIFYPEER, 0)
    c.setopt(c.SSL_VERIFYHOST, 0)
    c.setopt(c.POST, 1)
    c.setopt(c.HTTPPOST, post_data)
    c.perform()

    response_code = c.getinfo(pycurl.RESPONSE_CODE)
    response_data = fout.getvalue()
    print('')
    log_debug('TESTFLIGHT RESPONSE CODE: ' + str(response_code))
    log_debug('TESTFLIGHT RESPONSE DATA:\n' + str(response_data))

    if response_code is 200:
        response = json.loads(response_data)
        settings.add_build_info(platform, testflight_link=response['install_url'])

    io = StringIO.StringIO(response_data)
    settings.tf_upload_response = json.load(io)

    c.close()

def curl_progress(download_t, download_d, upload_t, upload_d):
    uploaded = ((upload_d / upload_t) * 100) if upload_t != 0 else 0
    print("\rtestflight upload progress: %0.2f %%" % uploaded, end="")
    sys.stdout.flush()

def build_xcode_projects():
    for platform, platform_settings in settings.config[BuildSettings.key_platforms].items():
        if settings.build_platform in ('_all_', platform):
            if BuildSettings.key_ios_build in platform_settings and platform_settings[BuildSettings.key_ios_build] is True:
                build_ios_xcode_project(platform, platform_settings)

def build_ios_xcode_project(platform_name, platform_settings):
    log_notification('archiving xcode project for ' + platform_name)

    log_debug('setting ditribution profile')
    xcode_project_dir = os.path.join(settings.config[BuildSettings.key_project_path], platform_settings[BuildSettings.key_unity_build_path])
    xcode_project_dir = os.path.join(xcode_project_dir, 'Unity-iPhone.xcodeproj')
    xcode_project_file =  os.path.join(xcode_project_dir, 'project.pbxproj')

    log_debug('xcode project file: ' + xcode_project_file)
    for line in fileinput.input(xcode_project_file, inplace=True):
        m = re.search("(\t+\"CODE_SIGN_IDENTITY\[sdk\=iphoneos\*\]\" = )" + "\"iPhone Developer\"", line)
        if m is None:
            print(line, end="")
        else:
            print(m.group(1) + "\"" + platform_settings[BuildSettings.key_xcode_profile_name] + "\";")

    execute_command('xcodebuild archive -project ' + xcode_project_dir + ' -scheme Unity-iPhone -configuration Release', dry_run=False)
    log_info('adding xcode archive comment: ' + settings.pretty_version())
    archive_dir = get_latest_archive_dir()
    plist_file = os.path.join(archive_dir, 'Info.plist')
    log_debug('archive plist file: ' + plist_file)

    execute_command("/usr/libexec/PlistBuddy -c \'Add :Comment string \"" + settings.pretty_version() + "\"\' " + "\"" + plist_file + "\"", dry_run=False)

    ipa_file, dsym_file = get_ios_build_files(settings.config[BuildSettings.key_temp_dir])

    if os.path.exists(ipa_file):
        os.remove(ipa_file)
    if os.path.exists(dsym_file):
        os.remove(dsym_file)

    app_dir = os.path.join(archive_dir, os.path.join('Products/Applications', settings.config[BuildSettings.key_app_name] + '.app'))
    log_debug('app dir: ' + app_dir)

    log_info('creating .ipa file')
    signing_identity = platform_settings[BuildSettings.key_xcode_profile_name]
    provisioning_profile = os.path.join(settings.config[BuildSettings.key_project_path], platform_settings[BuildSettings.key_xcode_profile_file])
    execute_command('/usr/bin/xcrun' +
                    ' -sdk iphoneos PackageApplication' +
                    ' -v "' + app_dir + '"' +
                    ' -o "' + ipa_file + '"' +
                    ' --sign "' + signing_identity + '"' +
                    ' --embed "' + provisioning_profile + '"', dry_run=False)

    dsym_dir = os.path.join(archive_dir, os.path.join('dSYMs', settings.config[BuildSettings.key_app_name] + '.app.dSYM'))
    log_debug("dsym dir: " + dsym_dir)
    zip_file_or_dir(dsym_dir, dsym_file)

    if platform_settings[BuildSettings.key_dropbox_upload]:
        dp_dest = os.path.join(platform_settings[BuildSettings.key_dropbox_upload_path])
        dropbox_add_file_to_upload(ipa_file, dp_dest, zipped=False, platform=platform_name, store_link=True)
        dropbox_add_file_to_upload(dsym_file, dp_dest, zipped=False, platform=platform_name, store_link=False)

def get_latest_archive_dir():
    home_dir = expanduser("~")
    all_archives_dir = os.path.join(home_dir, 'Library/Developer/Xcode/Archives/')
    latest_archive_dir = sorted(os.walk(all_archives_dir).next()[1], reverse=True)[0]
    archive_dir = sorted(os.walk(os.path.join(all_archives_dir, latest_archive_dir)).next()[1], reverse=True)[0]
    return os.path.join(all_archives_dir, os.path.join(latest_archive_dir, archive_dir))

def get_ios_build_files(tmp_dir):
    return (os.path.join(tmp_dir, settings.config[BuildSettings.key_app_name] + '.ipa'),
            os.path.join(tmp_dir, settings.config[BuildSettings.key_app_name] + '.dSYM.zip'))

def zip_file_or_dir(source, destination):
    log_info('zipping: ' + source + ' => ' + destination)
    path, filename = os.path.split(destination)
    mkdir_p(path)

    path_to_zip, file_to_zip = os.path.split(source)

    zf = zipfile.PyZipFile(destination, mode='w', compression=zipfile.ZIP_DEFLATED)
    try:
        zf.debug = 3
        if os.path.isdir(source):
            for root, dirs, files in os.walk(source):
                for file in files:
                    file_name = os.path.join(root, file)
                    zf.write(file_name, file_name[len(path_to_zip):])
        else:
            zf.write(source, source[len(path_to_zip):])
    finally:
        zf.close()

def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(path):
            pass
        else: raise

def mail_notification_message():
    message = 'Automatically generated mail.\n'
    message += 'game version: ' + settings.pretty_version() + '\n'
    message += 'build time: ' + settings.execution_time_text + '\n'
    message += unit_tests_results() + '\n\n'
    message += settings.build_message.replace('\\n', '\n') + '\n\n'
    message += settings.generate_build_info()

    return message

def mail_notification_title():
    return settings.config[BuildSettings.key_notification_mail_title] + ' ' + settings.pretty_version()

def keyring_service():
    return 'zbyhoo\'s unity auto build script'

def mail_hash(mail):
    return hashlib.md5(mail.encode()).hexdigest()

def get_mail_password(mail):
    return keyring.get_password(keyring_service(), mail_hash(mail))

def set_mail_password(mail, password):
    delete_mail_password(mail)
    keyring.set_password(keyring_service(), mail_hash(mail), password)

def delete_mail_password(mail):
    try:
        keyring.delete_password(keyring_service(), mail_hash(mail))
    except:
        pass

def mail_notification():
    if not settings.config[BuildSettings.key_mail_notification]:
        return

    from_addr = settings.config[BuildSettings.key_default_mail]
    to_addrs = settings.config[BuildSettings.key_mail_recipents]

    msg = MIMEText(mail_notification_message())
    msg['Subject'] = mail_notification_title()
    msg['From'] = from_addr
    msg['To'] = ', '.join(to_addrs)

    server = mail_authenticate()

    log_debug('sending mail:\n' + msg.as_string())
    server.sendmail(from_addr, to_addrs, msg.as_string())
    log_info('notification mail sent')
    server.quit()

def mail_authenticate():
    mail = settings.config[BuildSettings.key_default_mail]
    smtp = settings.config[BuildSettings.key_default_mail_smtp]
    password = get_mail_password(mail)
    if password is None:
        password = prompt_mail_password(mail)

    server = smtplib.SMTP(smtp)
    server.starttls()
    logged_in = False
    while not logged_in:
        try:
            server.login(mail, password)
            logged_in = True
        except smtplib.SMTPAuthenticationError, e:
            password = get_mail_password(mail)
            if password is not None:
                delete_mail_password(mail)
            log_error('cannot authenticate')
            password = prompt_mail_password(mail)
    return server

def prompt_mail_password(mail):
    password = getpass.getpass(mail + ' password: ')
    set_mail_password(mail, password)
    return password

def request_mail_password():
    if BuildSettings.key_default_mail in settings.config and len(settings.config[BuildSettings.key_default_mail]) > 0:
        log_info('checking mail password')
        mail_authenticate()

def prompt(prompt):
    return raw_input(prompt).strip()

def commit_version_file():
    if settings.config[BuildSettings.key_commit_changes]:
        project_path = settings.config[BuildSettings.key_project_path]
        version_file = settings.config[BuildSettings.key_version_file]

        repo = Repo(project_path)

        log_debug('commiting version file: ' + version_file)
        repo.index.add([version_file])
        repo.index.commit('build v' + settings.pretty_version())
        log_debug('git commit performed')

def run_unit_tests():
    log_info('running unit tests')

    unity = settings.config[BuildSettings.key_unity_app]
    result_file = os.path.join(settings.config[BuildSettings.key_project_path], 'UnitTestResults.xml')
    if os.path.exists(result_file):
        os.remove(result_file)
    execute_command(unity + ' -batchmode -quit -executeMethod ' + 'UnityTest.Batch.RunUnitTests', dry_run=False)

    tree = ET.parse(os.path.abspath(result_file))
    root = tree.getroot()

    settings.tests_total = int(root.attrib['total'])
    settings.tests_errors = int(root.attrib['errors']) + int(root.attrib['failures'])
    log_info(unit_tests_results())

    if (settings.tests_errors > 0):
        log_error('some unit tests failed')
        sys.exit(1)

def unit_tests_results():
    if settings.tests_total == 0:
        return 'unit tests: none'

    return 'unit tests passed: ' + str(settings.tests_total - settings.tests_errors) + '/' + str(settings.tests_total) +\
           ' (' + "{0:.2f}".format(float(settings.tests_total - settings.tests_errors) / settings.tests_total * 100) + '%)'

def main():
    parse_arguments()
    settings.start_timer()
    settings.start_log()

    request_mail_password()
    request_dropbox_password()

    run_unit_tests()

    # todo: generalize
    increment_build_number()
    parse_version()

    build_unity_projects()
    build_xcode_projects()

    upload_files_to_dropbox()
    upload_projects_to_testflight()

    # todo: genralize
    commit_version_file()

    settings.end_timer()
    mail_notification()
    settings.end_log()

if __name__ == '__main__':
    main()


