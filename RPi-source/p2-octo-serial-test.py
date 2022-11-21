#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import _thread
from functools import partial
import time
import datetime
from time import sleep, localtime, strftime
import os
import re
import subprocess
import sys
import os.path
import json
import argparse
from collections import deque
from tkinter.tix import NoteBook
from colorama import init as colorama_init
from colorama import Fore, Back, Style
import serial
from configparser import ConfigParser
from email.mime.text import MIMEText
from subprocess import Popen, PIPE
from enum import Enum, unique
from signal import signal, SIGPIPE, SIG_DFL
import sendgrid
from sendgrid.helpers.mail import Content, Email, Mail
signal(SIGPIPE,SIG_DFL)
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import socket
import struct
import binascii
import ctypes

if False:
    # will be caught by python 2.7 to be illegal syntax
    print_line('Sorry, this script requires a python3 runtime environment.', file=sys.stderr)
    os._exit(1)

# v0.0.1 - awaken email send
# v0.0.2 - add file handling

script_version  = "1.3.5"
script_name     = 'p2-cid-gw-daemon.py'
script_info     = '{} v{}'.format(script_name, script_version)
project_name    = 'P2-CID-gw'
project_url     = 'https://github.com/ironsheep/P2-Cycle-Info-Display'

# -----------------------------------------------------------------------------
# the BELOW are identical to that found in our gateway .spin2 object
#   (!!!they must be kept in sync!!!)
# -----------------------------------------------------------------------------

# markers found within the data arriving from the P2 but likely will NOT be found in normal user data sent by the P2
parm_sep    = '^|^'
body_start  = 'email|Start'
body_end    = 'email|End'

# the following enum EFI_* name order and starting value must be identical to that found in our gateway .spin2 object
FolderId = Enum('FolderId', [
     'EFI_VAR',
     'EFI_TMP',
     'EFI_CONTROL',
     'EFI_STATUS',
     'EFI_LOG',
     'EFI_MAIL',
     'EFI_PROC'], start=100)

#for folderId in FolderId:
#    print(folderId, folderId.value)

# the following enum FM_* name order and starting value must be identical to that found in our gateway .spin2 object
FileMode = Enum('FileMode', [
     'FM_READONLY',
     'FM_WRITE',
     'FM_WRITE_CREATE',
     'FM_LISTEN'], start=200)

#for fileMode in FileMode:
#    print(fileMode, fileMode.value)

# -----------------------------------------------------------------------------
# the ABOVE are identical to that found in our gateway .spin2 object
# -----------------------------------------------------------------------------
#   Colorama constants:
#  Fore: BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE, RESET.
#  Back: BLACK, RED, GREEN, YELLOW, BLUE, MAGENTA, CYAN, WHITE, RESET.
#  Style: DIM, NORMAL, BRIGHT, RESET_ALL
#

# console log file-pointer
conlog_fp = None

# Logging function
def print_line(text, error=False, warning=False, info=False, verbose=False, debug=False, console=True):
    timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
    if console:
        if error:
            print(Fore.RED + Style.BRIGHT + '[{}] '.format(timestamp) + Style.NORMAL + '{}'.format(text) + Style.RESET_ALL, file=sys.stderr)
        elif warning:
            print(Fore.YELLOW + Style.BRIGHT + '[{}] '.format(timestamp) + Style.NORMAL + '{}'.format(text) + Style.RESET_ALL)
        elif info or verbose:
            if verbose:
                # conditional verbose output...
                if opt_verbose:
                    print(Fore.GREEN + '[{}] '.format(timestamp) + Fore.YELLOW  + '- ' + '{}'.format(text) + Style.RESET_ALL)
            else:
                # info...
                print(Fore.MAGENTA + '[{}] '.format(timestamp) + Fore.WHITE  + '- ' + '{}'.format(text) + Style.RESET_ALL)
        elif debug:
            # conditional debug output...
            if opt_debug:
                print(Fore.CYAN + '[{}] '.format(timestamp) + '- (DBG): ' + '{}'.format(text) + Style.RESET_ALL)
        else:
            print(Fore.GREEN + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)
        if opt_console_logging:
            # determine log prefix
            prefixText = '- '
            if opt_debug:
                prefixText = '- (DBG): '
            elif warning:
                prefixText = 'WARNING: - '
            elif error:
                prefixText = 'ERROR: - '
            # determine if message should be reported
            bShouldLog = True
            if verbose and not opt_verbose:
                bShouldLog = False
            elif debug and not opt_debug:
                bShouldLog = False
            # now write to log if should be reported
            if bShouldLog:
                conlog_fp.write('[{}] '.format(timestamp) + '{}'.format(prefixText) + '{}'.format(text) + '\n')

# -----------------------------------------------------------------------------
#  Script Argument parsing
# -----------------------------------------------------------------------------
opt_term_log = True

# Argparse
parser = argparse.ArgumentParser(description=project_name, epilog='For further details see: ' + project_url)
parser.add_argument("-c", '--config_dir', help='set directory where config.ini is located', default=sys.path[0])
parser.add_argument("-d", "--debug", help="show debug output", action="store_true")
parser.add_argument("-f", '--fragments', help='write TCP fragement log', action="store_true")
parser.add_argument("-l", '--log', help='write .csv (l)og', action="store_true")
parser.add_argument("-p", "--packets", help="show (p)acket - TCP traffic debug", action="store_true")
parser.add_argument("-o", "--output_filename", help="log console (o)utput to file", default='')
parser.add_argument("-t", "--test", help="run from canned test file", action="store_true")
parser.add_argument("-v", "--verbose", help="increase output verbosity", action="store_true")
parser.add_argument("-s", "--single", help="merge ped/cycle into single ctr", action="store_true")
parser.add_argument("-n", "--no_tcp", help="disable sensor TCP communication", action="store_true")
parse_args = parser.parse_args()

opt_logging = parse_args.log
opt_verbose = parse_args.verbose
opt_debug = parse_args.debug
opt_single = parse_args.single
opt_no_tcp = parse_args.no_tcp
opt_log_fragments = parse_args.fragments
opt_useTestFile = parse_args.test
config_dir = parse_args.config_dir
opt_show_tcp = parse_args.packets
conlog_filename = parse_args.output_filename

opt_console_logging = False
if len(conlog_filename) > 0:
    if os.path.exists(conlog_filename):
        print_line('Log {} already exists, Aborting!'.format(conlog_filename), error=True)
        os._exit(1)
    else:
        opt_console_logging = True
        conlog_fp = open(conlog_filename, "w")
        print_line("Logging started", debug=True)

print_line(script_info, info=True)
if opt_verbose:
    print_line('Verbose enabled', verbose=True)
if opt_debug:
    print_line('Debug enabled', debug=True)
if opt_show_tcp:
    print_line('TCP Debug enabled', debug=True)
if opt_no_tcp:
    print_line('TCP Communication disabled', warning=True)
if opt_single:
    print_line('Merging Counters', info=True)
if opt_useTestFile:
    print_line('TEST: debug stream is test file', debug=True)
if opt_console_logging:
    print_line('Echoing output to log: {}'.format(conlog_filename), info=True)

# -----------------------------------------------------------------------------
#  Config File parsing
# -----------------------------------------------------------------------------
config = ConfigParser(delimiters=('=', ), inline_comment_prefixes=('#'))
config.optionxform = str
try:
    with open(os.path.join(config_dir, 'config.ini')) as config_file:
        config.read_file(config_file)
