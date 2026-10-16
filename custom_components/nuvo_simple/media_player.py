"""Support for interfacing with Nuvo Multi-Zone Amplifier via serial/RS-232."""

import logging

from homeassistant.core import HomeAssistant, callback
from homeassistant.components.media_player import (
    MediaPlayerEntity, MediaPlayerEntityFeature)
from homeassistant.const import CONF_NAME, STATE_OFF, STATE_ON

from . import (
    DOMAIN as COMPONENT_DOMAIN,
    MODEL,
    CONF_SOURCES,
    CONF_ZONES,
    zone_device_info,
)

_LOGGER = logging.getLogger(__name__)

SUPPORT_NUVO = MediaPlayerEntityFeature.VOLUME_MUTE | \
                    MediaPlayerEntityFeature.VOLUME_SET | \
                    MediaPlayerEntityFeature.VOLUME_STEP | \
                    MediaPlayerEntityFeature.TURN_ON | \
                    MediaPlayerEntityFeature.TURN_OFF | \
                    MediaPlayerEntityFeature.SELECT_SOURCE | \
                    MediaPlayerEntityFeature.GROUPING


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Nuvo media player entities from a config entry."""
    data = hass.data[COMPONENT_DOMAIN][entry.entry_id]
    nuvo = data['nuvo']
    sources = data[CONF_SOURCES]
    zones = data[CONF_ZONES]
    model = data[MODEL]
    entities = [NuvoZone(hass, nuvo, sources, 0, 'Group Controller',
                         entry.entry_id, model)]
    for zone_id, extra in zones.items():
        _LOGGER.info("Adding media player zone %d - %s", zone_id, extra[CONF_NAME])
        entities.append(NuvoZone(hass, nuvo, sources, zone_id, extra[CONF_NAME],
                                 entry.entry_id, model))
    async_add_entities(entities, True)


class NuvoZone(MediaPlayerEntity):
    """Representation of a Nuvo amplifier zone."""

    # The media player is the zone device's primary entity: it takes the
    # zone device's name, so friendly names stay just "Office" etc.
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, hass: HomeAssistant, nuvo, sources, zone_id, zone_name,
                 entry_id, model):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._source_id_name = sources
        self._source_name_id = {v: k for k, v in sources.items()}
        # ordered list of all source names
        self._source_names = sorted(self._source_name_id.keys(),
                                    key=lambda v: self._source_name_id[v])
        self._zone_id = zone_id
        self._name = zone_name
        self._attr_unique_id = f"{entry_id}_zone_{zone_id}"
        self._attr_device_info = zone_device_info(entry_id, model, zone_id, zone_name)

        self._state = None
        self._volume = None
        self._source = None
        self._mute = None
        self._group_members = None

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
        await self.hass.async_add_executor_job(self.update)

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)
        self._nuvo.update_entity_id(old_entity_id, self.entity_id)

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
        self.schedule_update_ha_state(True)

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
