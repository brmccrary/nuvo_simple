"""Support for interfacing with Nuvo Multi-Zone Amplifier via serial/RS-232."""

import logging

from homeassistant.core import callback
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import CONF_NAME

from . import (
    DOMAIN as COMPONENT_DOMAIN,
    MODEL,
    zone_device_info,
    CONF_ZONES,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Nuvo switch entities from a config entry."""
    data = hass.data[COMPONENT_DOMAIN][entry.entry_id]
    nuvo = data['nuvo']
    zones = data[CONF_ZONES]
    model = data[MODEL]
    entities = []
    for zone_id, extra in zones.items():
        _LOGGER.info("Adding switch entities for zone %d - %s", zone_id, extra[CONF_NAME])
        if model != 'CONCERTO':
            entities.append(NuvoGroup(nuvo, zone_id, extra[CONF_NAME],
                                      entry.entry_id, model))
        if model == 'ESSENTIA_D':
            entities.append(NuvoVolumeReset(nuvo, zone_id, extra[CONF_NAME],
                                            entry.entry_id, model))
        if model != 'CONCERTO':
            entities.append(NuvoKeypadLock(nuvo, zone_id, extra[CONF_NAME],
                                           entry.entry_id, model))
    async_add_entities(entities, True)


class NuvoGroup(SwitchEntity):
    """Representation of a Nuvo amplifier zone settings."""

    _attr_has_entity_name = True

    def __init__(self, nuvo, zone_id, zone_name, entry_id, model):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._zone_id = zone_id
        self._name = zone_name
        self._attr_unique_id = f"{entry_id}_zone_{zone_id}_source_group"
        self._attr_name = 'source group'
        self._attr_device_info = zone_device_info(entry_id, model, zone_id, zone_name)
        self._group = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self._name, 'settings')
        await self.hass.async_add_executor_job(self.update)

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (group) update called', self._zone_id)
        self.schedule_update_ha_state(True)

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zoneset_status(self._zone_id)
        if not state:
            self._group = None
            return None
        else:
            self._group = state.group

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def is_on(self):
        return self._group

    async def async_turn_on(self):
        """Send the on command."""
        await self.hass.async_add_executor_job(self._nuvo.set_group, self._zone_id, True)

    async def async_turn_off(self):
        """Send the off command."""
        await self.hass.async_add_executor_job(self._nuvo.set_group, self._zone_id, False)


class NuvoVolumeReset(SwitchEntity):
    """Representation of a Nuvo amplifier zone settings."""

    _attr_has_entity_name = True

    def __init__(self, nuvo, zone_id, zone_name, entry_id, model):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._zone_id = zone_id
        self._name = zone_name
        self._attr_unique_id = f"{entry_id}_zone_{zone_id}_volume_reset"
        self._attr_name = 'volume reset'
        self._attr_device_info = zone_device_info(entry_id, model, zone_id, zone_name)

        self._volume_reset = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self._name, 'settings')

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (volume reset) update called', self._zone_id)
        self.schedule_update_ha_state(True)

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zoneset_status(self._zone_id)
        if not state:
            self._volume_reset = None
            return None
        else:
            self._volume_reset = state.volume_reset

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def is_on(self):
        return self._volume_reset

    async def async_turn_on(self):
        """Send the on command."""
        await self.hass.async_add_executor_job(self._nuvo.set_volume_reset, self._zone_id, True)

    async def async_turn_off(self):
        """Send the off command."""
        await self.hass.async_add_executor_job(self._nuvo.set_volume_reset, self._zone_id, False)


class NuvoKeypadLock(SwitchEntity):
    """Representation of a Nuvo amplifier zone settings."""

    _attr_has_entity_name = True

    def __init__(self, nuvo, zone_id, zone_name, entry_id, model):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._zone_id = zone_id
        self._name = zone_name
        self._attr_unique_id = f"{entry_id}_zone_{zone_id}_keypad_lock"
        self._attr_name = 'keypad lock'
        self._attr_device_info = zone_device_info(entry_id, model, zone_id, zone_name)

        self._keypad_lock = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self._name, 'settings')

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (keypad lock) update called', self._zone_id)
        self.schedule_update_ha_state(True)

    def update(self):
        """Retrieve latest state."""
        state = self._nuvo.zoneset_status(self._zone_id)
        if not state:
            self._keypad_lock = None
            return None
        else:
            self._keypad_lock = state.keypad_lock

    @property
    def should_poll(self):
        """Disable polling."""
        return False

    @property
    def is_on(self):
        return self._keypad_lock

    async def async_turn_on(self):
        """Send the on command."""
        await self.hass.async_add_executor_job(self._nuvo.set_keypad_lock, self._zone_id, True)

    async def async_turn_off(self):
        """Send the off command."""
        await self.hass.async_add_executor_job(self._nuvo.set_keypad_lock, self._zone_id, False)
