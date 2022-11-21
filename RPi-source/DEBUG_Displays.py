#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import _thread
from datetime import datetime
from time import time, sleep, localtime, strftime
import os
import subprocess
import sys
import os.path
import argparse
from collections import deque
from unidecode import unidecode
from colorama import init as colorama_init
from colorama import Fore, Back, Style
import serial
from time import sleep
import PySimpleGUI as sg

from signal import signal, SIGPIPE, SIG_DFL
signal(SIGPIPE,SIG_DFL)

script_version = "0.0.1"
script_name = 'vw_debug.py'
script_info = '{} v{}'.format(script_name, script_version)
project_name = 'DEBUG_'
project_url = 'https://github.com/ironsheep/RPi-P2D2-Support'

if False:
    # will be caught by python 2.7 to be illegal syntax
    print_line('Sorry, this script requires a python3 runtime environment.', file=sys.stderr)
    os._exit(1)

sg.theme('GreenMono')

# Logging function
def print_line(text, error=False, warning=False, info=False, verbose=False, debug=False, console=True):
    timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
    if console:
        if error:
            print(Fore.RED + Style.BRIGHT + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL, file=sys.stderr)
        elif warning:
            print(Fore.YELLOW + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)
        elif info or verbose:
            if opt_verbose:
                # verbose...
                print(Fore.GREEN + '[{}] '.format(timestamp) + Fore.YELLOW  + '- ' + '{}'.format(text) + Style.RESET_ALL)
            else:
                # info...
                print(Fore.MAGENTA + '[{}] '.format(timestamp) + Fore.YELLOW  + '- ' + '{}'.format(text) + Style.RESET_ALL)
        elif debug:
            if opt_debug:
                print(Fore.CYAN + '[{}] '.format(timestamp) + '- (DBG): ' + '{}'.format(text) + Style.RESET_ALL)
        else:
            print(Fore.GREEN + '[{}] '.format(timestamp) + Style.RESET_ALL + '{}'.format(text) + Style.RESET_ALL)

# -----------------------------------------------------------------------------
#  Script Argument parsing
# -----------------------------------------------------------------------------

# Argparse
opt_debug = False
opt_verbose = False
opt_useTestFile = False
opt_logging = False

# Argparse
parser = argparse.ArgumentParser(description=project_name, epilog='For further details see: ' + project_url)
parser.add_argument("-v", "--verbose", help="increase output verbosity", action="store_true")
parser.add_argument("-d", "--debug", help="show debug output", action="store_true")
parser.add_argument("-t", "--test", help="run from canned test file", action="store_true")
parser.add_argument("-l", '--log_filename', help='write all debug messages to log file', default='')
parse_args = parser.parse_args()

opt_debug = parse_args.debug
opt_verbose = parse_args.verbose
opt_useTestFile = parse_args.test
log_filename = parse_args.log_filename
opt_logging = len(log_filename) > 0

print_line(script_info, info=True)
if opt_verbose:
    print_line('Verbose enabled', info=True)
if opt_debug:
    print_line('Debug enabled', debug=True)
if opt_logging:
    print_line('Logging to: {}'.format(log_filename), debug=True)
if opt_useTestFile:
    print_line('TEST: debug stream is test file', debug=True)

log_fp = None
if opt_logging:
    if os.path.exists(log_filename):
        print_line('Log {} already exists, Aborting!'.format(log_filename), error=True)
        os._exit(1)
    else:
        print_line("Logging started", debug=True)
        log_fp = open(log_filename, "w")

# -----------------------------------------------------------------------------
#  Circular queue for serial input lines & input task
# -----------------------------------------------------------------------------

lineBuffer = deque()

def pushLine(newLine):
    lineBuffer.append(newLine)
    # show debug every 100 lines more added
    if len(lineBuffer) % 100 == 0:
        print_line('- lines({})'.format(len(lineBuffer)),debug=True)

def popLine():
    global lineBuffer
    oldestLine = ''
    if len(lineBuffer) > 0:
        oldestLine = lineBuffer.popleft()
    return oldestLine


