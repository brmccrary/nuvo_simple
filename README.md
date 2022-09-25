# nuvo_simple
Home Assistant custom component integration to control the basic models Nuvo whole home amplifiers using a serial connection.
This is derived from code published by ejonesnospam.  For the Grand Concerto / Essentia G see sproket-9's integration [nuvo_serial](https://raw.githubusercontent.com/sprocket-9/hacs-nuvo-serial)

## What this Integration does:

Creates Home Assistant Entities for each zone allowing control through the Home Assistant web interface.

#### Media Player Entity:
* On/Off
* Volume
* Mute
* Source selection

#### Number Entities:
* Bass control
* Treble control

#### Switch Entities:
* Grouping
* Volume Reset (Essentia D only)

#### Binary_sensor Entity:
* Keypad DIP switch override (Essentia D only)

#### Services:
* Paging On
* Paging Off
* Mute All Zones
* Unmute All Zones
* All Zones Off

##### Paging service detail:
These Nuvos do not natively support a page function, however you can configure a paging zone and volume levels for the service to switch the amp over to.  Calling the off service restores all zones to their previous state.

## Known issues:

Warning in the logs from Home Assistant: "Detected blocking call to sleep inside the event loop."  I know this is due to the fact the serial port is used, but have not researched in further.  In my experience this does not cause any problems, and the switches usually will be toggled very litte.

Paging service turns on the last played zone for a small amount of time.  The Nuvo does not allow source changes when powered down, and even when powering on, will not accept a source change for a very short amount of time.  Therefore, if the last zone playing was zone 1, for example, and your paging zone is 6, zone 1 will play for a fraction of a second when the Paging on service is called until the Nuvo can be switched to the paging zone.  I don't see a way around this.

Only support for Essentia D and Simplese (untested) is provided currently.  I think this could be adapted to easily support the other simplier Nuvo amps however.

The Simplese is untested but I expect it to work except the bass and treble controls may not.  There is conflicting information in every protocol guide I've seen so someone that owns one will need to send a debug log if it does not work.

## Connecting to the Nuvo:
Connection to the Nuvo is by an RS232 serial port from the host running Home Assistant to the amplifier's serial port, either by using a USB to RS232 converter, or by using a RS232 port directly on the host.  If using a USB to RS232 converter, I would recommend using the full name instead of "/dev/ttyUSB0" as if you have more than one serial port that device can change.  You can find the full name by looking in /dev/serial/by-id.  For instance, "/dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller_D-if00-port0".

## Installing:

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/custom-components/hacs)

Install using the Home Assistant Community Store [HACS](https://hacs.xyz).

Once HACS is installed, go to the Integrations page and select the menu in the upper right hand corner and choose "Custom Repositories."

In the repository field, enter: https://github.com/brmccrary/nuvo_simple
In the Category field, select Integration. 

The integration will now show up as nuvo_simple under integrations inside HACS.  Click on it and Download.
 
## Configuration:

Configuration must be done through configuration.yaml, no GUI option is available for now.

Example:
~~~
nuvo_simple:
  port: /dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller_D-if00-port0
  baud: 9600      # Optional, defaults to 9600
  page_source: 3  # Optional, defaults to source 6
  page_volume: 35 # Optional, defaults to -40.  Volume in DB without the minus sign.  1 is loudest and 78 is muted.
  zones:
    1:
      name: Office
    2:
      name: Very Noisy Room
      zone_page_volume: 10  # Optional, if specified will override page_volume above for that zone only.
  sources:
    1:
      name: SiriusXM
    2:
      name: Chromecast Audio
~~~
## Troubleshooting:

Add the following to configuration.yaml to enable debugging:
~~~
logger:
  default: warn # Put your normal logging level that you use here.
  logs:
    custom_components.nuvo_simple: debug
    nuvo_simple: debug
~~~