except IOError:
    print_line('No configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)

# default domain when hostname -f doesn't return it
#  load any override from config file
default_domain = ''
fallback_domain = config['Daemon'].get('fallback_domain', default_domain).lower()

# default daemon use folder locations
default_folder_tmp = '/tmp/P2-RPi-ioT-gateway'
default_folder_var = '/var/P2-RPi-ioT-gateway'
default_folder_control = '/var/www/html/P2-RPi-ioT-gateway/control'
default_folder_status = '/var/P2-RPi-ioT-gateway/status'
default_folder_log = '/var/log/P2-RPi-ioT-gateway'
default_folder_mail = '/var/P2-RPi-ioT-gateway/mail'
default_folder_proc = '/var/P2-RPi-ioT-gateway/proc'

# load any folder overrides from config file
folder_tmp = config['Daemon'].get('folder_tmp', default_folder_tmp)
folder_var = config['Daemon'].get('folder_var', default_folder_var)
folder_control = config['Daemon'].get('folder_control', default_folder_control)
folder_status = config['Daemon'].get('folder_status', default_folder_status)
folder_log = config['Daemon'].get('folder_log', default_folder_log)
folder_mail = config['Daemon'].get('folder_mail', default_folder_mail)
folder_proc = config['Daemon'].get('folder_proc', default_folder_proc)

# and set up dictionary so we can get path indexed by enum value
folderSpecByFolderId = {}
folderSpecByFolderId[FolderId.EFI_TMP] = folder_tmp
folderSpecByFolderId[FolderId.EFI_VAR] = folder_var
folderSpecByFolderId[FolderId.EFI_CONTROL] = folder_control
folderSpecByFolderId[FolderId.EFI_STATUS] = folder_status
folderSpecByFolderId[FolderId.EFI_LOG] = folder_log
folderSpecByFolderId[FolderId.EFI_MAIL] = folder_mail
folderSpecByFolderId[FolderId.EFI_PROC] = folder_proc

# load any sendgrid use and details from config file
default_api_key = ''
default_from_addr = ''

use_sendgrid = config['EMAIL'].getboolean('use_sendgrid', False)
sendgrid_api_key = config['EMAIL'].get('sendgrid_api_key', default_api_key)
sendgrid_from_addr = config['EMAIL'].get('sendgrid_from_addr', default_from_addr)
print_line('CONFIG: use sendgrid={}'.format(use_sendgrid), debug=True)
print_line('CONFIG: sendgrid_api_key=[{}]'.format(sendgrid_api_key), debug=True)
print_line('CONFIG: sendgrid_from_addr=[{}]'.format(sendgrid_from_addr), debug=True)

# ----------------------------------------------
#   New for Cycle Info Display (CID)
#
# default RoadSys TCP IP values
default_tcp_hostname = ''
default_tcp_port = 0
default_log_packets = False
default_log_pkt_fragments = False
# values in seconds
default_tcp_timeout = 40
default_comm_keepalive = 70
default_write_timeout = 3600
# display layout/colors

default_format_count = 0
default_value_count = 0
default_sum_count = 0

# load RoadSys override values
rs_tcp_hostname     = config['RoadSys'].get('hostname', default_tcp_hostname)
rs_tcp_port         = config['RoadSys'].getint('port', default_tcp_port)
rs_tcp_timeout      = config['RoadSys'].getint('tcp_timeout', default_tcp_timeout)
rs_comm_keepalive   = config['RoadSys'].getint('keepalive', default_comm_keepalive)
rs_write_seconds    = config['RoadSys'].getint('count_write_timeout', default_write_timeout)
rs_log_packets      = config['RoadSys'].getboolean('log_packets', default_log_packets)
rs_log_pkt_fragments = config['RoadSys'].getboolean('log_pkt_fragments', default_log_pkt_fragments)

rs_format_count     = config['RoadSys'].getint('cidFormatCount', default_format_count)
rs_value_count      = config['RoadSys'].getint('cidValueCount', default_value_count)
rs_sum_count        = config['RoadSys'].getint('cidSumCount', default_sum_count)

if rs_tcp_hostname == default_tcp_hostname or rs_tcp_port == default_tcp_port:
    print_line('Missing "hostname" or "port" for readsys sensor! Aborting', error=True, sd_notify=True)
    sys.exit(1)
else:
    print_line('RoadSys Sensor IP={}'.format(rs_tcp_hostname), verbose=True)
    print_line('RoadSys Sensor PORT={}'.format(rs_tcp_port), verbose=True)
    print_line('Sensor KeepAlive {} Sec.'.format(rs_comm_keepalive), verbose=True)
    print_line('Count write interval {} Sec.'.format(rs_write_seconds), verbose=True)

if rs_log_packets:
    opt_logging = True
    print_line('Logging enabled by config file', verbose=True)

if rs_log_pkt_fragments:
    opt_log_fragments = True

#
#  LOAD Display layout specs
#
cidValueCount = 0
cidRawFormatSpecs = []
cidFormatIDs = []

# load the CID format specs
default_format_spec = ''
if rs_format_count > 0:
    for suffix in range(rs_format_count):
        keyName = 'cidFormat{}'.format(suffix + 1)
        formatSpec = config['RoadSys'].get(keyName, default_format_spec)
        if len(formatSpec) > 0 and formatSpec.startswith('"Format:'):
            if formatSpec.startswith('"') and formatSpec.endswith('"'):
                formatSpec = formatSpec[1:len(formatSpec)-1]    # remove double-quotes
            cidRawFormatSpecs.append(formatSpec)
            specParts = formatSpec.split(':')
            if len(specParts) > 2:
                specKey = '{}:{}'.format(specParts[1], specParts[2])
                cidFormatIDs.append(specKey)
            else:
                print_line('LOAD ERROR- BAD format spec [{}=] insufficient fields! [{}]()'.format(keyName, formatSpec, len(formatSpec)), error=True)
        else:
            print_line('LOAD ERROR- BAD format spec [{}=]! [{}]()'.format(keyName, formatSpec, len(formatSpec)), error=True)
    if len(cidRawFormatSpecs) != rs_format_count:
        print_line('LOAD ERROR- missing format spec(s)? found {}, wanted {}'.format(len(cidRawFormatSpecs), rs_format_count), error=True)

    for fmtSpec in cidFormatIDs:
        if 'VALUE:' in fmtSpec:
            cidValueCount += 1

    print_line('LOADed cidRawFormatSpecs=[{}]'.format(cidRawFormatSpecs), debug=True)
    print_line('LOADed cidFormatIDs=[{}]'.format(cidFormatIDs), debug=True)


# load the CID value specs
cidDefaultValues = {}
cidRawValueSpecs = []

default_value_spec = ''
if rs_value_count > 0:
    for suffix in range(rs_value_count):
        keyName = 'cidValue{}'.format(suffix + 1)
        valueSpec = config['RoadSys'].get(keyName, default_value_spec)
        if len(valueSpec) > 0 and valueSpec.startswith('"Value:'):
            cidRawValueSpecs.append(valueSpec)
            valueSpec = valueSpec[1:len(valueSpec)-1]    # remove double-quotes
            if '=' in valueSpec:
                valueSpecParts = valueSpec.split('=')
                keyParts = valueSpecParts[0].split(':')
                valueKey = '{}:{}'.format(keyParts[1], keyParts[2])
                # remember our label:message value
                cidDefaultValues[valueKey] = valueSpecParts[1]
        else:
            print_line('LOAD ERROR- BAD value spec [{}=]! [{}]()'.format(keyName, valueSpec, len(valueSpec)), error=True)
    if len(cidDefaultValues) != rs_value_count:
        print_line('LOAD ERROR- missing value spec(s)? found {}, wanted {}'.format(len(cidDefaultValues), rs_value_count), error=True)

    for specKey in cidFormatIDs:
        if 'VALUE:' in specKey:
            # values default to zero
            cidDefaultValues[specKey] = '0'

    print_line('LOADed cidRawValueSpecs=[{}]'.format(cidRawValueSpecs), debug=True)
    print_line('LOADed cidDefaultValues=[{}]'.format(cidDefaultValues), debug=True)


# load the CID sum specs
cidDefaultSums = {}
cidDefaultTotals = {}
cidCountedClasses = []
cidActiveCounters = []
cidAssignedCounters = {}
cidRawSumSpecs = []

def recordCountedClasses(classList):
    for classStr in classList:
        # don't add classes with {} wrap
        if '{' not in classStr and '}' not in classStr:
            # if special class string, force lower case
            if classStr.upper() == "ALL" or classStr.upper() == "OTHER":
                classStr = classStr.lower()
            # if class not in list, add it
            if classStr not in cidCountedClasses:
                cidCountedClasses.append(classStr)


default_sum_spec = ''
if rs_sum_count > 0:
    for suffix in range(rs_sum_count):
        keyName = 'cidSum{}'.format(suffix + 1)
        sumSpec = config['RoadSys'].get(keyName, default_value_spec)
        print_line('LOAD key [{}], found [{}]'.format(keyName, sumSpec), debug=True)
        if len(sumSpec) > 0 and sumSpec.startswith('"Sum:'):
            sumSpec = sumSpec[1:len(sumSpec)-1]    # remove double-quotes
            cidRawSumSpecs.append(sumSpec)
            if '=' in sumSpec:
                sumSpecParts = sumSpec.split('=')
                sumId = sumSpecParts[0][4:]
                keyParts = sumSpecParts[0].split(':')
                bHaveTotal = False
                if '{' in sumSpecParts[1] or '}' in sumSpecParts[1]:
                    bHaveTotal = True
                    classes = sumSpecParts[1].replace('{','').replace('}','').split(',')
                else:
                    classes = sumSpecParts[1].split(',')
                print_line('LOAD raw=[{}], sumId=[{}], classes=[{}]'.format(sumSpecParts, sumId, classes), debug=True)
                # remember our label:message value
                if bHaveTotal:
                    cidDefaultTotals[sumId] = classes
                    ctrName = 'count{}year'.format(len(cidDefaultTotals.keys()))
                    if sumId not in cidActiveCounters:
                        cidActiveCounters.append(sumId)
                        cidAssignedCounters[sumId] = ctrName
                else:
                    cidDefaultSums[sumId] = classes
                    ctrName = 'count{}'.format(len(cidDefaultSums.keys()))
                    if sumId not in cidActiveCounters:
                        cidActiveCounters.append(sumId)
                        cidAssignedCounters[sumId] = ctrName
                        recordCountedClasses(classes)
        else:
            print_line('LOAD ERROR- BAD value spec [{}=]! [{}]()'.format(keyName, sumSpec, len(sumSpec)), error=True)
    if len(cidDefaultSums) + len(cidDefaultTotals) != rs_sum_count:
        print_line('LOAD ERROR- missing value spec(s)? found {}, wanted {}'.format(len(cidDefaultSums), rs_sum_count), error=True)

    print_line('LOADed cidRawSumSpecs=[{}]'.format(cidRawSumSpecs), debug=True)
    print_line('LOADed cidDefaultSums=[{}]'.format(cidDefaultSums), debug=True)
    print_line('LOADed cidDefaultTotals=[{}]'.format(cidDefaultTotals), debug=True)
    print_line('LOADed cidCountedClasses=[{}]'.format(cidCountedClasses), debug=True)
    print_line('LOADed cidActiveCounters=[{}]'.format(cidActiveCounters), debug=True)
    print_line('LOADed cidAssignedCounters=[{}]'.format(cidAssignedCounters), debug=True)


print_line('cidValueCount=({})'.format(cidValueCount), debug=True)
print_line('Display has {} counted values'.format(cidValueCount), verbose=True)

def recordCountedClasses(classList):
    for classStr in classList:
        # don't add classes with {} wrap
        if '{' not in classStr and '}' not in classStr:
            # if class not in list, add it
            if classStr not in cidCountedClasses:
                cidCountedClasses.append(classStr)

def getLogFilename(prefixStr):
    # return log file name based upon current date/time
    dateTimeStr = strftime('%Y%m%d_%H%M', localtime())
    fileName = '{}_{}.log'.format(prefixStr, dateTimeStr)
    return fileName

if opt_logging:
    logFileSpec = "{}/{}".format(folder_log, getLogFilename(project_name.replace('-','').lower()))
    print_line('Logging to [{}]'.format(logFileSpec), info=True)
    cavidlog_fp = open(logFileSpec, "wt")

if opt_log_fragments:
    fragFileSpec = "{}/{}".format(folder_log, getLogFilename(project_name.replace('-','').lower()+"_frag"))
    print_line('Logging fragments to [{}]'.format(fragFileSpec), info=True)
    fraglog_fp = open(fragFileSpec, "wt")

termlog_fp = None
if opt_term_log:
    termLogFileSpec = "{}/{}".format(folder_log, getLogFilename(project_name.replace('-','').lower()+"_term"))
    print_line('Logging terminal commands to [{}]'.format(termLogFileSpec), verbose=True)
    termlog_fp = open(termLogFileSpec, "wt")

# -----------------------------------------------------------------------------
#  methods indentifying RPi host hardware/software
# -----------------------------------------------------------------------------

#  object that provides access to information about the RPi on which we are running
class RPiHostInfo:

    def getDeviceModel(self):
        out = subprocess.Popen("/bin/cat /proc/device-tree/model | /bin/sed -e 's/\\x0//g'",
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
        stdout, _ = out.communicate()
        model_raw = stdout.decode('utf-8')
        # now reduce string length (just more compact, same info)
        model = model_raw.replace('Raspberry ', 'R').replace(
            'i Model ', 'i 1 Model').replace('Rev ', 'r').replace(' Plus ', '+ ')

        print_line('rpi_model_raw=[{}]'.format(model_raw), debug=True)
        print_line('rpi_model=[{}]'.format(model), debug=True)
        return model, model_raw

    def getLinuxRelease(self):
        out = subprocess.Popen("/bin/cat /etc/apt/sources.list | /bin/egrep -v '#' | /usr/bin/awk '{ print $3 }' | /bin/grep . | /usr/bin/sort -u",
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
        stdout, _ = out.communicate()
        linux_release = stdout.decode('utf-8').rstrip()
        print_line('rpi_linux_release=[{}]'.format(linux_release), debug=True)
        return linux_release


    def getLinuxVersion(self):
        out = subprocess.Popen("/bin/uname -r",
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
        stdout, _ = out.communicate()
        linux_version = stdout.decode('utf-8').rstrip()
        print_line('rpi_linux_version=[{}]'.format(linux_version), debug=True)
        return linux_version

    def getHostnames(self):
        out = subprocess.Popen("/bin/hostname -f",
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
        stdout, _ = out.communicate()
        fqdn_raw = stdout.decode('utf-8').rstrip()
        print_line('fqdn_raw=[{}]'.format(fqdn_raw), debug=True)
        lcl_hostname = fqdn_raw
        if '.' in fqdn_raw:
            # have good fqdn
            nameParts = fqdn_raw.split('.')
            lcl_fqdn = fqdn_raw
            tmpHostname = nameParts[0]
        else:
            # missing domain, if we have a fallback apply it
            if len(fallback_domain) > 0:
                lcl_fqdn = '{}.{}'.format(fqdn_raw, fallback_domain)
            else:
                lcl_fqdn = lcl_hostname

        print_line('rpi_fqdn=[{}]'.format(lcl_fqdn), debug=True)
        print_line('rpi_hostname=[{}]'.format(lcl_hostname), debug=True)
        return lcl_hostname, lcl_fqdn

# -----------------------------------------------------------------------------
#  Maintain Runtime Configuration values
# -----------------------------------------------------------------------------

#  object that provides access to gateway runtime confiration data
class RuntimeConfig:
    # (declare class variables here)
    # Host RPi keys
    keyRPiModel = "Model"
    keyRPiMdlFull = "ModelFull"
    keyRPiRel = "OsRelease"
    keyRPiVer = "OsVersion"
    keyRPiName = "Hostname"
    keyRPiFqdn = "FQDN"

    # P2 Hardware/Application keys
    keyP2HwName = "hwName"
    keyP2ObjVer = "objVer"

    # CID Application keys
    keyCidBase1Year = "yearBase1"
    keyCidBase2Year = "YearBase2"
    keyCidCount1 = "resumeCount1"
    keyCidCount2 = "resumeCount2"

    # email keys
    keyEmailTo = "to"
    keyEmailFrom = "fm"
    keyEmailCC = "cc"
    keyEmailBCC = "bc"
    keyEmailSubj = "su"
    keyEmailBody = "bo"

    # sms keys
    keySmsPhone = "phone"
    keySmsMessage = "message"

    configRequiredEmailKeys = [ keyEmailTo, keyEmailSubj, keyEmailBody ]

    configOptionalEmailKeys =[ keyEmailFrom, keyEmailCC, keyEmailBCC ]

    #  searchable list of keys
    configKnownKeys = [ keyCidBase1Year, keyCidBase2Year,
                        keyCidCount1, keyCidCount2,
                        keyP2HwName, keyP2ObjVer,
                        keyRPiModel, keyRPiMdlFull, keyRPiRel, keyRPiVer, keyRPiName, keyRPiFqdn,
                        keyEmailTo, keyEmailFrom, keyEmailCC, keyEmailBCC, keyEmailSubj, keyEmailBody,
                        keySmsPhone, keySmsMessage ]

    # create a new instance
    def __init__(self):
        # (declare instance variables here)
        self.configDictionary = {}   # initially empty

    def haveNeededEmailKeys(self):
        # check if we have a minimum set of email specs to be able to send. Return T/F here T means we can send!
        foundMinimumKeysStatus = True
        for key in self.configRequiredEmailKeys:
            if key not in self.configDictionary.keys():
                foundMinimumKeysStatus = False

        print_line('CONFIG-Dict: have email keys=[{}]'.format(foundMinimumKeysStatus), debug=True)
        return foundMinimumKeysStatus

    def validateKey(self, name):
        # ensure a key we are trying to set/get is expect by this system
        #   generate warning if NOT
        if name not in self.configKnownKeys:
            print_line('CONFIG-Dict: Unexpected key=[{}]!!'.format(name), warning=True)

    def isKeyPresent(self, name):
        # ensure a key we are trying to set/get is expect by this system
        #   generate warning if NOT
        self.validateKey(name)   # warn if key isn't a known key
        bPresentStatus = False
        if name in self.configDictionary.keys():
            bPresentStatus = True
        return bPresentStatus

    def setConfigNamedVarValue(self, name, value):
        # set a config value for name
        self.validateKey(name)   # warn if key isn't a known key
        foundKey = False
        if name in self.configDictionary.keys():
            oldValue = self.configDictionary[name]
            foundKey = True
        self.configDictionary[name] = value
        if foundKey and oldValue != value:
            print_line('CONFIG-Dict: [{}]=[{}]->[{}]'.format(name, oldValue, value), debug=True)
        else:
            print_line('CONFIG-Dict: [{}]=[{}]'.format(name, value), debug=True)

    def getValueForConfigVar(self, name):
        # return a config value for name
        # print_line('CONFIG-Dict: get({})'.format(name), debug=True)
        self.validateKey(name)   # warn if key isn't a known key
        dictValue = ""
        if name in self.configDictionary.keys():
            dictValue = self.configDictionary[name]
            print_line('CONFIG-Dict: [{}]=[{}]'.format(name, dictValue), debug=True)
        else:
            print_line('CONFIG-Dict: [{}] NOT FOUND'.format(name, dictValue), warning=True)
        return dictValue

# -----------------------------------------------------------------------------
#  Maintain our list of file handles requested by the P2
# -----------------------------------------------------------------------------

#  Object used to track gateway files
class FileDetails:
    # (declare class variables here)

    # create a new instance with all details given!
    def __init__(self, fileName, fileMode, dirSpec):
        # (declare instance variables here)
        self.fileName = fileName + '.json'
        self.fileMode = fileMode
        self.dirSpec = dirSpec
        self.fileSpec = os.path.join(self.dirSpec, self.fileName)

# object tracking the gateway files providing access via handles
class FileHandleStore:
    # (declare class variables here)
    def __init__(self):
        # (declare instance variables here)
        self.dctLiveFiles = {}  # runtime hash of known files (not persisted)
        self.dctWatchedFiles = {}  # runtime hash of files being watched (not persisted)
        self.nNextFileId = 1  # initial collId value (1 - 99,999)

    def handleStringForFile(self, fileName, fileMode, dirSpec):
        # create and return a new fileIdKey for this new file and save file details with the key
        #  TODO: detect open-assoc of same file details (only 1 path/filename on file, please)
        fileIdKey = self.nextFileIdKey()
        desiredFileId = int(fileIdKey)
        self.dctLiveFiles[fileIdKey] = FileDetails(fileName, fileMode, dirSpec)
        return desiredFileId

    def handleForFSpec(self, possibleFSpec):
        # create and return a new fileIdKey for this new file and save file details with the key
        #  TODO: detect open-assoc of same file details (only 1 path/filename on file, please)
        desiredFileId = 0
        if len(self.dctLiveFiles.keys()) > 0:
            for fileIdKey in self.dctLiveFiles.keys():
                possibleFileDetails = self.dctLiveFiles[fileIdKey]
                if possibleFileDetails.fileSpec == possibleFSpec:
                    desiredFileId = int(fileIdKey)
                    break   # we have our answer, abort loop
        return desiredFileId

    def addWatchForHandle(self, possibleFileId):
        # record that we are now watching this file!
        fileIdKey = self.keyForFileId(possibleFileId)
        desiredFileDetails = self.dctLiveFiles[fileIdKey]
        self.dctWatchedFiles[fileIdKey] = desiredFileDetails

    def isWatchedFSpec(self, possibleFSpec):
        # return T/F where T means a watch of {possibleFSpec} is requested
        bChangeStatus = False
        if len(self.dctWatchedFiles.keys()) > 0:
            for fileIdKey in self.dctWatchedFiles.keys():
                possibleFileDetails = self.dctWatchedFiles[fileIdKey]
                if possibleFileDetails.fileSpec == possibleFSpec:
                    bChangeStatus = True
                    break   # we have our answer, abort loop
        return bChangeStatus

    def fpsecForHandle(self, possibleFileId):
        # return the fileSpec associated with the given collId
        fileIdKey = self.keyForFileId(possibleFileId)
        desiredFileDetails = self.dctLiveFiles[fileIdKey]
        return desiredFileDetails.fileSpec

    def nextFileIdKey(self):
      # return the next legal collId key [00001 -> 99999]
      fileIdKey = self.keyForFileId(self.nNextFileId)
      if fileIdKey in self.dctLiveFiles.keys():
        print_line('ERROR[Internal] FileHandleStore: attempted re-use of fileIdKey=[{}]'.format(fileIdKey),error=True)
      if(self.nNextFileId < 99999):  # limit to 1-99,999
        self.nNextFileId = self.nNextFileId + 1
      return fileIdKey

    def isValidHandle(self, possibleFileId):
        # return T/F where T means this key represents an actual file
        fileIdKey = self.keyForFileId(possibleFileId)
        validationStatus = True
        if not fileIdKey in self.dctLiveFiles.keys():
            validationStatus = False
        return validationStatus

    def keyForFileId(self, possibleFileId):
        # return file id as 5-char string
        desiredFileIdStr = '{:05d}'.format(int(possibleFileId))
        return desiredFileIdStr

# -----------------------------------------------------------------------------
#  methods for filesystem watching
# -----------------------------------------------------------------------------

# object that does the watching
class FileSystemWatcher:
    # (declare class variables here)

    def __init__(self, folderName):
        # (declare instance variables here)
        self.observer = Observer()
        self.DIRECTORY_TO_WATCH = folderName

    def run(self):
        print_line('Thread: FileSystemWatcher() started', verbose=True)
        event_handler = Handler()
        self.observer.schedule(event_handler, self.DIRECTORY_TO_WATCH, recursive=False)
        self.observer.start()
        try:
            while True:
                sleep(5)
        except Exception as exc:
            self.observer.stop()
            print_line('!!! FileSystemWatcher: Exception: {}'.format(exc), error=True)

        self.observer.join()

# object that takes action based on file/dir changed notifications
class Handler(FileSystemEventHandler):

    @staticmethod
    def on_any_event(event):
        print_line('- FileSystemEventHandler: event=[{}]'.format(event), debug=True)
        if event.is_directory:
            return None

        elif event.event_type == 'created':
            # Take any action here when a file is first created.
            print_line("Received FileCreate event - [{}]".format(event.src_path), debug=True)

        elif event.event_type == 'modified':
            # Taken any action here when a file is modified.
            print_line("Received FileModified event - [{}]".format(event.src_path), debug=True)
            p2ReportFileChanged(event.src_path)


# -----------------------------------------------------------------------------
#  Circular queue for serial input lines & serial/tcp listener
# -----------------------------------------------------------------------------

# object which is a queue of text lines
#  these arrive at a rate different from our handling them rate
#  so we put them in a queue while they wait to be handled
class RxLineQueue:
    # (declare class variables here)

    def __init__(self):
        # (declare instance variables here)
        # our instance variables
        self.lineBuffer = deque()

    def pushLine(self, newLine):
        self.lineBuffer.append(newLine)
        # show debug every 100 lines more added
        if len(self.lineBuffer) % 100 == 0:
            print_line('- lines({})'.format(len(self.lineBuffer)),debug=True)

    def popLine(self):
        oldestLine = ''
        if len(self.lineBuffer) > 0:
            oldestLine = self.lineBuffer.popleft()
        return oldestLine

    def flush(self):
        # empty the que of lines
        self.lineBuffer.clear()

    def lineCount(self):
        return len(self.lineBuffer)


# -----------------------------------------------------------------------------
#  TASK: dedicated P2 serial listener
# -----------------------------------------------------------------------------

def taskSerialP2Listener(serPortP2, rxP2LineQueue):
    print_line('Thread: taskSerialP2Listener() started', verbose=True)
    # process lies from serial or from test file
    if opt_useTestFile == True:
        test_file=open("charlie_rpi_debug.out", "r")
        lines = test_file.readlines()
        for currLine in lines:
            rxP2LineQueue.pushLine(currLine)
            #sleep(0.1)
    else:
        while True:
            if serPortP2.inWaiting() > 0:
                received_data = serPortP2.readline()              # data here, read serial port
                dataLen = len(received_data)
                if dataLen > 0 and dataLen < 512:
                    currLine = received_data.decode('latin-8', 'replace').rstrip()
                    #print_line('TASK-RX line({}=[{}]'.format(len(currLine), currLine), debug=True)
                    if currLine.isascii():
                        print_line('TASK-RX rxD({})=({})'.format(len(currLine),currLine), debug=True)
                        rxP2LineQueue.pushLine(currLine)
                    else:
                        print_line('TASK-RX non-ASCII rxD({})=[{}]'.format(len(received_data), received_data), warning=True)
                else:
                    # wrong size, ignore this...
                    if dataLen > 0:
                        print_line('TASK-RX TOO LONG rxD({})'.format(len(received_data)), warning=True)
            else:
                sleep(0.1)  # wait for more rx data

# -----------------------------------------------------------------------------
#  Email Handler
# -----------------------------------------------------------------------------

newLine = '\n'

def createAndSendEmail(emailTo, emailFrom, emailSubj, emailTextLines):
    # send a email via the selected interface
    print_line('createAndSendEmail to=[{}], from=[{}], subj=[{}], body=[{}]'.format(emailTo, emailFrom, emailSubj, emailTextLines), debug=True)
    #
    # build message footer
    # =================================
    #
    #  --
    #  Sent From: {objName} {objVer}
    #        Via: {daemonName} {daemonVer}
    #       Host: {RPiName} - {osName}, {osVersion}
    # =================================
    footer = '\n\n--\n'
    objName = runtimeConfig.getValueForConfigVar(runtimeConfig.keyP2HwName)
    objVer = runtimeConfig.getValueForConfigVar(runtimeConfig.keyP2ObjVer)
    footer += '  Sent From: {} v{}\n'.format(objName, objVer)
    footer += '        Via: {}\n'.format(script_info)
    footer += '       Host: {} - {}\n'.format(rpi_fqdn, rpi_model)
    footer += '    Running: Kernel v{} ({})\n'.format(rpi_linux_version, rpi_linux_release)
    # format the body text
    body = ''
    for line in emailTextLines:
        body += '{}\n'.format(line)
    # then append our footer
    emailBody = body + footer

    if use_sendgrid:
        #
        # compose our email and send via our SendGrid account
        #  # ,
        sgCli = sendgrid.SendGridAPIClient(sendgrid_api_key)
        newEmail = Mail(from_email = sendgrid_from_addr,
                    to_emails = emailTo,
                    subject = emailSubj,
                    plain_text_content = emailBody)
        response = sgCli.client.mail.send.post(request_body=newEmail.get())

        #  included for debugging purposes
        print_line('SG status_code [{}]'.format(response.status_code), debug=True)
        print_line('SG body [{}]'.format(response.body), debug=True)
        print_line('SG headers [{}]'.format(response.headers), debug=True)
    else:
        #
        # compose our email and send using sendmail directly
        #
        msg = MIMEText(emailBody)  # failed attempt to xlate...
        if len(emailFrom) > 0:
            msg["From"] = emailFrom
        msg["To"] = emailTo
        msg["Subject"] = emailSubj
        mailProcess = Popen(["/usr/sbin/sendmail", "-t", "-oi"], stdin=PIPE)
        # Both Python 2.X and 3.X
        mailProcess.communicate(msg.as_bytes() if sys.version_info >= (3,0) else msg.as_string())


def sendEmailFromConfig():
    # gather email details then create and send a email via the selected interface
    tmpTo =  runtimeConfig.getValueForConfigVar(runtimeConfig.keyEmailTo)
    tmpFrom = runtimeConfig.getValueForConfigVar(runtimeConfig.keyEmailFrom)
    tmpSubject = runtimeConfig.getValueForConfigVar(runtimeConfig.keyEmailSubj)
    tmpBody = runtimeConfig.getValueForConfigVar(runtimeConfig.keyEmailBody)
    # TODO: wire up BCC, CC ensure that multiple, To, Cc, and Bcc work too!
    # print_line('sendEmailFromConfig to=[{}], from=[{}], subj=[{}], body=[{}]'.format(tmpTo, tmpFrom, tmpSubject, tmpBody), debug=True)
    createAndSendEmail(tmpTo, tmpFrom, tmpSubject, tmpBody)

def getNameValuePairs(strRequest, cmdStr):
    # isolate name-value pairs found within {strRequest} (after removing prefix {cmdStr})
    rmdr = strRequest.replace(cmdStr,'')
    nameValuePairs = rmdr.split(parm_sep)
    print_line('getNameValuePairs nameValuePairs({})=({})'.format(len(nameValuePairs), nameValuePairs), debug=True)
    return nameValuePairs

def processNameValuePairs(nameValuePairsAr):
    # parse the name value pairs - return of dictionary of findings
    findingsDict = {}
    for nameValueStr in nameValuePairsAr:
        if '=' in nameValueStr:
            name,value = nameValueStr.split('=', 1)
            print_line(' [{}]=[{}]'.format(name, value), debug=True)
            findingsDict[name] = value
        else:
            print_line('processNameValuePairs nameValueStr({})=({}) ! missing "=" !'.format(len(nameValueStr), nameValueStr), warning=True)
    return findingsDict

# -----------------------------------------------------------------------------
#  CID Communications Object
# -----------------------------------------------------------------------------

# PUBLIC interface values
WRONG_ACK_CHR = 76
NO_ACK_CHR = 77
HANDSHAKE_WRONG = 80
HANDSHAKE_UNRECOGNISED = 81
NO_HANDSHAKE = 82
TRANSMIT_TIMEOUT = 88

ACK = 0x06
NAK = 0x15

SUCCESS = False

#  Object used to track gateway files
class cidComms:
    # (declare class variables here)
    CONNECT_RETRY_COUNT = 5

    MAX_TCP_BUFFER_LEN = 512

    # connecting to our CID sender
    TXD1_SECURITY_CODE = 0xB1
    RXD1_SECURITY_CODE = 0xB2

    EMU3_EQUIPMENT_NUMBER = 10668
    PASSWORD_STR = 'TDCS'
    EMPTY_STR = ''

    FLDIDX_SERIAL_NUMBER = 0
    FLDIDX_CAVID = 1
    FLDIDX_DATE_TIME = 2
    FLDIDX_VALIDITY_CODE = 3
    FLDIDX_DIRECTION = 4
    FLDIDX_LANE = 5
    FLDIDX_TEMPERATURE = 6
    FLDIDX_CLASS_NAME = 7
    FLDIDX_SPEED = 8
    FLDIDX_AXLES = 9
    FLDIDX_CONSTANT = 10
    FLDIDX_STRADDLE = 11
    FLDIDX_HEADWAY = 12
    FLDIDX_LENGTH = 13
    FLDIDX_OVERHANG = 37
    # MIN Check Values
    FLD_MIN_GOOD_INDEX = FLDIDX_OVERHANG
    FLD_MIN_COUNT = FLD_MIN_GOOD_INDEX + 1

    # extra fields no from SIM
    FLDIDX_FRONT_OVERHANG = 38
    FLDIDX_REAR_OVERHANG = 39
    # MAX Check Values
    FLD_MAX_GOOD_INDEX = FLDIDX_REAR_OVERHANG
    FLD_MAX_COUNT = FLD_MAX_GOOD_INDEX + 1

    FLDVAL_DIR_FORWARDS = '0'
    FLDVAL_DIR_REVERSE = '1'

    FLDVAL_ID_CAVID = 'CAVID'

    FLDVAL_CLS_PED = 'PED'
    FLDVAL_CLS_CYCLE = 'CYCLE'
    FLDVAL_CLS_BIKET = 'Bike+T'
    FLDVAL_CLS_M_C = 'M/C'
    FLDVAL_CLS_6N = '6N'
    FLDVAL_CLS_5N = '5N'


    # create a new instance with all details given!
    def __init__(self, tcpIpAddr, tcpPort):
        # (declare instance variables here)
        self.ipAddr = tcpIpAddr
        self.port = tcpPort
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.settimeout(rs_tcp_timeout)    # 40 seconds
        self.tcp_socket.connect((self.ipAddr, self.port))
        self.count1 = 0
        self.count2 = 0
        self.priorCount1 = -1
        self.priorCount2 = -1
        self.rptCount = 0
        self.reportSerial = '0'
        self.priorSerial = '0'
        self.base1Year = 0
        self.base2Year = 0
        self.count1Year = 0
        self.count2Year = 0
        self.priorCount1Year = -1
        self.priorCount2Year = -1
        self.needDayCtrsPersist = False
        self.needYTDCtrsPersist = False
        # track current day and current year
        self.priorDay = datetime.datetime.now().day
        self.priorYear = datetime.datetime.now().year
        # track Rx Interval
        self.receiveDuration = 0
        self.minReceiveDuration = 99999
        self.maxReceiveDuration = -99999
        self.totalReciveWaitTime = 0
        self.countReceiveAttempts = 0
        # track ACK interval
        self.priorSendTime = 0
        self.sendTime = 0
        self.elapsedTimeInSec = 0
        self.minElapsedTimeInSec = 99999
        self.maxElapsedTimeInSec = -99999
        # TCP comms enable
        self.disableTCP = False

    def SendCmd(self, cmdCode):
        status = SUCCESS

        cmdLayout = struct.Struct('!B')
        cmdNetwork = ctypes.create_string_buffer(cmdLayout.size)
        cmdLayout.pack_into(cmdNetwork, 0, cmdCode)
        #print('CMD Packed Value   :', binascii.hexlify(cmdNetwork))
        print_line("CID: SendCmd() Packed Value   : {}".format(binascii.hexlify(cmdNetwork)), debug=True)

        countBytesSent = self.tcp_socket.send(cmdNetwork)
        if countBytesSent != cmdLayout.size:
            print_line("CID: SendData() cmd byte NOT sent!", error=True)
            status = TRANSMIT_TIMEOUT
        return status

    def SendData(self, dataBytes, dataLen):
        status = SUCCESS

        # Calculate checksum
        byteIdx = 0
        CheckSum = 0
        while byteIdx < dataLen:
            CheckSum = CheckSum + dataBytes[byteIdx]
            byteIdx += 1

        # Write data
        #print('Packed Value   :', binascii.hexlify(dataBytes))
        print_line("CID: SendData() Packed Value   : {}".format(binascii.hexlify(dataBytes)), debug=True)
        countBytesSent = self.tcp_socket.send(dataBytes)
        if countBytesSent != dataLen:
            print_line("CID: SendData() not all data bytes sent!", error=True)

        # Write checksum
        checksumLayout = struct.Struct('!h')
        checksumNetwork = ctypes.create_string_buffer(checksumLayout.size)
        checksumLayout.pack_into(checksumNetwork, 0, CheckSum)

        countBytesSent = self.tcp_socket.send(checksumNetwork)
        #print('CKSUM Packed Value   :', binascii.hexlify(checksumNetwork))
        print_line("CID: SendData() Cksum Packed Value   : {}".format(binascii.hexlify(checksumNetwork)), debug=True)
        if countBytesSent != checksumLayout.size:
            print_line("CID: SendData() not all CheckSum bytes sent!", error=True)

        bytesRead = self.tcp_socket.recv(self.MAX_TCP_BUFFER_LEN)
        print_line("CID: SendData() bytesRead      : {}".format(binascii.hexlify(bytesRead)), debug=True)
        if len(bytesRead) == 0:
            status = NO_HANDSHAKE
        elif bytesRead[0] == NAK:
            status = HANDSHAKE_WRONG
        elif bytesRead[0] != ACK:
            status = HANDSHAKE_UNRECOGNISED
        return status

    def GetAck(self, dvcCommand):
        bytesRead = 0
        status = self.SendCmd(dvcCommand)
        if status == SUCCESS:
            bytesRead = self.tcp_socket.recv(self.MAX_TCP_BUFFER_LEN)
            #print('bytesRead      :', binascii.hexlify(bytesRead))
            print_line("CID: GetAck() bytesRead      : {}".format(binascii.hexlify(bytesRead)), debug=True)
            if (len(bytesRead) == 1):
                if (bytesRead[0] == 0xff):
                    status = SUCCESS
                else:
                    status = WRONG_ACK_CHR
            elif (len(bytesRead) == 3):
                if (bytesRead[0] == 0x2b):
                    status = SUCCESS
                else:
                    status = WRONG_ACK_CHR
            else:
                print_line("CID: GetAck() no response, Timedout!", error=True)
                status = NO_ACK_CHR
        return status

    def close(self):
        print_line("Closing socket", verbose=True)
        self.tcp_socket.close()

    # NOTEs from James:
    #  In the data stream, we are interested in Class Name and Direction.
    #  Any Class Name that is not PED consider a BIKE
    #
    #  But, as you and I discussed - for this initial, the end user is just lumping everything together.
    #
    #  Long term, I want Bikes and Peds separated into the two directions and the two classes - essentially four bins.

    # ---------------------------------------------------------- FAILURES ----------------------------------
    # [2022-10-08 16:05:34] - (DBG): CID-poll() csv=[159131,CAVID,2022-10-08 18:05:24.644,0,0,1,50,CYCLE,187,2,N,0,258,997,0,0,0,0,0,0,0,0,0,0,0,798,0,0,0,0,0,0,0,0,0,2022-10-08 18:05:24.276,00,00
    # ]
    # [2022-10-08 16:05:34] - (DBG): CID: trfc columnStrings(38)=[['159131', 'CAVID', '2022-10-08 18:05:24.644', '0', '0', '1', '50', 'CYCLE', '187', '2', 'N', '0', '258', '997', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '0', '798', '0', '0', '0', '0', '0', '0', '0', '0', '0', '2022-10-08 18:05:24.276', '00', '00\r\n\x00']]
    # [2022-10-08 16:05:34] -  value [CYCLE]/[0] -- type:BIKE dir:FWD
    # [2022-10-08 16:05:35] - (DBG): CID-poll() bytesRead      : b'fc0000080a1612051a00000000000000005900'
    # Exception ignored in thread started by: <bound method cidComms.poll of <__main__.cidComms object at 0x110703520>>
    # Traceback (most recent call last):
    #   File "/Users/stephen/Projects/Projects-ExtGit/RS001-cycleInfoDisplay/P2CycleInfoDisplay Support/macOSpythonTest/./cidTEST.py", line 343, in poll
    #     stringData = bytesRead.decode('UTF-8')
    # ---------------------------------------------------------- FAILURES ----------------------------------
    def interpValidity(self, codeStr):
        interpLines = []
        if codeStr != '0':
            byteArray = bytes(codeStr, 'UTF-8')
            bitFlags = 0
            if len(byteArray) > 2:
                bitFlags += (byteArray[2] - 0x30) * 100
            if len(byteArray) > 1:
                bitFlags += (byteArray[1] - 0x30) * 10
            if len(byteArray) > 0:
                bitFlags += (byteArray[0] - 0x30)
            #print_line("bitFlags=(0b{:b})".format(bitFlags), debug=True)

            if (bitFlags & 0x01) != 0:
                interpLines.append('b0 - Vehicle Straddled')
            if (bitFlags & 0x02) != 0:
                interpLines.append('b1 - Reverse Direction')
            if bitFlags & 0x04 != 0:
                interpLines.append('b2 - Vehicle Unclassified')
            if bitFlags & 0x08 != 0:
                interpLines.append('b3 - Speed Greater than 200kph')
            if bitFlags & 0x10 != 0:
                interpLines.append('b4 - Speed less then 5kph')
            if bitFlags & 0x20 != 0:
                interpLines.append('b5 - Gap Less than 5 meters')
            if bitFlags & 0x40 != 0:
                interpLines.append('b6 - Loop Failure')
            if bitFlags & 0x80 != 0:
                interpLines.append('b7 - Change Speed')

        return interpLines

    def interpCode(self, codeStr):
        interpLines = []
        bitArray = bytes(codeStr, 'UTF-8')
        if bitArray[0] == 0x31:
            interpLines.append("b0 - Mains Power Fail")
        if bitArray[1] == 0x31:
            interpLines.append("b1 - Low battery Voltage")
        if bitArray[2] == 0x31:
            interpLines.append("b2 - Modem Comms Error")
        if bitArray[3] == 0x31:
            interpLines.append("b3 - Memory Corruption Error")
        if bitArray[4] == 0x31:
            interpLines.append("b4 - WatchDog Reset")
        if bitArray[5]== 0x31:
            interpLines.append("b5 - Lane CPU Failure")
        if bitArray[6]== 0x31:
            interpLines.append("b6 - Front Door Open")
        if bitArray[7]== 0x31:
            interpLines.append("b7 - Back Door Open")
        if bitArray[8]== 0x31:
            interpLines.append("b8 - Sensor 1 Lane 1 Fault")
        if bitArray[9] == 0x31:
            interpLines.append("b9 - Sensor 2 Lane 1 Fault")
        if bitArray[10] == 0x31:
            interpLines.append("b10 - Sensor 1 Lane 2 Fault")
        if bitArray[11] == 0x31:
            interpLines.append("b11 - Sensor 2 Lane 2 Fault")
        if bitArray[12] == 0x31:
            interpLines.append("b12 - Sensor 1 Lane 3 Fault")
        if bitArray[13] == 0x31:
            interpLines.append("b13 - Sensor 2 Lane 3 Fault")
        if bitArray[14] == 0x31:
            interpLines.append("b14 - Sensor 1 Lane 4 Fault")
        if bitArray[15] == 0x31:
            interpLines.append("b15 - Sensor 2 Lane 4 Fault")
        if bitArray[15] == 0x31:
            interpLines.append("b16 - Sensor 1 Lane 5 Fault")
        if bitArray[17] == 0x31:
            interpLines.append("b17 - Sensor 2 Lane 5 Fault")
        if bitArray[18] == 0x31:
            interpLines.append("b18 - Sensor 1 Lane 6 Fault")
        if bitArray[19] == 0x31:
            interpLines.append("b19 - Sensor 2 Lane 6 Fault")
        if bitArray[20] == 0x31:
            interpLines.append("b20 - Sensor 1 Lane 7 Fault")
        if bitArray[21] == 0x31:
            interpLines.append("b21 - Sensor 2 Lane 7 Fault")
        if bitArray[22] == 0x31:
            interpLines.append("b22 - Sensor 1 Lane 8 Fault")
        if bitArray[23] == 0x31:
            interpLines.append("b23 - Sensor 2 Lane 8 Fault")
        if bitArray[24] == 0x31:
            interpLines.append("b24 - Sensor 3 Lane 1 Fault")
        if bitArray[25] == 0x31:
            interpLines.append("b25 - Sensor 3 Lane 2 Fault")
        if bitArray[26] == 0x31:
            interpLines.append("b26 - Sensor 3 Lane 3 Fault")
        if bitArray[27] == 0x31:
            interpLines.append("b27 - Sensor 3 Lane 4 Fault")
        if bitArray[28] == 0x31:
            interpLines.append("b28 - Sensor 3 Lane 5 Fault")
        if bitArray[29] == 0x31:
            interpLines.append("b29 - Sensor 3 Lane 6 Fault")
        if bitArray[30] == 0x31:
            interpLines.append("b30 - Sensor 3 Lane 7 Fault")
        if bitArray[31] == 0x31:
            interpLines.append("b31 - Sensor 3 Lane 8 Fault")

        return interpLines

    def checkAdjacency(self, priorStr, currentStr, lineNbr, lineAr):
        # trying to locate cause for:
        # ---------------------------------------------------------- FAILURES ----------------------------------
        # [2022-10-08 22:06:36] - Closing socket
        # Traceback (most recent call last):
        #   File "/Users/stephen/Projects/Projects-ExtGit/RS001-cycleInfoDisplay/P2CycleInfoDisplay Support/macOSpythonTest/./cidTEST.py", line 623, in <module>
        #     mainLoop(tcpInputQueue)
        #   File "/Users/stephen/Projects/Projects-ExtGit/RS001-cycleInfoDisplay/P2CycleInfoDisplay Support/macOSpythonTest/./cidTEST.py", line 559, in mainLoop
        #    if int(self.priorSerial) + 1 != int(self.reportSerial) and self.priorSerial != 0:
        # ValueError: invalid literal for int() with base 10: '\x00162047'
        # ---------------------------------------------------------- FAILURES ----------------------------------

        if not priorStr.isascii() or not currentStr.isascii():
            print_line("checkAdjacency() --- BAD VALUE! currSN({}) != priorSN+1({}) ---".format(currentStr, priorStr), error=True)
            print_line("                     BAD VALUE! lineAr(#{})=[{}]".format(lineNbr,lineAr), error=True)
        else:
            bExcepted = False
            try:
                priorNbr = int(priorStr)
            except:
                print_line("       EXCEPTION (pri=[{}])     BAD VALUE! lineAr(#{})=[{}]".format(priorStr, lineNbr,lineAr), error=True)
                bExcepted = True
            try:
                currentNbr = int(currentStr)
            except:
                print_line("       EXCEPTION (cur)     BAD VALUE! lineAr(#{})=[{}]".format(lineNbr,lineAr), error=True)
                bExcepted = True

            if not bExcepted and priorNbr + 1 != currentNbr and priorNbr != 0:
                print_line("checkAdjacency() --- S/N GAP! currSN({}) != priorSN+1({}) ---".format(currentStr, priorStr), error=True)

    # -----------------------------------------------------------------------------
    #  TASK: dedicated CID serial listener
    #   (also sends keep-alive messages)
    # -----------------------------------------------------------------------------
    def taskCidPoll(self, trafficQueue):
        # new strategy, send '1' every 60 secs
        #  just poll for non-zero length rest of time
        print_line("Thread: taskCidPoll() started", verbose=True)
        # send rx code, wait response
        #self.GetAck(RXD1_SECURITY_CODE)
        # now loop sending '1' every 60 seconds while constantly receiving
        newCsvLine = ''
        while True:
            if not self.disableTCP:
                self.sendKeepAlive()
            if not self.disableTCP:
                while True:
                    if self.isTimeForKeepAlive():
                        break
                    try:
                        self.startRx()
                        bytesRead = self.tcp_socket.recv(self.MAX_TCP_BUFFER_LEN)
                    except socket.error as msg:
                        print_line("  -- TIME OUT -- : msg=[{}]".format(msg), warning=True)
                        self.endRx()
                        continue
                    self.endRx()
                    if len(bytesRead) > 0:
                        # if 1st bytes is ascii then decode string
                        if (bytesRead[0] >= 0x07 and bytesRead[0] < 0x80) or bytesRead[0] == 0x00:
                            logTcpFragment("CID-poll() bytesRead      : {}".format(binascii.hexlify(bytesRead)))
                            stringData = bytesRead.decode('UTF-8')
                            logTcpFragment("CID-poll() text           : [{}]".format(stringData))
                            # append our next incoming bytes
                            newCsvLine = '{}{}'.format(newCsvLine, stringData)
                            # if we have EOL then post new line to our incoming QUEUE
                            if '\r\n' in newCsvLine:
                                # huh, we actually have a case where tail of 1st line and head of 2nd line arrived in same packet
                                firstCRLF = newCsvLine.find('\r\n')
                                lastCRLF = newCsvLine.rfind('\r\n')
                                # while we still have more than one CRLF in buffer, do:
                                while firstCRLF != -1 and lastCRLF != -1 and firstCRLF != lastCRLF:
                                    # process prefix to 1st CRLF as line
                                    newCsv = newCsvLine[:firstCRLF]
                                    self.reportNewCsv(newCsv, trafficQueue)
                                    # leave rest of line in buffer (skipping CRLF)
                                    newCsvLine = newCsvLine[firstCRLF+2:]
                                    # see if we have two more...
                                    firstCRLF = newCsvLine.find('\r\n')
                                    lastCRLF = newCsvLine.rfind('\r\n')

                                if firstCRLF != -1 and firstCRLF == lastCRLF:
                                    # process single CRLF
                                    # prefix to CRLF is new line
                                    newCsv = newCsvLine[:firstCRLF]
                                    self.reportNewCsv(newCsv, trafficQueue)
                                    # let's see how much is left...
                                    suffixCRLF = newCsvLine[firstCRLF:].rstrip('\x00').rstrip()
                                    if len(suffixCRLF) == 0:
                                        # whole prefix is our line
                                        newCsvLine = '' # empty our receiver
                                    else:
                                        # have crlf in midst of line, prior to prefix to CRLF should be processed, leave rest in buffer
                                        # leave rest of line in buffer (skipping CRLF)
                                        newCsvLine = newCsvLine[firstCRLF+2:]
                                else:
                                    print_line("firstCRLF={}".format(firstCRLF), debug=True)
                                    print_line("lastCRLF={}".format(lastCRLF), debug=True)
                                    print_line("ERROR: bug in code, shouldn't get here!".format(), error=True)

                        elif bytesRead[0] == 0xff:
                            # if first byte is ACK, ignore it...
                            logTcpFragment("CID-poll() bytesRead      : {}".format(binascii.hexlify(bytesRead)))
                        else:
                            # we don't know what this packet is!!!
                            logTcpFragment("CID-poll()   ??BAD??      : {}".format(binascii.hexlify(bytesRead)), error=True)
            else:
                sleep(0.2)  # nothing to do wait a bit... (tcp is disabled)

    def reportNewCsv(self, newCSVline, trafficQueue):
        if len(newCSVline) > 0:
            logTcpFragment("CID-poll() csv=[{}]".format(newCSVline))
            trafficQueue.pushLine(newCSVline)
            if opt_logging:
                cavidlog_fp.write('{}\n'.format(newCSVline))
                cavidlog_fp.flush()

    def sendKeepAlive(self):
        self.priorSendTime = self.sendTime
        self.sendTime = time.time()
        commStatus = self.SendCmd(0x31)
        if self.priorSendTime != 0:
            self.elapsedTimeInSec =  self.sendTime - self.priorSendTime
            if self.elapsedTimeInSec < self.minElapsedTimeInSec:
                self.minElapsedTimeInSec = self.elapsedTimeInSec
            if self.elapsedTimeInSec > self.maxElapsedTimeInSec:
                self.maxElapsedTimeInSec = self.elapsedTimeInSec
            print_line("- since last keep-alive: {:0.1f} sec [min:{:0.1f} - max:{:0.1f}]".format(self.elapsedTimeInSec, self.minElapsedTimeInSec, self.maxElapsedTimeInSec), debug=True)
            print_line("-         comm stats Rx: {:0.1f} sec x {} [min:{:0.1f} - max:{:0.1f}]".format(self.totalReciveWaitTime / self.countReceiveAttempts, self.countReceiveAttempts, self.minReceiveDuration, self.maxReceiveDuration), debug=True)

    def isTimeForKeepAlive(self):
        elapsedTimeInSec = time.time() - self.sendTime
        #print_line("- elapsed {:0.1f} sec".format(elapsedTimeInSec), debug=True)
        # if going to be more than rs_comm_keepalive seconds since last "I'm listening" message then send it again...
        bPollStatus = False
        if elapsedTimeInSec + rs_tcp_timeout >= rs_comm_keepalive:
            bPollStatus = True
        return bPollStatus

    def startRx(self):
        self.receiveStart = time.time()

    def endRx(self):
        self.receiveDuration = time.time() - self.receiveStart
        self.totalReciveWaitTime += self.receiveDuration
        self.countReceiveAttempts += 1
        if self.receiveDuration < self.minReceiveDuration:
            self.minReceiveDuration = self.receiveDuration
        if self.receiveDuration > self.maxReceiveDuration:
            self.maxReceiveDuration = self.receiveDuration

    def haveUpdates(self):
        # return T/F where T means we have a new PED or BIKE count to be reported
        bHaveStatus = False
        if self.dayCount1Updated() or self.dayCount2Updated() or self.yearCount1Updated() or self.yearCount2Updated():
            bHaveStatus = True
        if self.dayCountsNeedPersist() or self.yearBaseValuesNeedPersist():
            bHaveStatus = True
        return bHaveStatus

    def dayCount1(self):
        # return count of pedestrians seen so far
        currCount = self.count1
        self.priorCount1 = self.count1
        return currCount

    def dayCount2(self):
        # return count of bikes seen so far
        currCount = self.count2
        self.priorCount2 = self.count2
        return currCount

    def dayCounts(self):
        # return both current count values
        return self.count1, self.count2

    def presetDayCount1(self, newCountStr):
        # preload count 1
        priorValue = self.count1
        self.count1 = int(newCountStr)
        if priorValue != self.count1:
            print_line("count1 ({}) -> ({})".format(priorValue, self.count1), debug=True)
        else:
            print_line("count1 ({})".format(self.count1), debug=True)
        self.count1Year = self.base1Year + self.count1

    def presetDayCount2(self, newCountStr):
        # preload count 2
        priorValue = self.count2
        self.count2 = int(newCountStr)
        if priorValue != self.count2:
            print_line("count2 ({}) -> ({})".format(priorValue, self.count2), debug=True)
        else:
            print_line("count2 ({})".format(self.count2), debug=True)
        self.count2Year = self.base2Year + self.count2

    def dayCount1Updated(self):
        # return T/F where T means we have a new PED count to be reported
        bUpdatedStatus = False
        if self.priorCount1 != self.count1:
            bUpdatedStatus = True
        return bUpdatedStatus

    def dayCount2Updated(self):
        # return T/F where T means we have a new BIKE count to be reported
        bUpdatedStatus = False
        if self.priorCount2 != self.count2:
            bUpdatedStatus = True
        return bUpdatedStatus

    def dayCountsNeedPersist(self):
        return self.needDayCtrsPersist

    def yearBaseValuesNeedPersist(self):
        return self.needYTDCtrsPersist

    def clearDayCountsNeedPersist(self):
        self.needDayCtrsPersist = False

    def clearYearBaseValuesNeedPersist(self):
        self.needYTDCtrsPersist = False

    def yearCount1(self):
        # return count of pedestrians seen so far
        currCount = self.count1Year
        self.priorCount1Year = self.count1Year
        return currCount

    def yearCount2(self):
        # return count of bikes seen so far
        currCount = self.count2Year
        self.priorCount2Year = self.count2Year
        return currCount

    def yearCount1Updated(self):
        # return T/F where T means we have a new PED count to be reported
        bUpdatedStatus = False
        if self.priorCount1Year != self.count1Year:
            bUpdatedStatus = True
        return bUpdatedStatus

    def yearCount2Updated(self):
        # return T/F where T means we have a new BIKE count to be reported
        bUpdatedStatus = False
        if self.priorCount2Year != self.count2Year:
            bUpdatedStatus = True
        return bUpdatedStatus

    def baseYearCount1(self):
        # return base year count of pedestrians
        return self.base1Year

    def baseYearCount2(self):
        # return base year count of bikes
        return self.base2Year

    def resetCounters(self):
        # reset the counters, continue counting
        #   today counts
        self.count1 = 0
        self.count2 = 0
        #   year counts
        self.count1Year = self.base1Year
        self.count2Year = self.base2Year
        # reset prior counts, too
        self.priorCount1 = -1
        self.priorCount2 = -1
        self.priorCount1Year = -1
        self.priorCount2Year = -1

    def resetYearBases(self):
        # reset the counters, continue counting
        #   YTD Base counts at year end/start
        self.base1Year = 0
        self.base2Year = 0

    def setBase1Year(self, yearStr):
        priorValue = self.base1Year
        self.base1Year = int(yearStr)
        if priorValue != self.base1Year:
            print_line("base1Year ({}) -> ({})".format(priorValue, self.base1Year), debug=True)
        else:
            print_line("base1Year ({})".format(self.base1Year), debug=True)
        self.count1Year = self.base1Year + self.count1
        self.priorCount1Year = -1

    def setBase2Year(self, yearStr):
        priorValue = self.base2Year
        self.base2Year = int(yearStr)
        if priorValue != self.base2Year:
            print_line("base2Year ({}) -> ({})".format(priorValue, self.base2Year), debug=True)
        else:
            print_line("base2Year ({})".format(self.base2Year), debug=True)
        self.count2Year = self.base2Year + self.count2
        self.priorCount2Year = -1

    def dayChanged(self):
        bChangedStatus = False
        today = datetime.datetime.now().day
        if today != self.priorDay:
            bChangedStatus = True
            self.priorDay = today
        return bChangedStatus

    def yearChanged(self):
        bChangedStatus = False
        thisYear = datetime.datetime.now().year
        if thisYear != self.priorYear:
            bChangedStatus = True
            self.priorYear = thisYear
        return bChangedStatus

    def stop(self):
        # stop all TCP comms
        self.disableTCP = True

    def resume(self):
        # stop all TCP comms
        self.disableTCP = False

    def addToNamedCounter(self, ctrName, amount):
        bUpdatedCounter = True
        if ctrName.endswith('1'):
            self.count1 += amount
        elif ctrName.endswith('2'):
            self.count2 += amount
        elif ctrName.endswith('1year'):
            self.count1Year += amount
        elif ctrName.endswith('2year'):
            self.count2Year += amount
        else:
            bUpdatedCounter = False
        return bUpdatedCounter

    def handleTraffic(self, trafficQueue):
        # if we have sensor traffic process it into our counts
        while True:             # Event Loop
            if self.disableTCP:
                trafficQueue.flush()
            currLine = trafficQueue.popLine()
            if len(currLine) > 0:
                if ',CAVID,' in currLine:
                    columnStrings = currLine.split(',')
                    bGoodContent = len(columnStrings) >=  self.FLD_MIN_GOOD_INDEX and columnStrings[self.FLDIDX_CAVID] == self.FLDVAL_ID_CAVID
                    if not bGoodContent:
                        logTcpFragment("CID: trfc columnStrings({})=[{}]".format(len(columnStrings), columnStrings), error=True)
                    else:
                        if opt_show_tcp:
                            if len(columnStrings) != self.FLD_MIN_COUNT:
                                logTcpFragment("CID: trfc columnStrings({})=[{}]".format(len(columnStrings), columnStrings))
                            else:
                                logTcpFragment("CID: trfc columnStrings({})=[{}]".format(len(columnStrings), columnStrings), warning=True)
                        else:
                            # if odd field count (!38), show line...
                            if len(columnStrings) != self.FLD_MIN_COUNT:
                                logTcpFragment("CID: trfc columnStrings({})=[{}]".format(len(columnStrings), columnStrings), warning=True)

                    if bGoodContent:
                        self.priorSerial = self.reportSerial
                        self.reportSerial = columnStrings[self.FLDIDX_SERIAL_NUMBER]
                        self.checkAdjacency(self.priorSerial, self.reportSerial, self.rptCount, columnStrings)

                        validityCode = columnStrings[self.FLDIDX_VALIDITY_CODE]
                        laneValue = columnStrings[self.FLDIDX_LANE]
                        lengthValue = columnStrings[self.FLDIDX_LENGTH]
                        dirValue = columnStrings[self.FLDIDX_DIRECTION]
                        speedValue = columnStrings[self.FLDIDX_SPEED]
                        speedMPH = int(speedValue) / 1.609
                        headwayValue = columnStrings[self.FLDIDX_HEADWAY]
                        headwayValue = '{}00'.format(headwayValue)  # fake multiply by 100
                        headwaySec = int(headwayValue) / 1000
                        dirStr = '{unk}'
                        if dirValue == self.FLDVAL_DIR_FORWARDS:
                            dirStr = 'FWD'
                        if dirValue == self.FLDVAL_DIR_REVERSE:
                            dirStr = 'REV'
                        className = columnStrings[self.FLDIDX_CLASS_NAME]
                        countClass(className, validityCode)

                        classInterp = 'other'
                        if className == self.FLDVAL_CLS_CYCLE or className == self.FLDVAL_CLS_BIKET:
                            classInterp = 'BIKE'
                        elif className == self.FLDVAL_CLS_PED:
                            classInterp = 'PED'

                        # (meters to feet)
                        lenValueFt = int(lengthValue) / 30.48
                        print_line("#{}({}) value [{}]/[{}] -- type:{} dir:{}".format(self.rptCount, self.reportSerial, className, dirValue, classInterp, dirStr), verbose=True)
                        print_line("                  -- xtra --   lane:[{}] len:[{} cm / {:0.1f} ft], speed {} kph ({:.1f} mph), headway {:.1f} Sec, valid=[{}]".format(laneValue, lengthValue, lenValueFt, speedValue, speedMPH, headwaySec, validityCode), verbose=True)
                        interpLines = self.interpValidity(validityCode)
                        if len(interpLines) > 0:
                            for msg in interpLines:
                                print_line("                 --  {}".format(msg), verbose=True)

                        if self.dayChanged():
                            # add ending value to year base
                            cnt1Value, cnt2Value = self.dayCounts()
                            newBaseYrStr = '{}'.format(self.base1Year + cnt1Value)
                            self.setBase1Year(newBaseYrStr)
                            newBaseYrStr = '{}'.format(self.base2Year + cnt2Value)
                            self.setBase2Year(newBaseYrStr)
                            #  persist new year bases too
                            self.needYTDCtrsPersist = True

                            # zero our day counter(s)
                            self.resetCounters()
                            #  persist this day value too
                            self.needDayCtrsPersist = True

                        if self.yearChanged():
                            # zero our YTD counter(s)
                            self.resetYearBases()
                            #  persist new year bases too
                            self.needYTDCtrsPersist = True

                        # now update our counts
                        # if we want to count this one
                        if className in cidCountedClasses or 'all' in cidCountedClasses or 'other' in cidCountedClasses:
                            # for each sum are are tracking
                            summedValueId = ''
                            for valueId in cidDefaultSums.keys():
                                countedSet = cidDefaultSums[valueId]
                                # if class is counted in sum, add 1 to sum
                                if className in countedSet or 'all' in countedSet:
                                    summedValueId = valueId
                                    # idenitify counter we should increment
                                    desiredCounter = ''
                                    if valueId in cidAssignedCounters.keys():
                                        desiredCounter = cidAssignedCounters[valueId]
                                        bUpdatedCounter = self.addToNamedCounter(desiredCounter, 1)
                                        if bUpdatedCounter:
                                            print_line("  {} [{}] {} += {}".format(valueId, className, desiredCounter, 1), verbose=True)
                            # if value is also counted in a total add 1 to total
                            for totalValueId in cidDefaultTotals.keys():
                                countedSet = cidDefaultTotals[totalValueId]
                                if summedValueId in countedSet:
                                    desiredCounter = ''
                                    if totalValueId in cidAssignedCounters.keys():
                                        desiredCounter = cidAssignedCounters[totalValueId]
                                        bUpdatedCounter = self.addToNamedCounter(desiredCounter, 1)
                                        if bUpdatedCounter:
                                            print_line("  {} [{}] {} += {}".format(totalValueId, className, desiredCounter, 1), verbose=True)

                        # count this line
                        self.rptCount += 1
                elif 'CODE' in currLine:
                    # have diagnostic code
                    lineParts = currLine.split(',')
                    timestamp = lineParts[0].replace('CODE ','')
                    code = lineParts[1]
                    print_line("CID: trfc CODE ({}): [{}]({})".format(timestamp, code, len(code)), verbose=True)
                    interpLines = self.interpCode(code)
                    for msg in interpLines:
                        print_line("                 --  {}".format(msg), verbose=True)
                else:
                    print_line("CID: trfc ???=[{}]".format(currLine), warning=True)
            else:
                # queue emptied let's quit
                break   # exit our handling loop


classesDict = {}

def countClass(classNameStr, validityCodeStr):
    global classesDict
    instanceCount = 1
    if classNameStr in classesDict.keys():
        instanceCount = classesDict[classNameStr]
        instanceCount += 1
    classesDict[classNameStr] = instanceCount

def logTcpFragment(logMessage, error=False, warning=False):
    if opt_log_fragments:
        fraglog_fp.write('{}\n'.format(logMessage))
        fraglog_fp.flush()
    if opt_show_tcp:
        if not error and not warning:
            print_line(logMessage, debug=True)
        elif warning:
            print_line(logMessage, warning=True)
    if error:
        print_line(logMessage, error=True)

def logTermCmdRsp(logMessage):
    if opt_term_log and len(logMessage) > 0:
        timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
        termlog_fp.write('[{}] {}\n'.format(timestamp, logMessage))
        termlog_fp.flush()

# -----------------------------------------------------------------------------
#  Main loop
# -----------------------------------------------------------------------------
# commands from P2
cmdIdentifyHW  = "ident:"
cmdSendEmail = "email-send:"
cmdSendSMS = "sms-send:"
cmdFileAccess = "file-access:"
cmdFileWrite = "file-write:"
cmdFileRead = "file-read:"
cmdListFolder = "folder-list:"
cmdListKeys = "key-list:"
cmdTestSerial = "test:"
# new for CID
cmdDeviceReady  = "dvc-rdy:"
cmdFormatAccepted = "fmt-ok:"
cmdValueAccepted = "val-ok:"

# serial test named parameters
keyTestReset = "reset"  # T/F where T means start count at zero
keyTestMsg = "msg"  # T/F where T means start count at zero

testSerialParmKeys = [ keyTestReset, keyTestMsg ]

# file-access named parameters
keyFileAccDir = "dir"
keyFileAccMode = "mode"
keyFileAccFName = "cname"
fileAccessParmKeys = [ keyFileAccDir, keyFileAccMode, keyFileAccFName ]

# file-write, read named parameters
keyFileFileID = "cid"
keyFileVarNm = "key"
keyFileVarVal = "val"
fileWriteParmKeys = [ keyFileFileID, keyFileVarNm, keyFileVarVal ]
fileReadParmKeys = [ keyFileFileID, keyFileVarNm ]

# folder list named parameters
folderListParmKeys = [ keyFileAccDir ]
keyListParmKeys = [ keyFileFileID ]

# global state parameter for building email
gatheringEmailBody = False
emailBodyTextAr = []
serTestTxCount = 0
serTestRxCount = 0
serTestErrCount = 0


# -----------------------------------------------------------------------------
#  P2 <->CID Startup Sequencer
# -----------------------------------------------------------------------------

p2StartPrefix = "P2-rdy"
p2StartAckPrefix = "P2-StartAck"

def p2ProcessStartupRequest(newLine, serPortP2):

    # in    <-- "P2-rdy"
    # out   --> "fRpi-rdy"
    # in    <-- "P2-StartAck"
    # out   --> "fRpi-StartAck"
    bStartupStatus = False
    print_line('Startup line({})=[{}]'.format(len(newLine), newLine), debug=True)

    if newLine.startswith(p2StartPrefix):
        print_line('* HANDLE P2 Start', verbose=True)
        p2SendValidationSuccess(serPortP2, "fRpi-rdy", "", "")

    elif newLine.startswith(p2StartAckPrefix):
        print_line('* HANDLE P2 Start', verbose=True)
        p2SendValidationSuccess(serPortP2, "fRpi-StartAck", "", "")
        bStartupStatus = True
    else:
        print_line('* LINE IGNORED during startup...[{}]'.format(newLine), warning=True)

    return bStartupStatus


# -----------------------------------------------------------------------------
#  CID Cycle INfo Display Setup
# -----------------------------------------------------------------------------

# CID formats
#  NOTE: lines are 1-n
#     Instance Numbers are 1-n
#

cidFormatSendIdx = 0
cidValuesSendIdx = 0


# -----------------------------------------------------------------------------
#  CID P2 Communication interface (listener on 1st serial port)
# -----------------------------------------------------------------------------

def p2ProcessIncomingRequest(newLine, serPortP2):
    global gatheringEmailBody
    global emailBodyTextAr
    global serTestTxCount
    global serTestRxCount
    global serTestErrCount
    global cidFormatSendIdx
    global wakeInProgress

    if "-bad:" in newLine:
        print_line('Incoming line({})=[{}]'.format(len(newLine), newLine), error=True)
        #elif "-ok:" in newLine:
        #print_line('Incoming line({})=[{}]'.format(len(newLine), newLine), info=True)
    else:
        print_line('Incoming line({})=[{}]'.format(len(newLine), newLine), debug=True)

    if newLine.startswith(body_end):
        gatheringEmailBody = False
        print_line('Incoming emailBodyTextAr({})=[{}]'.format(len(emailBodyTextAr), emailBodyTextAr), debug=True)
        runtimeConfig.setConfigNamedVarValue(runtimeConfig.keyEmailBody, emailBodyTextAr)
        # Send the email if we know enough to do so...
        if runtimeConfig.haveNeededEmailKeys() == True:
            sendEmailFromConfig()
            p2SendValidationSuccess(serPortP2, "email", "", "")

    elif gatheringEmailBody == True:
        bodyLinesAr = newLine.split('\\n')
        print_line('bodyLinesAr({})=[{}]'.format(len(bodyLinesAr), bodyLinesAr), debug=True)
        emailBodyTextAr += bodyLinesAr

    elif newLine.startswith(p2StartPrefix):
        wakeInProgress = True
        p2ProcessStartupRequest(newLine, serPortP2)

    elif newLine.startswith(body_start):
        gatheringEmailBody = True
        emailBodyTextAr = []

    elif newLine.startswith(cmdIdentifyHW):
        print_line('* HANDLE id P2 Hardware', verbose=True)
        nameValuePairs = getNameValuePairs(newLine, cmdIdentifyHW)
        if len(nameValuePairs) > 0:
            findingsDict = processNameValuePairs(nameValuePairs)
            # Record the hardware info for later use
            if len(findingsDict) > 0:
                p2ProcDict = {}
                for key in findingsDict:
                    runtimeConfig.setConfigNamedVarValue(key, findingsDict[key])
                    p2ProcDict[key] = findingsDict[key]
                # now write to our P2 Proc file as well
                p2Name = runtimeConfig.getValueForConfigVar(runtimeConfig.keyP2HwName).replace(' - ', '-').replace(' ', '-')
                procFspec = os.path.join(folder_proc, 'P2-{}.json'.format(p2Name))
                writeJsonFile(procFspec, p2ProcDict)
                #print_line('p2ProcDict[{}]'.format(p2ProcDict), error=True)
                p2SendValidationSuccess(serPortP2, "fident", "", "")
            else:
                print_line('p2ProcessIncomingRequest nameValueStr({})=({}) ! missing hardware keys !'.format(len(newLine), newLine), warning=True)

    elif newLine.startswith(cmdDeviceReady):
        print_line('* HANDLE Device Ready', verbose=True)
        p2SendValidationSuccess(serPortP2, "fdvc-rdy", "", "")
        # now send first from our display list
        p2SendCidDisplayList(serPortP2, startFromTop=True)

    elif newLine.startswith(cmdFormatAccepted):
        # now send next from our display list
        if cidFormatSendIdx < len(cidRawFormatSpecs):
            p2SendCidDisplayList(serPortP2)
        else:
            # now send first from our display values list
            p2SendCidDisplayValuesList(serPortP2, startFromTop=True)

    elif newLine.startswith(cmdValueAccepted):
        # now send next from our display values list
        p2SendCidDisplayValuesList(serPortP2)

    elif newLine.startswith(cmdTestSerial):
        print_line('* HANDLE id P2 Hardware', verbose=True)
        nameValuePairs = getNameValuePairs(newLine, cmdTestSerial)
        if len(nameValuePairs) > 0:
            findingsDict = processNameValuePairs(nameValuePairs)
            if len(findingsDict) > 0:
                # validate all keys exist
                bHaveAllKeys = True
                missingParmName = ''
                for requiredKey in testSerialParmKeys:
                    if requiredKey not in findingsDict.keys():
                        HaveAllKeys = False
                        missingParmName = requiredKey
                        break
                if not bHaveAllKeys:
                    errorTxt = 'missing folder-list named parameter [{}]'.format(missingParmName)
                    p2SendValidationError(serPortP2, "stest", errorTxt)
                else:
                    # validate reset and take action
                    shouldReset = findingsDict[keyTestReset]
                    if shouldReset.lower() != 'true' and shouldReset.lower() != 'false':
                        errorTxt = 'Invalid [{}] value [{}]'.format(missingParmName, shouldReset)
                        p2SendValidationError(serPortP2, "stest", errorTxt)
                    else:
                        if shouldReset.lower() == 'true':
                            serTestRxCount = 0
                            serTestTxCount = 0
                            serTestErrCount = 0
                        rxStr = findingsDict[keyTestMsg]
                        compRxStr = p2GenNextRxString(serTestRxCount)
                        serTestRxCount += 1
                        print_line('TEST: rx=[{}] == [{}] ??'.format(rxStr, compRxStr), debug=True)
                        if rxStr != compRxStr:
                            serTestErrCount += 1
                        compTxStr = p2GenNextTxString(serTestTxCount)
                        serTestTxCount += 1
                        checkMsg = '{}{}msg={}'.format(serTestErrCount, parm_sep, compTxStr)
                        p2SendValidationSuccess(serPortP2, "stest", "ct", checkMsg)

    elif newLine.startswith(cmdListFolder):
        print_line('* HANDLE list collections', verbose=True)
        nameValuePairs = getNameValuePairs(newLine, cmdListFolder)
        if len(nameValuePairs) > 0:
            findingsDict = processNameValuePairs(nameValuePairs)
            if len(findingsDict) > 0:
                # validate all keys exist
                bHaveAllKeys = True
                missingParmName = ''
                for requiredKey in folderListParmKeys:
                    if requiredKey not in findingsDict.keys():
                        HaveAllKeys = False
                        missingParmName = requiredKey
                        break
                if not bHaveAllKeys:
                    errorTxt = 'missing folder-list named parameter [{}]'.format(missingParmName)
                    p2SendValidationError(serPortP2, "folist", errorTxt)
                else:
                    # validate dirID is valid Enum number
                    dirID = int(findingsDict[keyFileAccDir])
                    if dirID not in FolderId._value2member_map_:    # in list of valid Enum numbers?
                        errorTxt = 'bad parm dir={} - unknown folder ID'.format(dirID)
                        p2SendValidationError(serPortP2, "folist", errorTxt)
                    else:
                        # good request now list all files in dir
                        dirSpec = folderSpecByFolderId[FolderId(dirID)]
                        filesAr = os.listdir(dirSpec)
                        print_line('p2ProcessIncomingRequest filesAr({})=({})'.format(len(filesAr), filesAr), debug=True)
                        fileBaseNamesAr = []
                        fnameLst = ''
                        fnameCt = len(filesAr)
                        resultStr = ''
                        if fnameCt > 0:
                            # have 1 or more files
                            for filename in filesAr:
                                if '.json' in filename:
                                    fbasename = filename.replace('.json','')
                                    fileBaseNamesAr.append(fbasename)
                            fnameLst = ','.join(fileBaseNamesAr)
                            resultStr = '{}{}names={}'.format(fnameCt, parm_sep, fnameLst)
                        else:
                            # have NO files in dir
                            resultStr = '{}'.format(fnameCt)
                        p2SendValidationSuccess(serPortP2, "folist", "ct", resultStr)
        else:
            print_line('p2ProcessIncomingRequest nameValueStr({})=({}) ! missing list files params !'.format(len(newLine), newLine), warning=True)

    elif newLine.startswith(cmdListKeys):
        print_line('* HANDLE list keys in collection', verbose=True)
        nameValuePairs = getNameValuePairs(newLine, cmdListKeys)
        if len(nameValuePairs) > 0:
            findingsDict = processNameValuePairs(nameValuePairs)
            if len(findingsDict) > 0:
                # validate all keys exist
                bHaveAllKeys = True
                missingParmName = ''
                for requiredKey in keyListParmKeys:
                    if requiredKey not in findingsDict.keys():
                        HaveAllKeys = False
                        missingParmName = requiredKey
                        break
                if not bHaveAllKeys:
                    errorTxt = 'missing keys-list named parameter [{}]'.format(missingParmName)
                    p2SendValidationError(serPortP2, "kylist", errorTxt)
                else:
                    # validate dirID is valid Enum number
                    fileIdStr = findingsDict[keyFileFileID]
                    if not fileHandles.isValidHandle(fileIdStr):
                        errorTxt = 'BAD file handle [{}]'.format(fileIdStr)
                        p2SendValidationError(serPortP2, "kylist", errorTxt)
                    else:
                        fspec = fileHandles.fpsecForHandle(fileIdStr)
                        # good request now list all keys in collection
                        filesize = os.path.getsize(fspec)
                        fileDict = {}   # start empty
                        keysAr = []
                        if filesize > 0:    # if we have existing content, preload it
                            with open(fspec, "r") as read_file:
                                fileDict = json.load(read_file)
                                keysAr = fileDict.keys()
                        print_line('p2ProcessIncomingRequest keysAr({})=({})'.format(len(keysAr), keysAr), debug=True)
                        fileBaseNamesAr = []
                        keyNameLst = ''
                        keyCt = len(keysAr)
                        resultStr = ''
                        if keyCt > 0:
                            # have 1 or more files
                            keyNameLst = ','.join(keysAr)
                            resultStr = '{}{}names={}'.format(keyCt, parm_sep, keyNameLst)
                        else:
                            # have NO files in dir
                            resultStr = '{}'.format(keyCt)
                        p2SendValidationSuccess(serPortP2, "kylist", "ct", resultStr)
        else:
            print_line('p2ProcessIncomingRequest nameValueStr({})=({}) ! missing list files params !'.format(len(newLine), newLine), warning=True)

    elif newLine.startswith(cmdSendEmail):
        print_line('* HANDLE send email', verbose=True)
        nameValuePairs = getNameValuePairs(newLine, cmdSendEmail)
        if len(nameValuePairs) > 0:
            findingsDict = processNameValuePairs(nameValuePairs)
            if len(findingsDict) > 0:
                for key in findingsDict:
                    runtimeConfig.setConfigNamedVarValue(key, findingsDict[key])
            else:
                print_line('p2ProcessIncomingRequest nameValueStr({})=({}) ! missing email params !'.format(len(newLine), newLine), warning=True)

    elif newLine.startswith(cmdSendSMS):
        print_line('* HANDLE send SMS', verbose=True)
        nameValuePairs = getNameValuePairs(newLine, cmdSendSMS)
        if len(nameValuePairs) > 0:
            findingsDict = processNameValuePairs(nameValuePairs)
            if len(findingsDict) > 0:
                for key in findingsDict:
                    runtimeConfig.setConfigNamedVarValue(key, findingsDict[key])
            else:
                print_line('p2ProcessIncomingRequest nameValueStr({})=({}) ! missing SMS params !'.format(len(newLine), newLine), warning=True)
            # TODO: now send the SMS

    elif newLine.startswith(cmdFileWrite):
        print_line('* HANDLE File WRITE', verbose=True)
        nameValuePairs = getNameValuePairs(newLine, cmdFileWrite)
        if len(nameValuePairs) > 0:
            findingsDict = processNameValuePairs(nameValuePairs)
            if len(findingsDict) > 0:
                # validate all keys exist
                bHaveAllKeys = True
                missingParmName = ''
                for requiredKey in fileWriteParmKeys:
                    if requiredKey not in findingsDict.keys():
                        HaveAllKeys = False
                        missingParmName = requiredKey
                        break
                if not bHaveAllKeys:
                    errorTxt = 'missing file-write named parameter [{}]'.format(missingParmName)
                    p2SendValidationError(serPortP2, "fwrite", errorTxt)
                else:
                    fileIdStr = findingsDict[keyFileFileID]
                    if not fileHandles.isValidHandle(fileIdStr):
                        errorTxt = 'BAD write file handle [{}]'.format(fileIdStr)
                        p2SendValidationError(serPortP2, "fwrite", errorTxt)
                    else:
                        fspec = fileHandles.fpsecForHandle(fileIdStr)
                        varKey = findingsDict[keyFileVarNm]
                        varValue = findingsDict[keyFileVarVal]
                        # load json file
                        filesize = os.path.getsize(fspec)
                        fileDict = {}   # start empty
                        if filesize > 0:    # if we have existing content, preload it
                            with open(fspec, "r") as read_file:
                                fileDict = json.load(read_file)
                        # replace key-value pair (or add it)
                        fileDict[varKey] = varValue
                        # write the file
                        writeJsonFile(fspec, fileDict)
                        # report our operation success to P2 (status only)
                        p2SendValidationSuccess(serPortP2, "fwrite", "", "")
            else:
                print_line('p2ProcessIncomingRequest nameValueStr({})=({}) ! missing file-write params !'.format(len(newLine), newLine), warning=True)
            # TODO: now write the file

    elif newLine.startswith(cmdFileRead):
        print_line('* HANDLE File READ', verbose=True)
        nameValuePairs = getNameValuePairs(newLine, cmdFileRead)
        if len(nameValuePairs) > 0:
            findingsDict = processNameValuePairs(nameValuePairs)
            if len(findingsDict) > 0:
                # validate all keys exist
                bHaveAllKeys = True
                missingParmName = ''
                for requiredKey in fileReadParmKeys:
                    if requiredKey not in findingsDict.keys():
                        HaveAllKeys = False
                        missingParmName = requiredKey
                        break
                if not bHaveAllKeys:
                    errorTxt = 'missing file-read named parameter [{}]'.format(missingParmName)
                    p2SendValidationError(serPortP2, "fread", errorTxt)
                else:
                    fileIdStr = findingsDict[keyFileFileID]
                    if not fileHandles.isValidHandle(fileIdStr):
                        errorTxt = 'BAD file handle [{}]'.format(fileIdStr)
                        p2SendValidationError(serPortP2, "fread", errorTxt)
                    else:
                        fspec = fileHandles.fpsecForHandle(fileIdStr)
                        varKey = findingsDict[keyFileVarNm]
                        # load json file
                        with open(fspec, "r") as read_file:
                            fileDict = json.load(read_file)
                        if not varKey in fileDict.keys():
                            errorTxt = 'BAD Key - Key not found [{}]'.format(varKey)
                            p2SendValidationError(serPortP2, "fread", errorTxt)
                        else:
                            desiredValue = fileDict[varKey]
                            # report our operation success to P2 (and send value read from file)
                            p2SendValidationSuccess(serPortP2, "fread", "varVal", desiredValue)
            else:
                print_line('p2ProcessIncomingRequest nameValueStr({})=({}) ! missing file-read params !'.format(len(newLine), newLine), warning=True)
            # TODO: now read from the file

    elif newLine.startswith(cmdFileAccess):
        print_line('* HANDLE File Open-equiv', verbose=True)
        bNeedFileWatch = False
        nameValuePairs = getNameValuePairs(newLine, cmdFileAccess)
        if len(nameValuePairs) > 0:
            findingsDict = processNameValuePairs(nameValuePairs)
            if len(findingsDict) > 0:
                # validate all keys exist
                bHaveAllKeys = True
                missingParmName = ''
                for requiredKey in fileAccessParmKeys:
                    if requiredKey not in findingsDict.keys():
                        HaveAllKeys = False
                        missingParmName = requiredKey
                        break
                if not bHaveAllKeys:
                    errorTxt = 'missing named parameter [{}]'.format(missingParmName)
                    p2SendValidationError(serPortP2, "faccess", errorTxt)
                else:
                    # validate dirID is valid Enum number
                    dirID = int(findingsDict[keyFileAccDir])
                    if dirID not in FolderId._value2member_map_:    # in list of valid Enum numbers?
                        errorTxt = 'bad parm dir={} - unknown folder ID'.format(dirID)
                        p2SendValidationError(serPortP2, "faccess", errorTxt)
                    else:
                        # validate modeId is valid Enum number
                        modeId = int(findingsDict[keyFileAccMode])
                        if modeId not in FileMode._value2member_map_:    # in list of valid Enum numbers?
                            errorTxt = 'bad parm mode={} - unknown file-mode ID'.format(modeId)
                            p2SendValidationError(serPortP2, "faccess", errorTxt)
                        else:
                            dirSpec = folderSpecByFolderId[FolderId(dirID)]
                            filename = findingsDict[keyFileAccFName]
                            filespec = os.path.join(dirSpec, filename + '.json')
                            bCanAccessStatus = True
                            # if file should exist ensure it does, report if not
                            if FileMode(modeId) == FileMode.FM_READONLY or FileMode(modeId) == FileMode.FM_WRITE:
                                # P2 wants to access read/write an existing file
                                # determine if filename exists in dir
                                if not os.path.exists(filespec):
                                    # if it doesn't exist report the error!
                                    print_line('ERROR file named=[{}] not found fspec=[{}]'.format(filename, filespec), debug=True)
                                    errorTxt = 'bad fname={} - file NOT found'.format(filename)
                                    p2SendValidationError(serPortP2, "faccess", errorTxt)
                                    bCanAccessStatus = False
                            elif FileMode(modeId) == FileMode.FM_WRITE_CREATE:
                                # P2 will write to file, so create empty if doesn't exist
                                if not os.path.exists(filespec):
                                    # let's create the file
                                    print_line('* create empty file [{}]'.format(filespec), verbose=True)
                                    open(filespec, 'a').close() # equiv to touch(1)
                            elif FileMode(modeId) == FileMode.FM_LISTEN:
                                # P2 wants to be notified of content changes to this file!
                                # first, warn if this is not in control DIR!
                                if FolderId(dirID) != FolderId.EFI_CONTROL:
                                    print_line('ERROR attempt to watch file named=[{}] not in /control/ folder. Folder=[{}]'.format(filename, FolderId(dirID)), error=True)
                                    errorTxt = 'bad fname={} not in /control/! folder={}'.format(filename, FolderId(dirID))
                                    p2SendValidationError(serPortP2, "faccess", errorTxt)
                                    bCanAccessStatus = False
                                else:
                                    # Register need to report changes!
                                    bNeedFileWatch = True
                            if bCanAccessStatus == True:
                                # return findings as response
                                newFileIdStr = fileHandles.handleStringForFile(filename, FileMode(modeId), dirSpec)
                                if bNeedFileWatch:
                                    # activate our file watching!
                                    fileHandles.addWatchForHandle(newFileIdStr)
                                p2SendValidationSuccess(serPortP2, "faccess", "collId", newFileIdStr)
            else:
                print_line('p2ProcessIncomingRequest nameValueStr({})=[{}] ! missing FileAccess params !'.format(len(newLine), newLine), warning=True)
    else:
        print_line('ERROR: line({})=[{}] ! P2 LINE NOT Recognized !'.format(len(newLine), newLine), error=True)

def writeJsonFile(outFSpec, dataDict):
    # format the json data and write to file
    with open(outFSpec, "w") as jsonfile_fp:
        json.dump(dataDict, jsonfile_fp, indent = 4, sort_keys=True)
        # append a final newline
        jsonfile_fp.write("\n")

def readJsonFile(inFSpec):
    # read the json file returning the data
    jsonArrayOrDict = {}
    if os.path.exists(inFSpec):
        with open(inFSpec) as jsonfile_fp:
            jsonArrayOrDict = json.load(jsonfile_fp)
    else:
        print_line('readJsonFile() file [{}]: not found!'.format(inFSpec), error=True)
    return jsonArrayOrDict

def loadCidConfig(cidJsonFspec):
    # load runtimeConfig CID values from .json file
    tmpCidConfigDict = {}  # empty
    if os.path.exists(cidJsonFspec):
        tmpCidConfigDict = readJsonFile(cidJsonFspec)
    print_line('* load: tmpCidConfigDict=[{}]'.format(tmpCidConfigDict), debug=True)
    if len(tmpCidConfigDict) > 0:
        for key in tmpCidConfigDict.keys():
            value = tmpCidConfigDict[key]
            runtimeConfig.setConfigNamedVarValue(key, value)
    return tmpCidConfigDict

def saveCidConfig(cidJsonFspec):
    # save runtimeConfig CID values to .json file
    tmpCidConfigDict = {}
    if runtimeConfig.isKeyPresent(runtimeConfig.keyCidBase1Year):
        base1Year = runtimeConfig.getValueForConfigVar(runtimeConfig.keyCidBase1Year)
        tmpCidConfigDict[runtimeConfig.keyCidBase1Year] = base1Year
    if runtimeConfig.isKeyPresent(runtimeConfig.keyCidBase2Year):
        base2Year = runtimeConfig.getValueForConfigVar(runtimeConfig.keyCidBase2Year)
        tmpCidConfigDict[runtimeConfig.keyCidBase2Year] = base2Year
    if runtimeConfig.isKeyPresent(runtimeConfig.keyCidCount1):
        countValue1 = runtimeConfig.getValueForConfigVar(runtimeConfig.keyCidCount1)
        tmpCidConfigDict[runtimeConfig.keyCidCount1] = countValue1
    if runtimeConfig.isKeyPresent(runtimeConfig.keyCidCount2):
        countValue2 = runtimeConfig.getValueForConfigVar(runtimeConfig.keyCidCount2)
        tmpCidConfigDict[runtimeConfig.keyCidCount2] = countValue2
    print_line('* save: tmpCidConfigDict=[{}]'.format(tmpCidConfigDict), debug=True)
    if len(tmpCidConfigDict) > 0:
        # write config file if 1 or more keys
        writeJsonFile(cidJsonFspec, tmpCidConfigDict)
    else:
        # remove file is no keys in it
        os.remove(cidJsonFspec)

def p2SendValidationError(serPortP2, cmdPrefixStr, errorMessage):
    # format and send an error message via outgoing serial
    successStatus = False
    responseStr = '{}:status={}{}msg={}\n'.format(cmdPrefixStr, successStatus, parm_sep, errorMessage)
    newOutLine = responseStr.encode('utf-8')
    print_line('p2SendValidationError line({})=[{}]'.format(len(newOutLine), newOutLine), error=True)
    serPortP2.write(newOutLine)
    sleep(0.1)  # pause 1/10ths of second

def p2SendValidationSuccess(serPortP2, cmdPrefixStr, returnKeyStr, returnValueStr):
    # format and send an error message via outgoing serial
    successStatus = True
    if(len(returnKeyStr) > 0):
        # if we have a key we're sending along an extra KV pair
        responseStr = '{}:status={}{}{}={}\n'.format(cmdPrefixStr, successStatus, parm_sep, returnKeyStr, returnValueStr)
    else:
        # no key so just send final status
        responseStr = '{}:status={}\n'.format(cmdPrefixStr, successStatus)
    newOutLine = responseStr.encode('utf-8')
    print_line('p2SendValidationSuccess line({})=({})'.format(len(newOutLine), newOutLine), verbose=True)
    serPortP2.write(newOutLine)
    sleep(0.1)  # pause 1/10ths of second

def p2SendVariableChanged(serPortP2, varName, varValue, collId):
        # format and send an error message via outgoing serial
    responseStr = 'ctrl:{}={}{}collId={}\n'.format(varName, varValue, parm_sep, collId)
    newOutLine = responseStr.encode('utf-8')
    print_line('p2SendVariableChanged line({})=[{}]'.format(len(newOutLine), newOutLine), verbose=True)
    serPortP2.write(newOutLine)
    sleep(0.1)  # pause 1/10ths of second

def p2GenNextRxString(countValue):
    # format expected RX message for comparison use
    desiredFileIdStr = 'P2TestMsg#{:05d}'.format(int(countValue))
    return desiredFileIdStr

def p2GenNextTxString(countValue):
    # generate expected TX message to send
    desiredFileIdStr = 'RPiTestMsg#{:05d}'.format(int(countValue))
    return desiredFileIdStr

wakeInProgress = True

def p2ProcessInput(serPortP2, rxP2LineQueue):
    "Process P2 requests until queue empty"
    global wakeInProgress
    #print_line('* p2ProcessInput()', debug=True)
    while True:             # get Loop (if something, get another)
        # process an incoming line - creates our windows as needed
        currLine = rxP2LineQueue.popLine()
        if len(currLine) > 0:
            if wakeInProgress:
                bStarted = p2ProcessStartupRequest(currLine, serPortP2)
                if bStarted:
                    wakeInProgress = False
            else:
                p2ProcessIncomingRequest(currLine, serPortP2)
        else:
            break

def p2GenSomeOutput(serPortP2):
    newOutLine = b'Hello p2\n'
    print_line('p2GenSomeOutput line({})=({})'.format(len(newOutLine), newOutLine), debug=True)
    serPortP2.write(newOutLine)
    sleep(0.1)  # pause 1/10ths of second

def p2SendCidDisplayList(serPortP2, startFromTop=False):
    global cidFormatSendIdx
    if startFromTop:
        cidFormatSendIdx = 0
    if cidFormatSendIdx < len(cidRawFormatSpecs):
        messageStr = 'ctrl:{}\n'.format(cidRawFormatSpecs[cidFormatSendIdx])
        newOutLine = messageStr.encode('utf-8')
        print_line('p2SendCidDisplayList line({})=[{}]'.format(len(newOutLine), newOutLine), debug=True)
        cidFormatSendIdx += 1
        serPortP2.write(newOutLine)
        sleep(0.1)  # pause 1/10ths of second

priorTimeStr = ''

def getCurrTime():
    global priorTimeStr
    out = subprocess.Popen("/usr/bin/date +'%T'",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    timeStr = stdout.decode('utf-8').rstrip().replace(':','-')
    if priorTimeStr != timeStr:
        print_line('getCurrTime() time({})=[{}]'.format(len(timeStr), timeStr), debug=True)
        priorTimeStr = timeStr
    return timeStr

def p2SendCidDisplayValuesList(serPortP2, startFromTop=False):
    global cidValuesSendIdx
    bGoodValue = True
    if startFromTop:
        cidValuesSendIdx = 0
    if cidValuesSendIdx < len(cidFormatIDs):
        currKey = cidFormatIDs[cidValuesSendIdx]
        if 'TIME' in currKey:
            # get time, but don't send until the second changes
            #  (poor man's time sync)
            priorTime = valueStr = getCurrTime()
            while valueStr == priorTime:
                valueStr = getCurrTime()
            # second changed, now send it
        elif currKey in cidDefaultValues.keys():
            valueStr = cidDefaultValues[currKey]
        else: # other
            valueStr = "???"
            bGoodValue = False

        if bGoodValue:
            p2SendCidDisplayValue(serPortP2, currKey, valueStr)

        cidValuesSendIdx += 1

def p2SendCidDisplayValue(serPortP2, keyNameStr, valueStr):
    messageStr = 'ctrl:Value:{}:{}\n'.format(keyNameStr, valueStr)
    newOutLine = messageStr.encode('utf-8')
    serPortP2.write(newOutLine)
    sleep(0.1)  # pause 1/10ths of second
    print_line('p2SendCidDisplayValue line({})=[{}]'.format(len(newOutLine), newOutLine), debug=True)

def p2SendCidDisplayTestValue(serPortP2, valueStr):
    messageStr = 'ctrl:Display={}\n'.format(valueStr)
    newOutLine = messageStr.encode('utf-8')
    serPortP2.write(newOutLine)
    sleep(0.1)  # pause 1/10ths of second
    print_line('p2SendCidDisplayTestValue line({})=[{}]'.format(len(newOutLine), newOutLine), debug=True)

# -----------------------------------------------------------------------------
#  Main loop
# -----------------------------------------------------------------------------

# and allocate our single runtime config store
runtimeConfig = RuntimeConfig()

# and allocate our single runtime config store
fileHandles = FileHandleStore()

# alocate our access to our Host Info
rpiHost = RPiHostInfo()

rpi_model, rpi_model_raw = rpiHost.getDeviceModel()
rpi_linux_release = rpiHost.getLinuxRelease()
rpi_linux_version = rpiHost.getLinuxVersion()
rpi_hostname, rpi_fqdn = rpiHost.getHostnames()

# Write our RPi proc file
dictHostInfo = {}
dictHostInfo['Model'] = rpi_model
dictHostInfo['ModelFull'] = rpi_model_raw
dictHostInfo['OsRelease'] = rpi_linux_release
dictHostInfo['OsVersion'] = rpi_linux_version
dictHostInfo['Hostname'] = rpi_hostname
dictHostInfo['FQDN'] = rpi_fqdn

procFspec = os.path.join(folder_proc, 'rpiHostInfo.json')
writeJsonFile(procFspec, dictHostInfo)

# record RPi into to runtimeConfig
runtimeConfig.setConfigNamedVarValue(runtimeConfig.keyRPiModel, rpi_model)
runtimeConfig.setConfigNamedVarValue(runtimeConfig.keyRPiMdlFull, rpi_model_raw)
runtimeConfig.setConfigNamedVarValue(runtimeConfig.keyRPiRel, rpi_linux_release)
runtimeConfig.setConfigNamedVarValue(runtimeConfig.keyRPiVer, rpi_linux_version)
runtimeConfig.setConfigNamedVarValue(runtimeConfig.keyRPiName, rpi_hostname)
runtimeConfig.setConfigNamedVarValue(runtimeConfig.keyRPiFqdn, rpi_fqdn)

# let's ensure we have all needed directories

for dirSpec in folderSpecByFolderId.values():
    if not os.path.isdir(dirSpec):
        os.mkdir(dirSpec)
        if not os.path.isdir(dirSpec):
            print_line('WARNING: dir [{}] NOT found!'.format(dirSpec), warning=True)
            print_line('ERROR: Failed to create Dir [{}]!'.format(dirSpec), warning=True)
        else:
            print_line('Dir [{}] created!'.format(dirSpec), verbose=True)
    else:
        print_line('Dir [{}] - OK'.format(dirSpec), debug=True)


def p2ReportFileChanged(fSpec):
    # If file is of interest, Load json file and send vars to P2
    collId = fileHandles.handleForFSpec(fSpec);
    if fileHandles.isWatchedFSpec(fSpec) == False:
         print_line('CHK File [{}] is NOT watched'.format(fSpec), debug=True)
    else:
        print_line('CHK File [{}] is watched'.format(fSpec), debug=True)
        # load json file
        filesize = os.path.getsize(fSpec)
        fileDict = {}   # start empty
        if filesize > 0:    # if we have existing content, preload it
            with open(fSpec, "r") as read_file:
                fileAr = json.load(read_file)
                fileDict = fileAr[0]    # PHP puts dict in array!?
                for varName in fileDict.keys():
                    varValue = fileDict[varName]
                    print_line('Control [{}] = [{}]'.format(varName, varValue), debug=True)
                    # send var to P2
                    p2SendVariableChanged(serialPortP2, varName, varValue, collId)

# -----------------------------------------------------------------------------
#  TASK: dedicated Linux Command interface serial listener
# -----------------------------------------------------------------------------

def taskSerialCmdListener(serPortCmd, rxCmdLineQueue):
    print_line('Thread: taskSerialCmdListener({}) started'.format(serPortCmd.name), verbose=True)
    # process lies from serial or from test file
    lineSoFar = ''
    while True:
        # Check if incoming bytes are waiting to be read from the serial input  buffer.
        if serPortCmd.inWaiting() > 0:
            received_data = serPortCmd.readline()              # data here, read serial port
            dataLen = len(received_data)
            if dataLen > 0 and dataLen < 512:
                #print_line("cmd-poll() : data({})[{}]".format(dataLen, binascii.hexlify(received_data)), error=True)
                currLine = received_data.decode('latin-8', 'replace')
                if currLine.isascii():
                    lineSoFar = '{}{}'.format(lineSoFar, currLine)
                    #print_line('TASK-cmdRX lineSoFar({})=({})'.format(len(lineSoFar),lineSoFar), debug=True)
                    if '\n' in lineSoFar or '\r' in lineSoFar:
                        newLine = lineSoFar.rstrip('\r\n')
                        print_line('TASK-cmdRX rxD({})=({})'.format(len(newLine),newLine), debug=True)
                        rxCmdLineQueue.pushLine(newLine)
                        lineSoFar = ''
                else:
                    print_line('TASK-cmdRX non-ASCII rxD({})=[{}]'.format(len(received_data), received_data), warning=True)
            else:
                # wrong size, ignore this...
                if dataLen > 0:
                    print_line('TASK-cmdRX TOO LONG rxD({})'.format(len(received_data)), warning=True)
        else:
            sleep(0.1)  # wait for more rx data

# -----------------------------------------------------------------------------
#  Linux Command interface (listener on 2nd serial port)
# -----------------------------------------------------------------------------

cmdTestPanel  = "test"
cmdClearNRun  = "clear"
cmdSetBase    = "base"
cmdStop       = "stop"
cmdRun        = "run"
cmdHelp       = "help"
cmdVersions   = "ver"
cmdClasses    = "class"

patIsDecimal = None


def cmdValidateInput(serPortCmd, rxCmdLineQueue):
    global patIsDecimal
    if patIsDecimal == None:
        # compiling the pattern for alphanumeric string
        patIsDecimal = re.compile(r"^[0-9]+$")
    newLine = rxCmdLineQueue.popLine()
    if len(newLine) > 0:
        print_line('* cmdValInp() cmd({})=[{}]'.format(len(newLine), newLine), debug=True)
        bValidCmd = True
        bNeedHelpText = False
        bSendCmdHelp = False
        bNeedClassList = False
        bNeedBaseCountsText = False
        cmdStr = newLine.lower()
        bNeedVersionText = False
        p2Command = ''
        if newLine.lower() == cmdClearNRun:
            # reset counters, continue running
            bValidCmd = True   # dumb but need something here
        elif newLine.lower() == cmdClasses:
            # reset counters, continue running
            bNeedClassList = True   # show list of classes heard from sensor
            bValidCmd = True   # dumb but need something here
        elif newLine.startswith(cmdTestPanel):
            # stop, reset counters, requst reload, run
            lineParts = newLine.split(' ')
            bNeedCmdHelp = False
            if len(lineParts) == 2:
                cmdStr = lineParts[0].lower()
                if lineParts[1].lower() == 'red':
                    p2Command = 'red'
                elif lineParts[1].lower() == 'grn' or lineParts[1].lower() == 'green':
                    p2Command = 'green'
                elif lineParts[1].lower() == 'blu' or lineParts[1].lower() == 'blue':
                    p2Command = 'blue'
                elif lineParts[1].lower() == 'wht' or lineParts[1].lower() == 'white':
                    p2Command = 'white'
                elif lineParts[1].lower() == 'loop':
                    p2Command = 'loop'
                elif lineParts[1].lower() == 'stop':
                    p2Command = 'stop'
                else:
                    cmdSendResponse(serPortCmd, "ERROR: invalid parameter: [{}]".format(lineParts[1]))
                    bNeedCmdHelp = True
            else:
                cmdSendResponse(serPortCmd, "ERROR: missing/extra parameter(s): [{}]".format(newLine))
                bNeedCmdHelp = True

            if bNeedCmdHelp:
                bValidCmd = False
                cmdSendResponse(serPortCmd, "  test [red|grn|blu|wht|loop|stop] - full panel of [color], loop on colors, or stop test display")
                cmdSendResponse(serPortCmd, "") # blank line

        elif newLine.startswith(cmdSetBase):
            # set year to new value
            # base[1|2] nnnnn
            lineParts = newLine.split(' ')
            bNeedCmdHelp = False
            if len(lineParts) == 1:
                cmdStr = newLine.lower()
                p2Command = ''
                bNeedBaseCountsText = True
            elif len(lineParts) == 2:
                cmdStr = lineParts[0].lower()
                if lineParts[0].lower() == 'base1':
                    p2Command = lineParts[0].lower()
                elif lineParts[0].lower() == 'base2':
                    p2Command = lineParts[0].lower()
                else:
                    cmdSendResponse(serPortCmd, "ERROR: invalid parameter: [{}]".format(lineParts[1]))
                    bNeedCmdHelp = True
                # do further validation, is lineParts[2] decimal string...
                if re.fullmatch(patIsDecimal, lineParts[1]):
                    p2Command = '{} {}'.format(p2Command, lineParts[1])
                else:
                    cmdSendResponse(serPortCmd, "ERROR: invalid parameter (must be decimal number): [{}]".format(lineParts[1]))
                    bNeedCmdHelp = True
            else:
                cmdSendResponse(serPortCmd, "ERROR: missing/extra parameter(s): [{}]".format(newLine))
                bNeedCmdHelp = True

            if bNeedCmdHelp:
                bValidCmd = False
                cmdSendResponse(serPortCmd, "  base[1|2] nnnnn - Set base1/base2 year start-value")
                cmdSendResponse(serPortCmd, "") # blank line
                p2Command = ''

        elif newLine.lower() == cmdVersions:
            # show our RPi and P2 installed software/firmware versions
            bNeedVersionText = True
        elif newLine.lower() == cmdStop:
            # stop, temporarily halt TCP comms
            bValidCmd = True   # dumb but need something here
        elif newLine.lower() == cmdRun:
            # run/resume, restart TCP comms
            bValidCmd = True   # dumb but need something here
        elif newLine.lower() == cmdHelp:
            bNeedHelpText = True
            bValidCmd = True   # dumb but need something here
        else:
            bValidCmd = False

        if bValidCmd:
            if opt_term_log:
                logTermCmdRsp(newLine)  # log response
            cmdSendResponse(serPortCmd, "ok")
        else:
            print_line('ERROR: cmd({})=[{}] ! Command LINE NOT Recognized !'.format(len(newLine), newLine), error=True)
            bValidCmd = False
            cmdSendResponse(serPortCmd, "ERROR: Unknown Command: [{}]".format(newLine))
            cmdSendResponse(serPortCmd, " (enter help<ret> for list of commands)".format(newLine))
            cmdSendResponse(serPortCmd, "") # blank line

        if bNeedHelpText:
            cmdSendResponse(serPortCmd, "") # blank line
            cmdSendResponse(serPortCmd, "Supported Commands:")
            cmdSendResponse(serPortCmd, "  base  - Display base1,base2 year start-values")
            cmdSendResponse(serPortCmd, "  base[1|2] nnnnn - Set base1/base2 year start-value")
            cmdSendResponse(serPortCmd, "  clear - Reset counters to zero/yearly start value")
            cmdSendResponse(serPortCmd, "  class - List device classes reported by the sensor")
            cmdSendResponse(serPortCmd, "  help  - Show this help text")
            cmdSendResponse(serPortCmd, "  run   - Resume updating counts, interacting with sensor")
            cmdSendResponse(serPortCmd, "  stop  - Stop updating counts, interacting with sensor")
            cmdSendResponse(serPortCmd, "  test [red|grn|blu|wht|loop|stop] - Full panel of [color], loop on colors, or stop test display")
            cmdSendResponse(serPortCmd, "  ver   - Display version of firmware on P2 and software on RPi")
            cmdSendResponse(serPortCmd, "") # blank line

        if bNeedBaseCountsText:
            cmdSendResponse(serPortCmd, "") # blank line
            yearBase1Count = 0
            if runtimeConfig.isKeyPresent(runtimeConfig.keyCidBase1Year):
                yearBase1Count = runtimeConfig.getValueForConfigVar(runtimeConfig.keyCidBase1Year)
            yearBase2Count = 0
            if runtimeConfig.isKeyPresent(runtimeConfig.keyCidBase2Year):
                yearBase2Count = runtimeConfig.getValueForConfigVar(runtimeConfig.keyCidBase2Year)
            if yearBase1Count != 0 or yearBase2Count != 0:
                cmdSendResponse(serPortCmd, "Base Values:")
                if cidValueCount == 2:
                    cmdSendResponse(serPortCmd, " -  Base1 Year base ({})".format(yearBase1Count))
                else:
                    cmdSendResponse(serPortCmd, " -  Base1 Year base ({})".format(yearBase1Count))
                    cmdSendResponse(serPortCmd, " -  Base2 Year base ({})".format(yearBase2Count))
            else:
                cmdSendResponse(serPortCmd, " -  (Count(s) not set!)")
            cmdSendResponse(serPortCmd, "") # blank line

        if bNeedVersionText:
            cmdSendResponse(serPortCmd, "") # blank line
            cmdSendResponse(serPortCmd, "Versions:")
            cmdSendResponse(serPortCmd, " - RPi: {}".format(script_info))
            objName = runtimeConfig.getValueForConfigVar(runtimeConfig.keyP2HwName)
            objVer = runtimeConfig.getValueForConfigVar(runtimeConfig.keyP2ObjVer)
            if len(objName) == 0 or len(objVer) == 0:
                cmdSendResponse(serPortCmd, " -  P2: {} v{}".format('???', '???'))
            else:
                cmdSendResponse(serPortCmd, " -  P2: {} v{}".format(objName, objVer))
            cmdSendResponse(serPortCmd, "") # blank line

        if bNeedClassList:
            cmdSendResponse(serPortCmd, "") # blank line
            cmdSendResponse(serPortCmd, "Classes Seen:")
            if len(classesDict) > 0:
                for key in sorted(classesDict.keys()):
                    currCount = classesDict[key]
                    cmdSendResponse(serPortCmd, " -  {} x {}".format(currCount, key))
            else:
                cmdSendResponse(serPortCmd, " - (none, yet)") # blank line
            cmdSendResponse(serPortCmd, "") # blank line

        print_line(' - return: bValidCmd=[{}],  cmdStr=[{}],  p2Command=[{}]'.format(bValidCmd, cmdStr, p2Command), debug=True)
        return bValidCmd, cmdStr, p2Command

def cmdSendResponse(serPortCmd, responseMsg):
    # format and send an error message via outgoing serial
    responseStr = '{}\r\n'.format(responseMsg)
    newOutLine = responseStr.encode('utf-8')
    print_line('cmdSendResponse line({})=({})'.format(len(newOutLine), newOutLine), verbose=True)
    serPortCmd.write(newOutLine)
    if opt_term_log:
        logTermCmdRsp(responseMsg)  # log response


def validateFormatSpecs(formatSpecList):
    #  Format:TIME:1:color=ORANGE,line=1,alignment=CENTER"
    #  Format:MESSAGE:1:color=GREEN,line=2,alignment=SCROLLING-LEFT"
    #  Format:LABEL:1:color=YELLOW,line=4,alignment=LEFT"
    #  Format:VALUE:1:color=YELLOW,line=4,alignment=RIGHT,padWidth=4,padType=left-spaces"
    #  Format:LABEL:2:color=YELLOW,line=5,alignment=LEFT"
    #  Format:VALUE:2:color=YELLOW,line=5,alignment=RIGHT,padWidth=6,padType=left-spaces"
    #  Format:MESSAGE:2:color=ORANGE,line=7,alignment=CENTER"
    validTypes = ['TIME', 'MESSAGE', 'LABEL', 'VALUE']
    validArgNames = ['color', 'line', 'alignment']
    validValueArgNames = ['color', 'line', 'alignment', 'padWidth', 'padType']
    validLtRtAlignmentTypes = ['LEFT', 'RIGHT']
    validLRCAlignmentTypes = ['LEFT', 'CENTER', 'RIGHT']
    validAlignmentTypes = ['LEFT', 'CENTER', 'RIGHT', 'SCROLLING-LEFT', 'SCROLLING-RIGHT', 'SCROLLING-UP', 'SCROLLING-DOWN']
    validPadTypes = ['LEFT-SPACES', 'RIGHT-SPACES', 'LEFT-ZEROS', 'RIGHT-ZEROS']
    validColors = ['BLACK', 'RED', 'GREEN', 'BLUE', 'YELLOW', 'CYAN', 'MAGENTA', 'WHITE', 'ORANGE', 'RAINBOW']
    keysFound = []
    specErrors = []
    bFoundError = False
    for formatSpec in formatSpecList:
        specErrors = [] # start empty
        bFoundSpecError = False
        specParts = formatSpec.split(":")
        # must lead with Format:
        if specParts[0] != 'Format':
            bFoundSpecError = True
            specErrors.append('  - Missing "Format:" prefix')
        # must be legit type
        if not specParts[1] in validTypes:
            bFoundSpecError = True
            specErrors.append('  - Invalid type [{}] Not one of [{}]'.format(specParts[1], validTypes))
        # each field key must be unique
        fieldKey = '{}:{}'.format(specParts[1], specParts[2])
        if not fieldKey in keysFound:
            keysFound.append(fieldKey)
        else:
            bFoundSpecError = True
            specErrors.append('  - Key [{}] already used!'.format(fieldKey))

        bIsValueSpec = False
        if specParts[1] == 'VALUE':
            bIsValueSpec = True
        # preset alignment validation based on type
        if specParts[1] == 'TIME' or specParts[1] == 'DATE':
            # time/date have Left, right, center
            validAlignmentSet = validLRCAlignmentTypes
        elif specParts[1] == 'LABEL' or specParts[1] == 'VALUE':
            # label, value have Left, right only
            validAlignmentSet = validLtRtAlignmentTypes
        else:
            # message has scrolling alignment too
            validAlignmentSet = validAlignmentTypes
        # preset argument validation based on type
        validArgumentSet = validArgNames
        if bIsValueSpec:
            validArgumentSet = validValueArgNames
        optionList = specParts[3].split(',')
        partIdx = 0
        for currArg in optionList:
            if '=' in currArg:
                argParts = currArg.split('=')
                if len(argParts) != 2:
                    bFoundSpecError = True
                    specErrors.append('  - Argument #{} [{}] missing left or right side'.format(partIdx, currArg))
                else:
                    if not argParts[0] in validArgumentSet:
                        bFoundSpecError = True
                        specErrors.append('  - Argument #{} [{}] Unknown'.format(partIdx, currArg))
                    else:
                        if argParts[0] == validArgumentSet[0]:
                            # validate color
                            if not argParts[1].upper() in validColors:
                                bFoundSpecError = True
                                specErrors.append('  - Argument #{} [{}] Unknown color [{}]'.format(partIdx, currArg, argParts[1]))
                        if argParts[0] == validArgumentSet[1]:
                            # validate line
                            if int(argParts[1]) < 1 or int(argParts[1]) > 10:
                                bFoundSpecError = True
                                specErrors.append('  - Argument #{} [{}] Unknown color [{}]'.format(partIdx, currArg, argParts[1]))
                        if argParts[0] == validArgumentSet[2]:
                            # validate alignment
                            if not argParts[1].upper() in validAlignmentSet:
                                bFoundSpecError = True
                                specErrors.append('  - Argument #{} [{}] Unknown alignment spec [{}]'.format(partIdx, currArg, argParts[1]))
                        if bIsValueSpec:
                            if argParts[0] == validValueArgNames[3]:
                                # validate padWidth
                                if int(argParts[1]) < 2 or int(argParts[1]) > 6:
                                    bFoundSpecError = True
                                    specErrors.append('  - Argument #{} [{}] Invalid PadWidth [{}] must be [2-6]'.format(partIdx, currArg, argParts[1]))
                            if argParts[0] == validValueArgNames[4]:
                                # validate padType
                                if not argParts[1].upper() in validPadTypes:
                                    bFoundSpecError = True
                                    specErrors.append('  - Argument #{} [{}] Unknown padType spec [{}]'.format(partIdx, currArg, argParts[1]))
            else:
                bFoundSpecError = True
                specErrors.append('  - Argument #{} [{}] missing assignment!'.format(partIdx, currArg))
            partIdx += 1
        if bFoundSpecError:
            bFoundError = True
            print_line('ERROR: BAD Format Spec: [{}]'.format(formatSpec), error=True)
            for errStr in specErrors:
                print_line(errStr, error=True)

    if bFoundError:
        print_line('** Aborted due to input errors!', error=True)
        os._exit(1)

def formatSpecFor(valueId):
    desiredSpec = '?not-found?'
    for fmtSpec in cidRawFormatSpecs:
        if valueId in fmtSpec:
            desiredSpec = fmtSpec
    return desiredSpec

def validateDefaultSpecs(defaultValuesDict):
    keysFoundList = []
    specErrorsList = []
    bFoundError = False
    bFoundSpecError = False
    # ensure we have a format string for every Value Spec
    valueIdx = 0
    for valueId in defaultValuesDict.keys():
        if valueId not in cidFormatIDs:
            specErrorsList.append('ERROR: Value Spec: [{}] with no matching format Spec'.format(cidRawValueSpecs[valueIdx]))
            bFoundSpecError = True
        else:
            keysFoundList.append(valueId)
        valueIdx += 1

    # ensure we have a Value string for every non-Value Format Spec
    for valueId in cidFormatIDs:
        if 'VALUE' in valueId or 'TIME' in valueId:
            continue
        if valueId not in keysFoundList:
            specErrorsList.append('ERROR: Missing "Value:" spec for [{}]'.format(valueId))
            formatSpec = formatSpecFor(valueId)
            specErrorsList.append(' - Matching Format Spec: [{}]'.format(formatSpec))
            bFoundSpecError = True

    # show our results
    if bFoundSpecError:
        bFoundError = True
        for errStr in specErrorsList:
            print_line(errStr, error=True)

    if bFoundError:
        print_line('** Aborted due to input errors!', error=True)
        os._exit(1)

def validateSumSpecs(activeCountersList):
    keysFoundList = []
    specErrorsList = []
    bFoundError = False
    bFoundSpecError = False
    # ensure we have a Format Spec for every Sum:VALUE: Spec
    sumIdx = 0
    for valueId in activeCountersList:
        if valueId not in cidFormatIDs:
            specErrorsList.append('ERROR: Sum Spec: [{}] with no matching format Spec'.format(cidRawSumSpecs[sumIdx]))
            bFoundSpecError = True
        else:
            keysFoundList.append(valueId)
        sumIdx += 1
    # ensure we have a Sum string for every Format:VALUE: Spec
    valuesFoundInFormatSpecs = []
    for valueId in cidFormatIDs:
        if 'VALUE' in valueId:
            valuesFoundInFormatSpecs.append(valueId)
    for valueId in valuesFoundInFormatSpecs:
        if valueId not in keysFoundList:
            specErrorsList.append('ERROR: Missing "Sum:" spec for [{}]'.format(valueId))
            formatSpec = formatSpecFor(valueId)
            specErrorsList.append(' - Matching Format Spec: [{}]'.format(formatSpec))
            bFoundSpecError = True

    # show our results
    if bFoundSpecError:
        bFoundError = True
        for errStr in specErrorsList:
            print_line(errStr, error=True)

    if bFoundError:
        print_line('** Aborted due to input errors!', error=True)
        os._exit(1)

timeOfLastCountWrite = None

def isTimeToSaveCount():
    # return T/F - where T means it is time to write the count value(s)
    global timeOfLastCountWrite
    bIsTimeStatus = False
    elapsedSeconds = 0
    timeNow = time.time()
    if timeOfLastCountWrite != None:
        elapsedSeconds = timeNow - timeOfLastCountWrite
    # if first time, or should write every time, or time since last is great enough then do our write!
    #  also write if force is TRUE!
    if timeOfLastCountWrite == None or rs_write_seconds == 0 or elapsedSeconds >= rs_write_seconds:
        bIsTimeStatus = True

    return bIsTimeStatus

def saveCountValue(configKey, countValueStr, force=False):
    # write our latest count value only if it's time to
    global timeOfLastCountWrite
    timeNow = time.time()
    # if first time, or should write every time, or time since last is great enough then do our write!
    #  also write if force is TRUE!
    if force == True or isTimeToSaveCount():
        runtimeConfig.setConfigNamedVarValue(configKey, countValueStr)
        saveCidConfig(cidJsonFspec)
        print_line('Saved latest count [{}]=[{}]'.format(configKey, countValueStr), verbose=True)
        timeOfLastCountWrite = timeNow

def saveBaseValue(configKey, countValueStr):
    # write our latest base value
    runtimeConfig.setConfigNamedVarValue(configKey, countValueStr)
    saveCidConfig(cidJsonFspec)
    print_line('Saved latest count [{}]=[{}]'.format(configKey, countValueStr), verbose=True)


colorama_init()  # Initialize our color console system

# start our serial receive listener

# 1,440,000 = 150x 9600 baud  FAILS P2 Tx
#   864,000 =  90x 9600 baud  FAILS P2 Tx
#   720,000 =  75x 9600 baud  FAILS P2 Rx
#   672,000 =  70x 9600 baud  FAILS P2 Rx
#   624,000 =  65x 9600 baud  GOOD (Serial test proven)
#   499,200 =  52x 9600 baud
#   480,000 =  50x 9600 baud
#
baudRateP2 = 115200
print_line('Baud rate, P2: {:,} bits/sec'.format(baudRateP2), verbose=True)
serialPortP2 = serial.Serial ("/dev/ttyS0", baudRateP2, timeout=1)    #Open port with baud rate & timeout
p2InputQueue = RxLineQueue()
_thread.start_new_thread(taskSerialCmdListener, ( serialPortP2, p2InputQueue, ))


baudRateCmd = 115200
print_line('Baud rate, Cmd: {:,} bits/sec'.format(baudRateCmd), verbose=True)
serialPortCmd = serial.Serial ("/dev/ttyAMA0", baudRateCmd, timeout=1)    #Open port with baud rate & timeout
cmdInputQueue = RxLineQueue()
#_thread.start_new_thread(taskSerialCmdListener, ( serialPortCmd, cmdInputQueue, ))

# start our file-system watcher watching for file changes in folder_control
#dirWatcher = FileSystemWatcher(folder_control)
#dirWatcher.run()
#_thread.start_new_thread(dirWatcher.run, ( ))

def mainLoop():
    while True:             # Event Loop
        sleep(10)

sleep(1)    # allow threads to start...

# run our loop
try:
    mainLoop()

finally:
    # normal shutdown
    print_line('Done', info=True)
    if opt_logging:
        cavidlog_fp.close()
    if opt_log_fragments:
        fraglog_fp.close()
    if opt_term_log:
        termlog_fp.close()
