"""Support for interfacing with Nuvo Multi-Zone Amplifier via serial/RS-232."""

import logging

from homeassistant.core import callback
from homeassistant.components.number import NumberEntity
from homeassistant.const import CONF_NAME

from . import (
    DOMAIN as COMPONENT_DOMAIN,
    MODEL,
    zone_device_info,
    CONF_ZONES,
    CONF_MIN_OFFSET,
    CONF_MAX_OFFSET,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Nuvo number entities from a config entry."""
    data = hass.data[COMPONENT_DOMAIN][entry.entry_id]
    nuvo = data['nuvo']
    zones = data[CONF_ZONES]
    min_offset = int(data[CONF_MIN_OFFSET])
    max_offset = int(data[CONF_MAX_OFFSET])
    model = data[MODEL]
    entities = []
    for zone_id, extra in zones.items():
        _LOGGER.info("Adding number entities for zone %d - %s", zone_id, extra[CONF_NAME])
        entities.append(NuvoBass(nuvo, zone_id, extra[CONF_NAME],
                                 entry.entry_id, model))
        entities.append(NuvoTreble(nuvo, zone_id, extra[CONF_NAME],
                                   entry.entry_id, model))
        entities.append(NuvoVolumeOffset(nuvo, zone_id, extra[CONF_NAME],
                                         min_offset, max_offset,
                                         entry.entry_id, model))
        if model == 'CONCERTO':
            entities.append(NuvoBalance(nuvo, zone_id, extra[CONF_NAME],
                                        entry.entry_id, model))
    async_add_entities(entities, True)


class NuvoBass(NumberEntity):
    """Representation of a Nuvo amplifier zone settings."""

    _attr_has_entity_name = True

    def __init__(self, nuvo, zone_id, zone_name, entry_id, model):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._zone_id = zone_id
        self._name = zone_name
        self._attr_unique_id = f"{entry_id}_zone_{zone_id}_bass"
        self._attr_name = 'bass'
        self._attr_device_info = zone_device_info(entry_id, model, zone_id, zone_name)

        self._bass = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self._name, 'settings')
        await self.hass.async_add_executor_job(self.update)

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (bass) update called', self._zone_id)
        self.schedule_update_ha_state(True)

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
        await self.hass.async_add_executor_job(self._nuvo.set_bass, self._zone_id, value)


class NuvoTreble(NumberEntity):
    """Representation of a Nuvo amplifier zone settings."""

    _attr_has_entity_name = True

    def __init__(self, nuvo, zone_id, zone_name, entry_id, model):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._zone_id = zone_id
        self._name = zone_name
        self._attr_unique_id = f"{entry_id}_zone_{zone_id}_treble"
        self._attr_name = 'treble'
        self._attr_device_info = zone_device_info(entry_id, model, zone_id, zone_name)

        self._treble = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self._name, 'settings')

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (treble) update called', self._zone_id)
        self.schedule_update_ha_state(True)

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
        await self.hass.async_add_executor_job(self._nuvo.set_treble, self._zone_id, value)


class NuvoVolumeOffset(NumberEntity):
    """Representation of a Nuvo amplifier zone settings."""

    _attr_has_entity_name = True

    def __init__(self, nuvo, zone_id, zone_name, min_offset, max_offset,
                 entry_id, model):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._zone_id = zone_id
        self._name = zone_name
        self._min_offset = min_offset
        self._max_offset = max_offset
        self._attr_unique_id = f"{entry_id}_zone_{zone_id}_volume_offset"
        self._attr_name = 'volume offset'
        self._attr_device_info = zone_device_info(entry_id, model, zone_id, zone_name)

        self._volume_offset = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self._name, 'settings')

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (volume offset) update called', self._zone_id)
        self.schedule_update_ha_state(True)

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zoneset_status(self._zone_id)
        if not state:
            return False
        self._volume_offset = state.volume_offset

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def native_min_value(self) -> float:
        return float(self._min_offset)

    @property
    def native_max_value(self) -> float:
        return float(self._max_offset)

    @property
    def native_step(self) -> float:
        return float('1')

    @property
    def native_value(self):
        """Return the current treble level.."""
        return self._volume_offset

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.hass.async_add_executor_job(self._nuvo.set_volume_offset, self._zone_id, value)


class NuvoBalance(NumberEntity):
    """Representation of a Nuvo amplifier zone settings."""

    _attr_has_entity_name = True

    def __init__(self, nuvo, zone_id, zone_name, entry_id, model):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._zone_id = zone_id
        self._name = zone_name
        self._attr_unique_id = f"{entry_id}_zone_{zone_id}_balance"
        self._attr_name = 'balance'
        self._attr_device_info = zone_device_info(entry_id, model, zone_id, zone_name)

        self._balance = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self._name, 'settings')
        await self.hass.async_add_executor_job(self.update)

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (balance) update called', self._zone_id)
        self.schedule_update_ha_state(True)

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zoneset_status(self._zone_id)
        if not state:
            return False
        self._balance = state.balance

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def native_min_value(self) -> float:
        return float('-6')

    @property
    def native_max_value(self) -> float:
        return float('+6')

    @property
    def native_step(self) -> float:
        return float('1')

    @property
    def native_value(self):
        """Return the current balance level.."""
        return self._balance

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        _LOGGER.debug('Zone %s set balance %s', self._zone_id, value)
        await self.hass.async_add_executor_job(self._nuvo.set_balance, self._zone_id, value)
