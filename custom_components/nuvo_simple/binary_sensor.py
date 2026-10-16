"""Support for interfacing with Nuvo Multi-Zone Amplifier via serial/RS-232."""

import logging

from homeassistant.core import callback
from homeassistant.const import CONF_NAME
from homeassistant.components.binary_sensor import BinarySensorEntity

from . import (
    DOMAIN as COMPONENT_DOMAIN,
    MODEL,
    zone_device_info,
    CONF_ZONES,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up Nuvo binary sensor entities from a config entry."""
    data = hass.data[COMPONENT_DOMAIN][entry.entry_id]
    nuvo = data['nuvo']
    zones = data[CONF_ZONES]
    model = data[MODEL]
    entities = []
    for zone_id, extra in zones.items():
        if model == 'ESSENTIA_D':
            _LOGGER.info("Adding binary sensor entity for zone %d - %s", zone_id, extra[CONF_NAME])
            entities.append(NuvoOverride(nuvo, zone_id, extra[CONF_NAME],
                                         entry.entry_id, model))
    async_add_entities(entities, True)


class NuvoOverride(BinarySensorEntity):
    """Representation of a Nuvo amplifier zone settings."""

    _attr_has_entity_name = True

    def __init__(self, nuvo, zone_id, zone_name, entry_id, model):
        """Initialize new zone."""
        self._nuvo = nuvo
        self._zone_id = zone_id
        self._name = zone_name
        self._attr_unique_id = f"{entry_id}_zone_{zone_id}_override"
        self._attr_name = 'override'
        self._attr_device_info = zone_device_info(entry_id, model, zone_id, zone_name)
        self._override = None

    async def async_added_to_hass(self) -> None:
        self._nuvo.add_callback(self._update_callback, self._zone_id, self._name, 'settings')
        await self.hass.async_add_executor_job(self.update)

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        super().async_entity_id_changed(old_entity_id)

    @callback
    def _update_callback(self):
        _LOGGER.debug('Zone %s settings (override) update called', self._zone_id)
        self.schedule_update_ha_state(True)

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
    def is_on(self):
        return self._override
