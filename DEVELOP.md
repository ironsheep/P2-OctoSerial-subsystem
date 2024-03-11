# Developing a P2 Application with 2-8 serial ports using this octo-serial driver

Add a 2-8 port serial subsystem to your project!

![Project Maintenance][maintenance-shield]

[![License][license-shield]](LICENSE)

## Table of Contents

On this Page:

*Follow these steps to add 2-8 port serial P2 driver to your project:*

- [Download the latest release .zip file](#download-the-latest-release-file) - get project files
- [Include project object(s) in your top-object-file](#include-project-object-in-your-top-object-file) - adjust your top-level file
- [Add your own serial code](#and-youre-off--add-your-own-serial-sendreceive-code) 

Additional pages:

- [Main Page](https://github.com/ironsheep/P2-OctoSerial-subsystem) - Return to the top of this repo

---

## Download the latest release file

Go to the project [Releases page](https://github.com/ironsheep/P2-OctoSerial-subsystem/releases) expand the **Assets** heading to see the **OctoMimumFiles.zip** file link. Click on it to download the .zip file. Unzip it and then move the three **.spin2** files into your project. 

Lastly you'll include the objects, define the ports you want to use, start the driver and then add your serial port send/receive code.


## Include Project Object in your top-object-file

You now need to select octo port object(s).


### Using the P2 Octo-serial Driver

- isp\_octoport_serial.spin2 - the new serial driver code. 

You simply include file(s) with something like:

```script
OBJ { Objects Used by this Object }

    serPorts  : "isp_octoport_serial"	           ' include the driver
    strFmt    : "isp_mem_strings"                  ' include in-memory formatted strings

```

#### Start the Octo-serial Driver

Starting the driver object in Spin2 is also pretty simple:

```spin2
CON { serial io pins }

    BAUD_OCTO_PORTS = 115_200

    ' port 1 Rx and Tx,  far end Raspberry Pi
    SER1_RX = 16
    SER1_TX = 17
    
    ' port 2 Rx and Tx, far end P1
    SER2_RX = 20
    SER2_TX = 21
    
    CHAR_BUFFER_SIZE = 80
    
VAR { port handles }

  LONG  hndlRpi
  LONG  hndlP1
  
  BYTE txBuffer[32 + 1]
  BYTE rxBuffer[CHAR_BUFFER_SIZE + 1]

PUB main() : ok | portHandle, pNextString
'' DEMO 

    ' tell object what ports are active
    
    ' this link connects to raspberry pi
    hndlRpi := serPorts.addPort(SER1_RX, SER1_TX, serPorts.MODE_NONE, BAUD_OCTO_PORTS, serPorts.PU_3K3)  
          
    ' this link connects to a P1             
    hndlP1 := serPorts.addPort(SER2_RX, SER2_TX, serPorts.MODE_NONE, BAUD_OCTO_PORTS, serPorts.PU_15K) 
    
    ' start the transceiver cog
    ok := serPorts.start()
    if not ok
        debug("* Serial FAILED to start")
    else
        debug("* Serial started OK")

  ... and do your app stuff from here on ...
  
    ' HERE's a tiny example:
    
    ' create our string from variables
    strFmt.sFormatStr1(@txBuffer, string("%d:$sb12\r\n"), hndlRpi + 1)
    
    ' send our string to RPi
    serPorts.txStr(hndlRpi, @txBuffer)
    
    ' loop waiting for string replies
    repeat
       portHandle, pNextString := serPorts.nextRxString(@rxBuffer, CHAR_BUFFER_SIZE)
       if portHandle <> serPorts.PORT_NOT_FOUND
           debug("* Rx [", zstr_(pNextString), "](", udec_(strsize(pNextString)), ")")
   
```


### And you're off!  Add your own serial send/receive code

You are now at the `... and do your app stuff from here on ...` section of this page.
From here on, just use any of the Public Methods found in the interface description.  Here's a quick (maybe partial) summary:

| Method Signature | Purpose |
| --- | --- |
| --- **Initial Startup** ---
| PUB  addPort(rxp, txp, mode, baudrate, txPullup) : portHandle | Call this method before start(). (minimum, 1 call to this routine required before calling start())</br> Can't use the same pin for more than one port!</br> Returns {portHandle} to use for subsequent accesses to this port (or PORT\_NOT_FOUND if error)
| PUB  start() : ok | Start the backend COG 8-port transceiver
| PUB  stop() |  Stop the backend 8-port transceiver cog and serial dequeue cog</br> -- frees the cog if driver was running
| --- **Receive Routines** ---
| PUB  rx(portHandle) : nChar | Pulls BYTE from backend COG Transceiver receive buffer if available</br> -- WARNING: will wait for char to arrive if buffer is empty!
| PUB  rxCheck(portHandle) : nChar | Pulls BYTE from backend COG Transceiver receive buffer if available</br> -- returns (NO_CHAR) if buffer is empty (or invalid port handle)
| PUB  rxTime(portHandle, ms) : nChar | Wait ms milliseconds for a BYTE to be received</br> -- returns (NO_CHAR) if no BYTE received, $00..$FF if BYTE
| PUB  rxTix(portHandle, tix) : nChar |  Waits {tix} clock ticks for a BYTE to be received</br> -- returns (NO_CHAR) if no BYTE received
| --- **Transmit Routines** ---
| PUB  tx(portHandle, nChar) |  Move BYTE into backend COG Transceiver transmit buffer if room is available</br> -- sets port OVERFLOW status if buffer was full (nChar is ignored in this case)
| PUB  txN(portHandle, nChar, nCount) | Emit {nChar} {nCount} times
| PUB  txStr(portHandle, pStr) | Emit z-string pointed to by {pStr}
| PUB  txPrefix(portHandle, pStr, prefixLen) | Emit {prefixLen} characters of string at {pStr}</br> -- will stop at end of string if it happens before {prefixLen}
| --- **Special String Receiver** ---
| PUB  nextRxString(pUserBuf, nBufLen) : portHandle, pNextString | Return pointer {pNextString} to avail string with</br>{portHandle} of port it came from</br> -- returns {portHandle} of PORT_NOT_FOUND if no strings available
| --- **Port Control and Status** ---
| PUB  portBaudrate(portHandle) : nBaudrate | Return the baudrate configured for given port (or -1 if invalid port handle)
| PUB  isRxOverflow(portHandle) : bOverflowStatus |  Return the OVERFLOW status (T/F) for given port
| PUB  clearRxOverflow(portHandle) |  Clear OVERFLOW status for given port
| PUB  rxFlush(portHandle) |  Flush receive buffer
| PUB  rxCharsAvailable(portHandle) : nbrCharsAvail |  Returns count of characters in backend COG Transceiver receive buffer waiting to be unloaded
| PUB  txComplete(portHandle) : bCompleteStatus | Returns T/F where T means tx buffer is empty (or FALSE if invalid port handle)
| PUB  txFlush(portHandle) | Wait until transmit buffer is empty</br> -- will delay one additional BYTE period after buffer is empty
| --- **Queued String Routines** --- | { **--- SPECIAL BUILD REQUIRED ---** }</br>(See `*-COG-OFFLOADER-*` markers in **isp\_octoport_serial.spin2**)
| PUB  getRxString(pUserBuf, nBufLen) : pNextString |  Return next string from receive QUEUE (or 0 if empty)


Have Fun!

## Files included with the Octo-Serial Driver

There are files for both the P2 and files for a test Raspberry Pi in this repository.

Two directories contain files:

- The `P2-source/` directory contains the following files for the P2.

**Core driver files:**

| Filename | Description |
| --- | --- |
| demo_octoSystem.spin2 | (**WELL THIS IS NOT REALLY A CORE FILE**)</br>A demonstration file I use for testing w/RPi<->P2 and P2<->P2
| isp\_mem_strings.spin2 | An in-memory string formatter so you can build strings to send using printf() like code
| isp\_octoport_serial.spin2 | The 2-8 Port Serial Driver file (*this is configured to work standalone!*)
| jm_nstrings.spin2 | Underlying support used internally by `isp_mem_strings.spin2`

**Additional files when using the Special Build form of the driver:**

| Filename | Description |
| --- | --- |
| isp\_string_queue.spin2 | A String Queue mechanism
| isp\_stack_check.spin2 | A stack check tool I used when running spin cogs

**NOTE:** To convert the driver to have it's own separate cog for offloading incoming strings you hunt down all `*-COG-OFFLOADER-*` comment marks. Each of these lines start with a '{'. To enable this feature you comment the { by preceeding it with a "'" (spin2 comment character) this uncomments the code within the { ... } block. You have to find all of these (5 or more of them) in the file and uncomment each.  This effort changes start() to now start a 2nd cog which constantly runs to offload strings from the backend cog and store them in a special string queue. A new method `getRxString()` is then used to pop strings off of this new queue.  *I put this in as an experiment. If you find it useful let me know!*

- and the `RPi-source/` directory contains 

| Filename | Description |
| --- | --- |
| p2-octo-serial-test.py | A test file I used to ack messages sent by the P2, it manages two separate serial ports and must be run on an RPi 4 so there are two serial ports.
| config.ini | This test file was copied from another project. I butched it but left in the config.ini reader in case i need it later. The file is here and must be when python script is run but provides no useful info to the script. (all content is currently parsed but ignored)
| requirements.txt | This is the requirements needed my python for the script to run. you know what to do with this if you've played with our P2 IoT Gateway project.
---

> If you like my work and/or this has helped you in some way then feel free to help me out for a couple of :coffee:'s or :pizza: slices!
>
> [![coffee](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/ironsheep) &nbsp;&nbsp; -OR- &nbsp;&nbsp; [![Patreon](./images/patreon.png)](https://www.patreon.com/IronSheep?fan_landing=true)[Patreon.com/IronSheep](https://www.patreon.com/IronSheep?fan_landing=true)


---

## Disclaimer and Legal

> *Parallax, Propeller Spin, and the Parallax and Propeller Hat logos* are trademarks of Parallax Inc., dba Parallax Semiconductor

---

## License

Licensed under the MIT License.

Follow these links for more information:

### [Copyright](copyright) | [License](LICENSE)

[maintenance-shield]: https://img.shields.io/badge/maintainer-stephen%40ironsheep%2ebiz-blue.svg?style=for-the-badge

[license-shield]: https://img.shields.io/badge/License-MIT-yellow.svg

