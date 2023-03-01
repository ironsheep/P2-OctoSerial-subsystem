# P2-OctoSerial-subsystem
A Parallax Propeller v2 Object for maintaining 1-8 simultaneous serial ports using one COG

![Project Maintenance][maintenance-shield]

[![License][license-shield]](LICENSE)

## 8 Serial Ports using a single COG

A single COG services from 1 to 8 Tx/Rx pairs of pins.  The pins are configured as smart-pins which means that the driver feeds bytes to transmit pins when needed and get bytes from receive pins when bytes are available. This backend driver is written in pasm2. The interface routines are written in spin2.

A method is supplied that interprets newlines (0x0A) as line ends. (This allows the driver to work with LF or CRLF terminated lines.). This method when called frequently enough unloads the back-end circular buffers into string buffers, one for each active port. When a string has completely arrive it returns the complete strings.

## Table of Contents

On this Page:

- [Driver Features](#driver-features)
- [How to contribute](#how-to-contribute)

Additional pages:

- [Performance Measurement](VERIFY.md) - see timing information from measurements taken on 8-port test system
- [Add serial ports to your project using this object](DEVELOP.md) - Walks thru configuration and setup of serial ports in your own project

### Driver Features

Key Features of this driver:

- Round robbin handling of active ports (not priority based)
- Only active ports are in round robbin
- 8 Active tx/rx port pairs Certified to 26x 115_200 -> 2\_995\_200 baud (w/clk at 300 MHz)
  - Hours of traffic run through all 8 ports P2 <-> P2 with no data corruption or loss at speed
  - All bytes of each message verified

### Current status

Latest Changes:

```
2023-01-19 Further testing results
- Tested with no failures at speeds (clock at 300MHz):
  - 115_200
  - 230_400 - 2x 115_200
  - 640_000
  - 2_000_000
  - 2_995_200 - 26x 115_200
  - Fails at 3_456_000 and above
2022-11-23 Draft release v1.0.0
- Services 1 to eight ports
- Tested initial configuration: 115,200 bps, N81
- Validated with serial decoding logic analyzer
- Tested Raspberry Pi <-> P2
- Tested P2 <-> P2
```

### Known Issues

We have more plans in the works:

- Characterize: Find and document at this repo the highest speeds the driver can do against various devices without data loss
- Add more discrete port control if users find a need (e.g., 2-stop bits, etc.)

## How to Contribute

This is a project supporting our P2 Development Community. Please feel free to contribute to this project. You can contribute in the following ways:

- File **Feature Requests** or **Issues** (describing things you are seeing while using our code) at the [Project Issue Tracking Page](https://github.com/ironsheep/P2-OctoSerial-subsystem/issues)
- Fork this repo and then add your code to it. Finally, create a Pull Request to contribute your code back to this repository for inclusion with the projects code. See [CONTRIBUTING](CONTRIBUTING.md)

---

> If you like my work and/or this has helped you in some way then feel free to help me out for a couple of :coffee:'s or :pizza: slices!
>
> [![coffee](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/ironsheep) &nbsp;&nbsp; -OR- &nbsp;&nbsp; [![Patreon](./images/patreon.png)](https://www.patreon.com/IronSheep?fan_landing=true)[Patreon.com/IronSheep](https://www.patreon.com/IronSheep?fan_landing=true)

---

## Disclaimer and Legal

> *Parallax, Propeller Spin, and the Parallax and Propeller Hat logos* are trademarks of Parallax Inc., dba Parallax Semiconductor
>
> This project is a community project not for commercial use.
>
> This project is in no way affiliated with, authorized, maintained, sponsored or endorsed by *Parallax Inc., dba Parallax Semiconductor* or any of its affiliates or subsidiaries.

---

## License

Copyright © 2022 Iron Sheep Productions, LLC. All rights reserved.

Licensed under the MIT License.

Follow these links for more information:

### [Copyright](copyright) | [License](LICENSE)

[maintenance-shield]: https://img.shields.io/badge/maintainer-stephen%40ironsheep%2ebiz-blue.svg?style=for-the-badge

[license-shield]: https://camo.githubusercontent.com/bc04f96d911ea5f6e3b00e44fc0731ea74c8e1e9/68747470733a2f2f696d672e736869656c64732e696f2f6769746875622f6c6963656e73652f69616e74726963682f746578742d646976696465722d726f772e7376673f7374796c653d666f722d7468652d6261646765
