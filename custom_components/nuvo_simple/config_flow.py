"""Config flow for Nuvo Classic."""
import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import SerialPortSelector
from homeassistant.util import slugify
from yarl import URL

from . import (
    DOMAIN,
    CONF_BAUD, CONF_PAGE_SOURCE, CONF_PAGE_VOLUME, CONF_ALL_OFF_RECALL,
    CONF_MIN_OFFSET, CONF_MAX_OFFSET, CONF_ZONES, CONF_SOURCES,
    CONF_ZONE_PAGE_VOLUME,
    DEFAULT_BAUD, DEFAULT_PAGE_SOURCE, DEFAULT_PAGE_VOLUME,
    DEFAULT_MIN_OFFSET, DEFAULT_MAX_OFFSET,
)

_LOGGER = logging.getLogger(__name__)


def _remote_port_label(hass: HomeAssistant, port: str) -> str | None:
    """Readable name for an ESPHome serial proxy port, as the port picker shows it.

    e.g. "Serial Proxy 1a2b3c · RS-232 Port 1", using the name
    the user gave the device in Home Assistant if they renamed it.
    """
    url = URL(port)
    if url.scheme != 'esphome-hass':
        return None
    port_name = url.query.get('port_name')
    esphome_entry_id = url.path.lstrip('/')
    if not port_name or not esphome_entry_id:
        return None
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), esphome_entry_id)
    device = next(
        (d for d in devices if d.primary_config_entry == esphome_entry_id),
        devices[0] if devices else None,
    )
    if device is None:
        return port_name
    return f"{device.name_by_user or device.name} · {port_name}"


async def _async_port_title(hass: HomeAssistant, port: str) -> str:
    """Entry title naming the amplifier's port in words rather than a URL."""
    from homeassistant.components.usb import async_scan_serial_ports

    if (label := _remote_port_label(hass, port)) is not None:
        return f"Nuvo Classic ({label})"
    if '://' in port:
        try:
            for device in await async_scan_serial_ports(hass):
                if device.device == port and device.description:
                    return f"Nuvo Classic ({device.description})"
        except Exception:
            _LOGGER.debug("Serial port scan failed", exc_info=True)
    return f"Nuvo Classic ({port})"


def _connection_schema(data):
    return vol.Schema({
        # Picker lists local serial ports and network ports such as ESPHome
        # serial proxies; manual entry still takes socket:// URLs.
        vol.Required(CONF_PORT, default=data.get(CONF_PORT, vol.UNDEFINED)): SerialPortSelector(),
        vol.Optional(CONF_PAGE_SOURCE, default=data.get(CONF_PAGE_SOURCE, DEFAULT_PAGE_SOURCE)): vol.In(['1','2','3','4','5','6']),
        vol.Optional(CONF_PAGE_VOLUME, default=data.get(CONF_PAGE_VOLUME, DEFAULT_PAGE_VOLUME)): str,
        vol.Optional(CONF_ALL_OFF_RECALL, default=data.get(CONF_ALL_OFF_RECALL, False)): bool,
        vol.Optional(CONF_MIN_OFFSET, default=data.get(CONF_MIN_OFFSET, DEFAULT_MIN_OFFSET)): str,
        vol.Optional(CONF_MAX_OFFSET, default=data.get(CONF_MAX_OFFSET, DEFAULT_MAX_OFFSET)): str,
    })


def _sources_schema(data):
    existing = data.get(CONF_SOURCES, {})
    schema = {}
    for i in range(1, 7):
        default = existing.get(str(i), {}).get(CONF_NAME, '')
        schema[vol.Optional(f'source_{i}', default=default)] = str
    return vol.Schema(schema)


def _zones_schema(data):
    existing = data.get(CONF_ZONES, {})
    schema = {}
    for i in range(1, 13):
        default_enabled = str(i) in existing
        default_name = existing.get(str(i), {}).get(CONF_NAME, f'Zone {i}')
        default_vol = existing.get(str(i), {}).get(CONF_ZONE_PAGE_VOLUME, '')
        schema[vol.Optional(f'zone_{i}_enabled', default=default_enabled)] = bool
        schema[vol.Optional(f'zone_{i}_name', default=default_name)] = str
        schema[vol.Optional(f'zone_{i}_page_volume', default=default_vol)] = str
    return vol.Schema(schema)


def _parse_sources(user_input):
    sources = {}
    for i in range(1, 7):
        name = user_input.get(f'source_{i}', '').strip()
        if name:
            sources[str(i)] = {CONF_NAME: name}
    return sources


def _parse_zones(user_input):
    zones = {}
    for i in range(1, 13):
        if not user_input.get(f'zone_{i}_enabled', False):
            continue
        name = user_input.get(f'zone_{i}_name', '').strip() or f'Zone {i}'
        zone_data = {CONF_NAME: name}
        page_vol = user_input.get(f'zone_{i}_page_volume', '').strip()
        if page_vol:
            zone_data[CONF_ZONE_PAGE_VOLUME] = page_vol
        zones[str(i)] = zone_data
    return zones


class NuvoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Nuvo Classic."""

    VERSION = 1

    def __init__(self):
        self._data = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return NuvoOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial connection step."""
        errors = {}
        if user_input is not None:
            # One config entry per serial port; a second amp on a different
            # port is allowed, the same port twice is not.
            await self.async_set_unique_id(slugify(user_input[CONF_PORT]))
            self._abort_if_unique_id_configured()
            # The unique ID records the port an entry was created with; an amp
            # since moved to another port in Configure is matched here.
            for entry in self._async_current_entries(include_ignore=False):
                if {**entry.data, **entry.options}.get(CONF_PORT) == user_input[CONF_PORT]:
                    return self.async_abort(reason='already_configured')
            try:
                from .nuvo import get_nuvo
                nuvo = await self.hass.async_add_executor_job(
                    get_nuvo,
                    user_input[CONF_PORT],
                    9600,
                    user_input[CONF_ALL_OFF_RECALL],
                )
                try:
                    model = await self.hass.async_add_executor_job(nuvo.get_model)
                finally:
                    await self.hass.async_add_executor_job(nuvo.close)
                if model == 'Unknown':
                    errors['base'] = 'cannot_detect_model'
                else:
                    self._data.update(user_input)
                    self._data['model'] = model
                    return await self.async_step_sources()
            except Exception:
                _LOGGER.exception("Error connecting to Nuvo")
                errors['base'] = 'cannot_connect'

        return self.async_show_form(
            step_id='user',
            data_schema=_connection_schema(self._data),
            errors=errors,
        )

    async def async_step_sources(self, user_input=None):
        """Handle the sources configuration step."""
        errors = {}
        if user_input is not None:
            sources = _parse_sources(user_input)
            if not sources:
                errors['base'] = 'no_sources'
            else:
                self._data[CONF_SOURCES] = sources
                return await self.async_step_zones()

        return self.async_show_form(
            step_id='sources',
            data_schema=_sources_schema(self._data),
            errors=errors,
        )

    async def async_step_zones(self, user_input=None):
        """Handle the zones configuration step."""
        errors = {}
        if user_input is not None:
            zones = _parse_zones(user_input)
            if not zones:
                errors['base'] = 'no_zones'
            else:
                self._data[CONF_ZONES] = zones
                return self.async_create_entry(
                    title=await _async_port_title(self.hass, self._data[CONF_PORT]),
                    data=self._data,
                )

        return self.async_show_form(
            step_id='zones',
            data_schema=_zones_schema(self._data),
            errors=errors,
        )

    async def async_step_import(self, import_data):
        """Import configuration from configuration.yaml."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        sources = {}
        for source_id, extra in import_data.get(CONF_SOURCES, {}).items():
            sources[str(source_id)] = {
                CONF_NAME: extra[CONF_NAME] if isinstance(extra, dict) else str(extra)
            }

        zones = {}
        for zone_id, extra in import_data.get(CONF_ZONES, {}).items():
            zones[str(zone_id)] = dict(extra)

        entry_data = {
            CONF_PORT: import_data[CONF_PORT],
            CONF_BAUD: import_data.get(CONF_BAUD, DEFAULT_BAUD),
            CONF_PAGE_SOURCE: import_data.get(CONF_PAGE_SOURCE, DEFAULT_PAGE_SOURCE),
            CONF_PAGE_VOLUME: import_data.get(CONF_PAGE_VOLUME, DEFAULT_PAGE_VOLUME),
            CONF_ALL_OFF_RECALL: import_data.get(CONF_ALL_OFF_RECALL, False),
            CONF_MIN_OFFSET: import_data.get(CONF_MIN_OFFSET, DEFAULT_MIN_OFFSET),
            CONF_MAX_OFFSET: import_data.get(CONF_MAX_OFFSET, DEFAULT_MAX_OFFSET),
            CONF_SOURCES: sources,
            CONF_ZONES: zones,
        }

        return self.async_create_entry(
            title=f"Nuvo Classic ({import_data[CONF_PORT]})",
            data=entry_data,
        )


class NuvoOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options for Nuvo Classic."""

    def __init__(self, config_entry):
        self._entry = config_entry
        self._data = {**config_entry.data, **config_entry.options}

    async def _async_retitle_for_port(self):
        """Follow a port change in the title, unless the user renamed the entry."""
        old_port = {**self._entry.data, **self._entry.options}[CONF_PORT]
        new_port = self._data[CONF_PORT]
        if new_port == old_port:
            return
        generated = {f"Nuvo Classic ({old_port})",
                     await _async_port_title(self.hass, old_port)}
        if self._entry.title in generated:
            self.hass.config_entries.async_update_entry(
                self._entry, title=await _async_port_title(self.hass, new_port))

    async def async_step_init(self, user_input=None):
        """Handle connection settings."""
        errors = {}
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_sources()

        return self.async_show_form(
            step_id='init',
            data_schema=_connection_schema(self._data),
            errors=errors,
        )

    async def async_step_sources(self, user_input=None):
        """Handle sources configuration."""
        errors = {}
        if user_input is not None:
            sources = _parse_sources(user_input)
            if not sources:
                errors['base'] = 'no_sources'
            else:
                self._data[CONF_SOURCES] = sources
                return await self.async_step_zones()

        return self.async_show_form(
            step_id='sources',
            data_schema=_sources_schema(self._data),
            errors=errors,
        )

    async def async_step_zones(self, user_input=None):
        """Handle zones configuration."""
        errors = {}
        if user_input is not None:
            zones = _parse_zones(user_input)
            if not zones:
                errors['base'] = 'no_zones'
            else:
                self._data[CONF_ZONES] = zones
                await self._async_retitle_for_port()
                return self.async_create_entry(title='', data=self._data)

        return self.async_show_form(
            step_id='zones',
            data_schema=_zones_schema(self._data),
            errors=errors,
        )