def taskProcessInput():
    print_line('Thread: taskProcessInput() started', verbose=True)
    # process lies from serial or from test file
    if opt_useTestFile == True:
        test_file=open("charlie_rpi_debug.out", "r")
        lines = test_file.readlines()
        for currLine in lines:
            pushLine(currLine)
            #sleep(0.1)
    else:
        #ser = serial.Serial ("/dev/serial0", 2000000, timeout=1)    #Open port with baud rate & timeout
        ser = serial.Serial ("/dev/ttyAMA1", 2000000, timeout=1)    #Open port with baud rate & timeout
        while True:
            received_data = ser.readline()              #read serial port
            currLine = received_data.decode('latin-1').rstrip()
            if len(currLine) > 0:
                pushLine(currLine)
                #print_line('Rx [{}]!'.format(currLine), debug=True)

# -----------------------------------------------------------------------------
#  Named window support
# -----------------------------------------------------------------------------

kWindowTypeTerm = 'term'
kWindowTypeLogic = 'logic'
kWindowTypeLogic = 'scope'

windowsByName = {}
windowTypeByName = {}
debugViewsShowing = False
kNoSuchWindow = ''

def removeNamedWindow(name):
    global windowsByName
    global windowTypeByName
    if existsNamedWindow(name):
        windowsByName.pop(name)
    if existsTypeForNamedWindow(name):
        windowTypeByName.pop(name)
    if existsNamedWindow(name) or existsTypeForNamedWindow(name):
        print_line('ERROR: Failed to remove window [{}]!'.format(name), error=True)
    else:
        print_line('removeNamedWindow({}) - REMOVED'.format(name), debug=True)

def addNamedWindow(name, window, type):
    global windowsByName
    global windowTypeByName
    if existsNamedWindow(name) == True or existsTypeForNamedWindow(name) == True:
        print_line('NAME {} already in windows list, SKIPPED!'.format(name), error=True)
    else:
        windowsByName[name] = window
        windowTypeByName[name] = type
        print_line('addNamedWindow({}, {}) - ADDED'.format(name, type), debug=True)

def existsNamedWindow(name):
    foundStatus = True
    if getNamedWindow(name) == kNoSuchWindow:
        foundStatus = False
    return foundStatus

def getNamedWindow(name):
    return windowsByName.get(name, kNoSuchWindow)

def addTypeForNamedWindow(name, type):
    global windowTypeByName
    if existsTypeForNamedWindow(name) == False:
        windowTypeByName[name] = type
    else:
        print_line('NAME {} already in windows list, SKIPPED!'.format(name), error=True)

def existsTypeForNamedWindow(name):
    foundStatus = True
    if getTypeForNamedWindow(name) == kNoSuchWindow:
        foundStatus = False
    return foundStatus

def getTypeForNamedWindow(name):
    return windowTypeByName.get(name, kNoSuchWindow)



    """
    CONSTANTS From Chips code

    clLime                = $00FF00;
    clRed                 = $0000FF;
    clBlue                = $FF3F00;
    clYellow              = $00FFFF;
    clMagenta             = $FF00FF;
    clAqua                = $FFFF00;
    clOrange              = $007FFF;
    clOlive               = $007F7F;
    clWhite               = $FFFFFF;
    clBlack               = $000000;
    clGrey                = $404040;
    DefaultBackColor      = clBlack;
    DefaultGridColor      = clGrey;
    DefaultLineColor      = clAqua;
    DefaultFillColor      = clBlue;
    DefaultTextColor      = clYellow;
    DefaultColor          = clAqua;

    DefaultLineSize       = 1;
    DefaultDotSize        = 1;
    DefaultTextSize       = 10;
    DefaultTextStyle      = 0;

    DefaultCols           = 80;
    DefaultRows           = 25;

    scope_wmin            = 32;
    scope_wmax            = 2048;
    scope_hmin            = 32;
    scope_hmax            = 2048;

    scope_xy_wmin         = 32;
    scope_xy_wmax         = 2048;

    plot_wmin             = 32;
    plot_wmax             = 2048;
    plot_hmin             = 32;
    plot_hmax             = 2048;

    term_colmin           = 1;
    term_colmax           = 256;
    term_rowmin           = 1;
    term_rowmax           = 128;

    DefaultScopeColors    : array[0..7] of integer = (clLime, clRed, clAqua, clYellow, clMagenta, clBlue, clOrange, clOlive);
    DefaultTermColors     : array[0..7] of integer = (clOrange, clBlack, clYellow, clBlack, clAqua, clBlack, clLime, clBlack);
    """

