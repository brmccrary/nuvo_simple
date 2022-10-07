"""Support for interfacing with Nuvo Multi-Zone Amplifier via serial/RS-232."""

import logging
import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.media_player import (
    DOMAIN, PLATFORM_SCHEMA, SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_OFF, SUPPORT_TURN_ON, SUPPORT_VOLUME_MUTE, SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_STEP, SUPPORT_GROUPING, MediaPlayerEntity)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, \
    SOURCE_IMPORT
from homeassistant.const import (
    ATTR_ENTITY_ID, CONF_NAME, CONF_PORT, STATE_OFF, STATE_ON)
from homeassistant.helpers import config_validation as cv, entity_platform, \
    service, discovery
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import (
    DOMAIN as COMPONENT_DOMAIN,
    NUVO,
    DATA_NUVO,
    CONF_SOURCES,
    CONF_ZONES,
    SOURCE_SCHEMA,
    ZONE_SCHEMA,
    SOURCE_IDS,
    ZONE_IDS
)

_LOGGER = logging.getLogger(__name__)

SUPPORT_NUVO = SUPPORT_VOLUME_MUTE | SUPPORT_VOLUME_SET | \
                    SUPPORT_VOLUME_STEP | SUPPORT_TURN_ON | \
                    SUPPORT_TURN_OFF | SUPPORT_SELECT_SOURCE | \
                    SUPPORT_GROUPING

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_PORT): cv.string,
    vol.Required(CONF_ZONES): vol.Schema({ZONE_IDS: ZONE_SCHEMA}),
    vol.Required(CONF_SOURCES): vol.Schema({SOURCE_IDS: SOURCE_SCHEMA}),
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    sources = hass.data[COMPONENT_DOMAIN][CONF_SOURCES]
    zones = hass.data[COMPONENT_DOMAIN][CONF_ZONES]
    hass.data[DATA_NUVO][DOMAIN] = []
    hass.data[DATA_NUVO][DOMAIN].append(NuvoZone(hass,
        NUVO, sources, 0, 'Group Controller'))

    for zone_id, extra in zones.items():
        _LOGGER.info("Adding media player zone %d - %s", zone_id, \
                     extra[CONF_NAME])
        hass.data[DATA_NUVO][DOMAIN].append(NuvoZone(hass,
            NUVO, sources, zone_id, extra[CONF_NAME]))

    async_add_entities(hass.data[DATA_NUVO][DOMAIN], True)

class NuvoZone(MediaPlayerEntity):
    """Representation of a Nuvo amplifier zone."""

    def __init__(self, hass: HomeAssistant, nuvo, sources, zone_id, zone_name):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._source_id_name = sources
        self._source_name_id = {v: k for k, v in sources.items()}
        # ordered list of all source names
        self._source_names = sorted(self._source_name_id.keys(),
                                    key=lambda v: self._source_name_id[v])
        self._zone_id = zone_id
        self._name = zone_name

        self._state = None
        self._volume = None
        self._source = None
        self._mute = None

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zone_status(self._zone_id)
        if not state:
            return False
        self._state = STATE_ON if state.power else STATE_OFF
        if state.zonegroup_members != []:
            self._group_members = state.zonegroup_members
        else:
            self._group_members = None
        self._volume = state.volume
        self._mute = state.mute
        try:
            self._source = self._source_id_name[int(state.source)]
        except:
            self._source = 'Unknown'

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self.entity_id, 'media')
        self.update()

    def join_players(self, group_members: list[str]):
        _LOGGER.debug('Zone %s adding %s to group', self._zone_id, group_members)
        self._nuvo.join_players(self._zone_id, group_members)

    def unjoin_player(self) -> None:
        _LOGGER.debug('Zone %s unjoin from all groups', self._zone_id)
        self._nuvo.unjoin_player(self._zone_id)
        return True

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s media player update called', self._zone_id)
        self.async_schedule_update_ha_state(True)

    @property
    def name(self):
        """Return the name of the zone."""
        return self._name

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def device_class(self):
        """Return the type of the device."""
        return 'speaker'

    @property
    def state(self):
        """Return the state of the zone."""
        return self._state

    @property
    def source_list(self):
        """List of available input sources."""
        return self._source_names

    @property
    def group_members(self):
        """List of group members."""
        return self._group_members

    @property
    def volume_level(self):
        """Volume level of the media player (0..1)."""
        if self._volume is None:
            return None
        if int(self._volume) > -24:
            return (( int(self._volume) + 24) / 24 / 2 +.5)
        else:
            return (( int(self._volume) + 78) / 54 / 2)

    @property
    def is_volume_muted(self):
        """Boolean if volume is currently muted."""
        return self._mute

    @property
    def source(self):
        """Return the current input source of the device."""
        return self._source

    @property
    def supported_features(self):
        """Return flag of media commands that are supported."""
        return SUPPORT_NUVO

    def page (self, page_source, page_zones, page_volume):
        """Call paging service."""
        self._nuvo.page(page_source, page_zones, page_volume)

    def restore(self, page_source, page_zones):
        """Restore saved state."""
        self._nuvo.restore(page_source, page_zones)

    def select_source(self, source):
        """Set input source."""
        if source not in self._source_name_id:
            return
        idx = self._source_name_id[source]
        self._nuvo.set_source(self._zone_id, idx)

    def turn_on(self):
        """Turn the media player on."""
        self._nuvo.set_power(self._zone_id, True)

    def turn_off(self):
        """Turn the media player off."""
        self._nuvo.set_power(self._zone_id, False)

    def mute_volume(self, mute):
        """Mute (true) or unmute (false) media player."""
        self._nuvo.set_mute(self._zone_id, mute)

    def set_volume_level(self, volume):
        """Set volume level, range 0..1."""
        if volume > .5:
            self._nuvo.set_volume(self._zone_id, int((volume * 48) - 48))
        else:
            self._nuvo.set_volume(self._zone_id, int((volume * 108) - 78))

    def volume_up(self):
        """Volume up the media player."""
        if self._volume is None:
            return
        self._nuvo.set_volume(self._zone_id, min(self._volume + 1, 0))

    def volume_down(self):
        """Volume down media player."""
        if self._volume is None:
            return
        self._nuvo.set_volume(self._zone_id, max(self._volume - 1, -78))

