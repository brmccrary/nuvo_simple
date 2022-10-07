"""Support for interfacing with Nuvo Multi-Zone Amplifier via serial/RS-232."""

import logging
import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType, HomeAssistantType
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util
from homeassistant.const import CONF_TYPE, CONF_NAME, CONF_PORT
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import STATE_OFF, STATE_ON

from . import (
    DOMAIN as COMPONENT_DOMAIN,
    NUVO,
    MODEL,
    DATA_NUVO,
    ZONE_SCHEMA,
    CONF_ZONES,
    ZONE_IDS,
)

_LOGGER = logging.getLogger(__name__)
DOMAIN = 'binary_sensor'

async def async_setup_entry(hass, entry):
    """Set up the number entities for Nuvo."""
    platform = entity_platform.async_get_current_platform()

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: None) -> None:
    zones = hass.data[COMPONENT_DOMAIN][CONF_ZONES]
    hass.data[DATA_NUVO][DOMAIN] = []

    for zone_id, extra in zones.items():
        if hass.data[DATA_NUVO][MODEL] == 'ESSENTIA_D':
            _LOGGER.info("Adding binary sensor entity for zone %d - %s", zone_id,\
                     extra[CONF_NAME])
            hass.data[DATA_NUVO][DOMAIN].append(NuvoOverride(
                NUVO, zone_id, extra[CONF_NAME]))

    async_add_entities(hass.data[DATA_NUVO][DOMAIN], True)

class NuvoOverride(BinarySensorEntity):
    """Representation of a Nuvo amplifier zone settings."""

    def __init__(self, nuvo, zone_id, zone_name):
        """Initialize new zone."""
        self._nuvo = NUVO
        self._zone_id = zone_id
        self._name = zone_name

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self._name, 'settings')
        self.update()

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (override) update called', self._zone_id)
        self.async_schedule_update_ha_state(True)

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zoneset_status(self._zone_id)
        if not state:
            self._override = None
            return None
        else:
            self._override = state.override

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def name(self):
        """Return the name of the zone."""
        return f'{self._name} override'

    @property
    def is_on(self):
        return self._override