clLime                = "#00FF00"
clRed                 = "#FF0000"
clBlue                = "#003FFF"
clYellow              = "#FFFF00"
clMagenta             = "#FF00FF"
clAqua                = "#00FFFF"
clOrange              = "#FF7F00"
clOlive               = "#7F7F00"
clWhite               = "#FFFFFF"
clBlack               = "#000000"
clGrey                = "#404040"
clGreen               = "#00FF00"
DefaultBackColor      = clBlack
DefaultGridColor      = clGrey
DefaultLineColor      = clAqua
DefaultFillColor      = clBlue
DefaultTextColor      = clYellow
DefaultColor          = clAqua

DefaultLineSize       = 1
DefaultDotSize        = 1
DefaultTextSize       = 10
DefaultTextStyle      = 0

DefaultCols           = 80
DefaultRows           = 25

scope_wmin            = 32
scope_wmax            = 2048
scope_hmin            = 32
scope_hmax            = 2048

scope_xy_wmin         = 32
scope_xy_wmax         = 2048

plot_wmin             = 32
plot_wmax             = 2048
plot_hmin             = 32
plot_hmax             = 2048

term_colmin           = 1
term_colmax           = 256
term_rowmin           = 1
term_rowmax           = 128

DefaultScopeColors    = [ clLime, clRed, clAqua, clYellow, clMagenta, clBlue, clOrange, clOlive ]
DefaultTermColors     = [ clOrange, clBlack, clYellow, clBlack, clAqua, clBlack, clLime, clBlack ]

# -----------------------------------------------------------------------------
#  Debug output parsing support
# -----------------------------------------------------------------------------

kTypeString = 'string'
kTypeInteger = 'int'
kTypeColor = 'color'

valTableTerm = [
    ( 'TITLE', kTypeString ),
    ( 'POS', kTypeInteger, kTypeInteger ),
    ( 'SIZE', kTypeInteger, kTypeInteger ),
    ( 'TEXTSIZE', kTypeInteger ),
    ( 'TEXTCOLOR', kTypeColor, kTypeColor ),
    ( 'BACKCOLOR', kTypeColor ),
    ( 'UPDATE' ),
]

def getValidationTuple(table, parameterName):
    print_line('table=[{}], parameterName=[{}]'.format('tbl-??', parameterName), debug=True)
    desiredValTuple = ''
    validStatus = False
    searchTerm = parameterName.lower()
    for tupleIndex in range(len(table)):
        currTuple = table[tupleIndex]
        keyword = currTuple[0].lower()
        if keyword == searchTerm:
            desiredValTuple = currTuple
            validStatus = True
            break;

    print_line('-> tuple=[{}], valid={}'.format(desiredValTuple, validStatus), debug=True)
    return desiredValTuple, validStatus

def intForColorString(colorString):
    # % means binary ^2
    # %% quarternary ^4
    # $ means hex ^16
    return

def interpretArgument(argument, validationType):
    print_line('argument=[{}], validationType=[{}]'.format(argument, validationType), debug=True)
    interpValue = ''
    validStatus = True
    if validationType == kTypeString:
        interpValue = argument
    elif validationType == kTypeInteger:
        interpValue = int(argument)
    elif validationType == kTypeColor:
        interpValue = intForColorString(argument)
    else:
        print_line('ERROR: Unknown validation Type=[{}]'.format(validationType), error=True)
        validStatus = False

    print_line('-> interpValue=[{}], valid={}'.format(interpValue, validStatus), debug=True)
    return interpValue, validStatus

def parseOptions(lineParts, valTable, skip=0):
    # process line parts into tuples
    #  returning (tuples, valid flag)
    optionTuples = []
    validStatus = True
    maxParts = len(lineParts)
    currIndex = skip
    while currIndex < maxParts:
        validationTuple, valid = getValidationTuple(valTable, lineParts[currIndex])
        fieldValues = []
        if valid == False:
            validStatus = False
            break
        else:
            # now gather needed values into list then into new tuple
            fieldValues.append(lineParts[currIndex])
            if len(validationTuple) > 1:
                for fieldIndex in range(len(validationTuple) - 1):
                    currIndex += 1
                    parsedValue, valid = interpretArgument(lineParts[currIndex], validationTuple[fieldIndex+1])
                    if valid == True:
                        fieldValues.append(parsedValue)
                    else:
                        validStatus = False
                        break;
                if validStatus == False:
                    break

            currIndex += 1  # point past only/final value
            optionTuples.append(tuple(fieldValues))

    print_line('-> tuples=[{}], valid={}'.format(optionTuples, validStatus), debug=True)
    return optionTuples, validStatus

