"""Support for interfacing with Nuvo Multi-Zone Amplifier via serial/RS-232."""

import logging
import voluptuous as vol
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.number import NumberEntity
from homeassistant.const import CONF_TYPE, CONF_NAME, CONF_PORT
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType, HomeAssistantType
from homeassistant.util import dt as dt_util

from . import (
    DOMAIN as COMPONENT_DOMAIN,
    NUVO,
    DATA_NUVO,
    ZONE_SCHEMA,
    CONF_ZONES,
    ZONE_IDS,
)

_LOGGER = logging.getLogger(__name__)
DOMAIN = 'number'

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
        _LOGGER.info("Adding number entities for zone %d - %s", zone_id,\
                     extra[CONF_NAME])
        hass.data[DATA_NUVO][DOMAIN].append(NuvoBass(
            NUVO, zone_id, extra[CONF_NAME]))
        hass.data[DATA_NUVO][DOMAIN].append(NuvoTreble(
            NUVO, zone_id, extra[CONF_NAME]))

    async_add_entities(hass.data[DATA_NUVO][DOMAIN], True)

class NuvoBass(NumberEntity):
    """Representation of a Nuvo amplifier zone settings."""

    def __init__(self, nuvo, zone_id, zone_name):
        """Initialize new zone."""
        self._nuvo = NUVO
        self._zone_id = zone_id
        self._name = zone_name

        self._bass = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, 'settings')
        self.update()

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (bass) update called', self._zone_id)
        self.async_schedule_update_ha_state(True)

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zoneset_status(self._zone_id)
        if not state:
            return False
        self._bass = state.bass

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def name(self):
        """Return the name of the zone."""
        return f'{self._name} bass'

    @property
    def native_min_value(self) -> float:
        return float('-12')

    @property
    def native_max_value(self) -> float:
        return float('+12')

    @property
    def native_step(self) -> float:
        return float('2')

    @property
    def native_value(self):
        """Return the current bass level.."""
        return self._bass

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        self._nuvo.set_bass(self._zone_id, value)

class NuvoTreble(NumberEntity):
    """Representation of a Nuvo amplifier zone settings."""

    def __init__(self, nuvo, zone_id, zone_name):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._zone_id = zone_id
        self._name = zone_name

        self._treble = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, 'settings')

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (treble) update called', self._zone_id)
        self.async_schedule_update_ha_state(True)

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zoneset_status(self._zone_id)
        if not state:
            return False
        self._treble = state.treble

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def name(self):
        """Return the name of the zone."""
        return f'{self._name} treble'

    @property
    def native_min_value(self) -> float:
        return float('-12')

    @property
    def native_max_value(self) -> float:
        return float('+12')

    @property
    def native_step(self) -> float:
        return float('2')

    @property
    def native_value(self):
        """Return the current treble level.."""
        return self._treble

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        self._nuvo.set_treble(self._zone_id, value)
