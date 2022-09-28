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
* Paging On (nuvo_simple.paging_on)
* Paging Off (nuvo_simple.paging_off)
* Mute All Zones (nuvo_simple.mute_all)
* Unmute All Zones (nuvo_simple.unmute_all)
* All Zones Off (nuvo_simple.all_off)

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

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)

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

## Lovelace Frontend Configuration
I really liked the way [sproket-9](https://github.com/sprocket-9) created the idea of using the [mini-media-player](https://github.com/kalkih/mini-media-player) and I think it works great for the "simple" Nuvo amps as well.  Here is his example, except I only added one zone, but this should be enough to get someone started:

Everything in this section is optional and shows a heavily opinionated method of configuring Lovelace to display the Nuvo entities.  While it may not be to everyones taste, it should at least give some inspiration for configuration possibilites.

The core [Media Player](https://www.home-assistant.io/integrations/media_player/) integration (and therefore any Lovelace media control card representing a media player entity) does not provide a way to control a media device's EQ settings.  Each EQ setting is modeled using the [Number](https://www.home-assistant.io/integrations/number/) integration.  The advantage of this is the ability to use the native number ranges exposed by the Nuvo for each control rather than a card showing a generic 0-X scale.

While Home Assistant will auto-create Lovelace media control and number cards for each Nuvo entity, a more polished look can be achieved using third-party cards [mini-media-player](https://github.com/kalkih/mini-media-player) and [lovelace-slider-entity-row](https://github.com/thomasloven/lovelace-slider-entity-row), both cards are installable through [HACS](https://hacs.xyz).

This example Lovelace configuration displays the EQ settings in a [Conditional](https://www.home-assistant.io/lovelace/conditional/) card that is only displayed when the zone is switched on and an input_boolean entity is True.  This input_boolean is toggled by tapping the mini-media-player representing the zone.  In order to achieve this, an additional input_boolean entity per-zone needs manually created (it's purely to control the frontend EQ Conditional card, it doesn't represent anything on the Nuvo itself).

e.g. In configuration.yaml:

```yaml
input_boolean:
  eq_office:
    name: Office EQ
    initial: off
```

Will create the entity:
```
input_boolean.eq_office
```

As shown the yaml section below, the [tap action](https://github.com/kalkih/mini-media-player#action-object-options) on each mini-media-player will call the input_boolean.toggle service.

Example section in ui-lovelace.yaml:

```yaml

views:
  - title: MusicZones
    cards:
      - type: vertical-stack
        cards:
          - type: entities
            entities:
              - type: custom:mini-media-player
                entity: media_player.office
                group: true
                hide:
                  controls: false
                  info: false
                  power_state: false
                  play_pause: true
                  prev: true
                  next: true
                icon: mdi:speaker-wireless
                volume_stateless: true
                tap_action:
                  action: call-service
                  service: input_boolean.toggle
                  service_data:
                    entity_id: input_boolean.eq_office
              - type: custom:slider-entity-row
                entity: media_player.office
                full_row: true
                step: 1
                hide_state: false
                hide_when_off: true
          - type: conditional
            conditions:
              - entity: media_player.office
                state: 'on'
              - entity: input_boolean.eq_office
                state: 'on'
            card:
              type: entities
              entities:
                - type: custom:slider-entity-row
                  entity: number.office_bass
                  name: Bass
                  icon: mdi:music-clef-bass
                  hide_state: false
                  hide_when_off: true
                  full_row: false
                - type: custom:slider-entity-row
                  entity: number.office_treble
                  full_row: false
                  name: Treble
                  icon: mdi:music-clef-treble
                  hide_state: false
                  hide_when_off: true
                - entity: switch.office_volume_reset
                  name: Volume Reset
                  icon: mdi:volume-low
                  show_state: true
                - entity: switch.office_source_group
                  name: Source Grouping
                  icon: mdi:speaker-multiple
                  show_state: true
                - entity: binary_sensor.office_override
                  name: Keypad Override
                  icon: mdi:cogs
                  show_state: true

This configuration will display the card below (except with your own theme, which is probably different than mine), with the EQ settings card toggled by tapping on the media player, in any area not containing a control:

![Lovelace](images/lovelaceui.png)