# -----------------------------------------------------------------------------
#  Debug driven FEED a Window operations
# -----------------------------------------------------------------------------

kTermControlList = [ '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '13', 'CLEAR', 'UPDATE', 'SAVE', 'CLOSE' ]
windowCloseRequested = False

def buildTermList(rawValue):
    """
    TERM feed:
        0 = Clear			'control characters
        1 = Home
        2 = Set colum, column follows
        3 = Set row, row follows
        4 = Set color 0
        5 = Set color 1
        6 = Set color 2
        7 = Set color 3
        8 = Backspace			'printable characters
        9 = Tab
        13 = New line
        >31 = chr
        'string'			'print string
        CLEAR				'clear display
        UPDATE				'update display (only needed in 'update' mode)
        SAVE 'filename'			'save display as filename.bmp
        CLOSE				'close display, frees name
    """
    desiredOperations = []
    validStatus = True
    lineParts = rawValue.split()
    inString = False
    currString = ''
    skipNext = False
    for partIndex in range(len(lineParts)):
        currPart = lineParts[partIndex]
        if skipNext == True:
            skipNext = False
            continue
        if inString == True:
            # append this to string
            currString = '{} {}'.format(currString, currPart)
            if "'" in currPart:
                # end this string, it is closed
                newOpTuple = ( currString.replace("'",''), '' )
                desiredOperations.append( newOpTuple )
                inString = False
                currString = ''
        elif "'" in currPart:
            if inString == False:
                # start a new string
                currString = currPart
                inString = True
        elif currPart.upper() in kTermControlList:
            # have numeric directive!
            if currPart.upper() == 'CLEAR':  # have 2nd form of clear, make it first form
                # have clear screen
                desiredOperations.append( ( '0', '' ) )
            elif currPart == '2' or currPart == '3' or currPart.upper() == 'SAVE':  # have ROW
                # MAYBE BUG: fix whitespace in filename case?!
                newOpTuple  = ( currPart, lineParts[partIndex + 1] )
                skipNext = True
                desiredOperations.append( newOpTuple )
            else:
                desiredOperations.append( ( currPart, '' ) )
        else:
            # BAD directive!
            print_line('ERROR: unknown TERM directive [{}] in [{}]'.format(currPart, rawValue), error=True)
            validStatus = False
    print_line('-> desiredOperations({})=[{}], valid={}'.format(len(desiredOperations), desiredOperations, validStatus), debug=True)
    return desiredOperations, validStatus

def feedTermWindow(rawValue, targetWindow):
    global windowCloseRequested
    writeOperationList, valid = buildTermList(rawValue)
    textColor = DefaultTermColors[0]  # 0,1 are default FG,BG colors
    backgroundColor = DefaultTermColors[1]  # 0,1 are default FG,BG colors
    if valid == True:
        for currOp in writeOperationList:
            print_line('currOp[{}]=[{}]'.format(len(currOp), currOp[0]), debug=True)
            currValue = currOp[0]
            if currValue == '0':
                # clear the display
                targetWindow[DEBUG_MULTILINE_KEY].update('', append=False)
            elif currValue.upper() == 'CLOSE':
                # close the window
                windowCloseRequested = True
            elif currValue.upper() == 'UPDATE':
                print_line('WARNING: UPDATE - not yet supported'.format(), warning=True)
            elif currValue.upper() == 'SAVE':
                print_line('WARNING: SAVE to {} - not yet supported'.format(currOp[1]), warning=True)
            elif currValue.upper() == '4':
                textColor = DefaultTermColors[0]  # 0,1 are default FG,BG colors
                backgroundColor = DefaultTermColors[1]  # 0,1 are default FG,BG colors
            elif currValue.upper() == '5':
                textColor = DefaultTermColors[2]  # 0,1 are default FG,BG colors
                backgroundColor = DefaultTermColors[3]  # 0,1 are default FG,BG colors
            elif currValue.upper() == '6':
                textColor = DefaultTermColors[4]  # 0,1 are default FG,BG colors
                backgroundColor = DefaultTermColors[5]  # 0,1 are default FG,BG colors
            elif currValue.upper() == '7':
                textColor = DefaultTermColors[6]  # 0,1 are default FG,BG colors
                backgroundColor = DefaultTermColors[7]  # 0,1 are default FG,BG colors
            elif currValue.upper() == '9':
                # write a tab
                targetWindow[DEBUG_MULTILINE_KEY].update('\t', append=True)
            elif currValue.upper() == '13':
                # write a newline
                targetWindow[DEBUG_MULTILINE_KEY].update('\n', append=True)
            else:
                print_line('currValue=[{}], fg=[{}], bg=[{}]'.format(currValue, textColor, backgroundColor), debug=True)
                targetWindow[DEBUG_MULTILINE_KEY].update(currValue, text_color=textColor, background_color=backgroundColor, append=True)
    else:
        print_line('ERROR: invalid parse of [{}]'.format(rawValue), error=True)

def feedBadWindowType(rawValue, targetWindow):
    print_line('ERROR: no window for [{}]'.format(rawValue), error=True)


# -----------------------------------------------------------------------------
#  Debug driven CREATE/ROUTE operations
# -----------------------------------------------------------------------------

def opCreateTermWindow(cmdString):
    print_line('opCreateWindow({})'.format(cmdString), debug=True)
    """
    ---------------------------------------------------------------------------------------
    TERM config:	TITLE 'Title String'		'override default caption
                    POS screen_x screen_y		'default is 0 0
                    SIZE columns rows	        'default is 80 25
                    TEXTSIZE text_size_6_to_200	'default is current text editor size
                    TEXTCOLOR text0 back0 ...	'define text and back colors for settings pairs 0..3
                    BACKCOLOR color_rrggbb		'set background color
                    UPDATE	                    'set 'update' mode
    ---------------------------------------------------------------------------------------
    """
    lineParts = cmdString.split()
    if len(lineParts) > 2 and lineParts[1] == '`term':
        newWindowName = lineParts[2]
        print_line('newWindowName=[{}]'.format(newWindowName), debug=True)
        # create the desired window
        # EXAMPLE:
        #   Cog0  `term temp size 80 16 textsize 10
        settingsTuples, valid = parseOptions(lineParts, valTableTerm, skip=3)
        if valid == True:
            # configure the window
            windowTitle = '{} - TERM'.format(newWindowName)
            windowWidth = DefaultCols
            windowHeight = DefaultRows
            windowX = 0
            windowY = 0
            fontSize = DefaultTextSize
            foregroundColor = DefaultTermColors[0]  # 0,1 are default FG,BG colors
            backgroundColor = DefaultTermColors[1]  # 0,1 are default FG,BG colors
            for tupleIndex in range(len(settingsTuples)):
                currOption = settingsTuples[tupleIndex]
                if currOption[0].upper() == 'SIZE':
                    windowWidth = currOption[1]
                    windowHeight = currOption[2]
                elif currOption[0].upper() == 'TEXTSIZE':
                    fontSize = currOption[1]
                elif currOption[0].upper() == 'BACKCOLOR':
                    backgroundColor = currOption[1]
                elif currOption[0].upper() == 'POS':
                    windowX = currOption[1]
                    windowY = currOption[2]
                elif currOption[0].upper() == 'TITLE':
                    windowTitle = currOption[1]
            # create our TERM window
            layout = [ [sg.Multiline(size=(windowWidth, windowHeight), write_only=True, background_color=backgroundColor, font=("Helvetica", fontSize), text_color=foregroundColor, autoscroll=True, key=DEBUG_MULTILINE_KEY)] ]
            window = sg.Window(title=windowTitle, layout=layout, location=(windowX, windowY), finalize=True)

            # remember the window
            addNamedWindow(newWindowName, window, kWindowTypeTerm)
        else:
            os._exit(1) # PARSE FAIL exit!!!
    else:
        print_line('BAD Window Create command [{}]'.format(cmdString), error=True)
        os._exit(1) # PARSE FAIL exit!!!

def opJustLogIt(cmdString):
    print_line('opJustLogIt({})'.format(cmdString), debug=True)


def opSendToWindow(cmdString):
    global windowCloseRequested
    lineParts = cmdString.split()
    print_line('opSendToWindow(window=[{}], value=[{}])'.format(lineParts[1], cmdString), debug=True)
    # EXAMPLE:
    #   Cog0  `temp 'Xpin=24, Ypin=25' 13
    lineForTerm = ' '.join(lineParts[2:])
    targetWindowName = lineParts[1].replace("`", '')
    if existsNamedWindow(targetWindowName):
        windowCloseRequested = False
        targetWindow = getNamedWindow(targetWindowName)
        targetWindowType = getTypeForNamedWindow(targetWindowName)
        windowWriteFunction = functionForWrite(targetWindowType)
        windowWriteFunction(lineForTerm, targetWindow)
        # if line contained a 'close' then let's close our window
        if windowCloseRequested == True:
            removeNamedWindow(targetWindowName)
            targetWindow.close()


def functionForWrite(opId):
    table = {
        kWindowTypeTerm : feedTermWindow,
    }
    # get() method of dictionary data type returns
    # value of passed argument if it is present
    # in dictionary otherwise second argument will
    # be assigned as default value of passed argument
    return table.get(opId, feedBadWindowType)

def functionForCommand(opId):
    table = {
        "`term" : opCreateTermWindow,
        "INIT" : opJustLogIt,
    }
    # get() method of dictionary data type returns
    # value of passed argument if it is present
    # in dictionary otherwise second argument will
    # be assigned as default value of passed argument
    return table.get(opId, opSendToWindow)



DEBUG_MULTILINE_KEY = '-OUTPUT-'+sg.WRITE_ONLY_KEY
debugLogWindow = ''

def debugLogClear():
    debugLogWindow[DEBUG_MULTILINE_KEY].update('')

def debugLogPrint(text, fgColor=clGreen, bgColor=clBlack):
    debugLogWindow[DEBUG_MULTILINE_KEY].update(text, text_color=fgColor, background_color=bgColor, text_color_for_value=fgColor, background_color_for_value=bgColor, append=True)

def SetUpDebugLogWindow():
    global debugViewsShowing
    global debugLogWindow
    debugViewsShowing = True
    # create our default log display window
    layout = [ [sg.Multiline(size=(80,24), background_color=clBlack, font=("Helvetica", DefaultTextSize), write_only=True, autoscroll=True, key=DEBUG_MULTILINE_KEY)] ]
    debugLogWindow = sg.Window('DEBUG Output', layout, finalize=True)

def processDebugLine(debug_text):
    # if our debug output log window not showing show it
    if debugViewsShowing == False:
        SetUpDebugLogWindow()
        debugLogClear()

    if opt_logging:
        log_fp.write(debug_text + '\n')

    # EXAMPLES:
    # Cog0  INIT $0000_0000 $0000_0000 load
    # Cog0  INIT $0000_0D58 $0000_1248 jump
    # Cog0  `term temp size 80 16 textsize 10
    # Cog0  `temp 'Xpin=24, Ypin=25' 13
    lineParts = debug_text.split()

        #  process a line of P2 DEBUG output
    textColor = clGreen
    if len(lineParts) > 1:
        if lineParts[1] == 'INIT':
            textColor = clBlue
        elif lineParts[1] == '`term':
            textColor = clOrange

    debugLogPrint(debug_text.rstrip() + '\n', fgColor=textColor)

    if len(lineParts) > 1:
        # [0] is cog ID
        # [1] is directive or routing ID (window name)
        operation = functionForCommand(lineParts[1])
        operation(debug_text)


kWindowReadTimeoutIn_mSec = 1

def mainLoop():
    while True:             # Event Loop
        if debugViewsShowing == True:
            event, values = debugLogWindow.read(timeout=kWindowReadTimeoutIn_mSec)
            if event != '__TIMEOUT__':
                print(event, values)
            if event in (sg.WIN_CLOSED, 'Exit'):
                break
            if event == 'Clear':
                debugLogWindow[DEBUG_MULTILINE_KEY].update('')
        # process an incoming line - creates our windows as needed
        currLine = popLine()
        if len(currLine) > 0:
            processDebugLine(currLine)

    debugLogWindow.close()
    print_line('Debug Window EXIT', debug=True)
    if opt_logging:
        log_fp.close()

# -----------------------------------------------------------------------------
#  Main loop
# -----------------------------------------------------------------------------

# start our input task
_thread.start_new_thread(taskProcessInput, ( ))

# run our loop
try:
    mainLoop()

finally:
    # normal shutdown
    debugLogWindow.close()
    print_line('Done', info=True)
    if opt_logging:
        log_fp.close()
