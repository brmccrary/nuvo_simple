"""The Nuvo Classic component."""
import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import CONF_NAME, CONF_PORT, Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.SWITCH]

DOMAIN = "nuvo_simple"
DATA_NUVO = "nuvo_simple"

CONF_PAGE_SOURCE = "page_source"
CONF_PAGE_VOLUME = "page_volume"
CONF_ZONE_PAGE_VOLUME = "zone_page_volume"
CONF_PORT = "port"
CONF_BAUD = "baud"
CONF_ZONES = "zones"
CONF_SOURCES = "sources"
CONF_MIN_OFFSET = "min_offset"
CONF_MAX_OFFSET = "max_offset"
CONF_ALL_OFF_RECALL = "all_off_recall"
MODEL = "model"

DEFAULT_BAUD = "9600"
DEFAULT_PAGE_SOURCE = "6"
DEFAULT_PAGE_VOLUME = "35"
DEFAULT_ALL_OFF_RECALL = "no"
DEFAULT_MIN_OFFSET = "-20"
DEFAULT_MAX_OFFSET = "20"

SERVICE_PAGE_ON = "paging_on"
SERVICE_PAGE_OFF = "paging_off"
SERVICE_MUTE = "mute_all"
SERVICE_UNMUTE = "unmute_all"
SERVICE_ALL_OFF = "all_off"

PAGE_ZONES = "page_zones"
ZONE_PAGE_VOLUME = "zone_page_volume"

LEGACY_UNIQUE_ID_PREFIX = "nuvo_simple_zone_"

ZONE_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
    vol.Optional(CONF_ZONE_PAGE_VOLUME): cv.string,
})

SOURCE_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
})

ZONE_IDS = vol.All(vol.Coerce(int), vol.Range(min=1, max=12))
SOURCE_IDS = vol.All(vol.Coerce(int), vol.Range(min=1, max=6))

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_PORT): cv.string,
                vol.Optional(CONF_BAUD, default=DEFAULT_BAUD): cv.string,
                vol.Optional(CONF_PAGE_SOURCE, default=DEFAULT_PAGE_SOURCE): cv.string,
                vol.Optional(CONF_PAGE_VOLUME, default=DEFAULT_PAGE_VOLUME): cv.string,
                vol.Optional(CONF_ALL_OFF_RECALL, default=DEFAULT_ALL_OFF_RECALL): cv.boolean,
                vol.Optional(CONF_MIN_OFFSET, default=DEFAULT_MIN_OFFSET): cv.string,
                vol.Optional(CONF_MAX_OFFSET, default=DEFAULT_MAX_OFFSET): cv.string,
                vol.Required(CONF_ZONES): vol.Schema({ZONE_IDS: ZONE_SCHEMA}),
                vol.Required(CONF_SOURCES): vol.Schema({SOURCE_IDS: SOURCE_SCHEMA}),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

from .nuvo import get_nuvo


# Device registry id of each entry's hub device, recorded in async_setup_entry.
# HA 2026.9 dropped the `via_device` identifier-tuple form of DeviceInfo in
# favour of `via_device_id`, which needs the hub's registry id rather than its
# identifiers, so the id is looked up here instead of at every call site.
_HUB_DEVICE_IDS: dict[str, str] = {}


def zone_device_info(entry_id: str, model: str, zone_id: int, zone_name: str) -> DeviceInfo:
    """Device info for one zone, presented as a child device of the amplifier."""
    info = DeviceInfo(
        identifiers={(DOMAIN, f'{entry_id}_zone_{zone_id}')},
        name=zone_name,
        manufacturer='Nuvo',
        model=model,
    )
    if hub_device_id := _HUB_DEVICE_IDS.get(entry_id):
        info['via_device_id'] = hub_device_id
    return info


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Trigger import flow for users still using configuration.yaml."""
    hass.data.setdefault(DOMAIN, {})
    if DOMAIN in config:
        _LOGGER.warning(
            "Nuvo Classic: configuration.yaml setup is deprecated and will be removed "
            "in a future release. Please remove it from configuration.yaml and use the "
            "UI integration instead (Settings → Integrations → Add Integration → Nuvo Classic)."
        )
        from homeassistant.components.persistent_notification import async_create as pn_create
        pn_create(
            hass,
            "Nuvo Classic is now configured through the UI. "
            "Please remove the `nuvo_simple:` section from your configuration.yaml "
            "and restart Home Assistant. "
            "Go to **Settings → Integrations** to manage the integration.",
            title="Nuvo Classic: Action Required",
            notification_id="nuvo_simple_deprecated_yaml",
        )
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={'source': SOURCE_IMPORT},
                data=config[DOMAIN],
            )
        )
    return True


async def _async_remote_port_available(hass: HomeAssistant, port: str) -> bool:
    """Whether a network serial port is currently offered by its device.

    Local device paths are always considered available; opening those is the
    driver's job and it retries on its own.
    """
    if '://' not in port:
        return True

    from homeassistant.components.usb import async_scan_serial_ports

    try:
        ports = await async_scan_serial_ports(hass)
    except Exception:
        _LOGGER.debug("Serial port scan failed", exc_info=True)
        return True

    # Ports no scanner contributes (socket://, rfc2217://) are never listed
    scanned_schemes = ('esphome-hass://', 'esphome://')
    if not port.startswith(scanned_schemes):
        return True
    return any(p.device == port for p in ports)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Nuvo Classic amplifier from a config entry."""
    conf = {**entry.data, **entry.options}
    port = conf[CONF_PORT]
    baud = conf.get(CONF_BAUD, DEFAULT_BAUD)
    all_off_recall = conf.get(CONF_ALL_OFF_RECALL, False)

    # A network port (e.g. an ESPHome serial proxy) only exists while its
    # device is connected, which on a
    # restart can be after this entry is first set up. Wait for it instead of
    # hammering a port that cannot be opened yet.
    if not await _async_remote_port_available(hass, port):
        raise ConfigEntryNotReady(f"Waiting for the device providing {port} to connect")

    nuvo = await hass.async_add_executor_job(get_nuvo, port, baud, all_off_recall)

    model = await hass.async_add_executor_job(nuvo.get_model)
    if model == 'Unknown':
        await hass.async_add_executor_job(nuvo.close)
        raise ConfigEntryNotReady(f"Cannot detect Nuvo model on {port}")

    _LOGGER.info('Detected Nuvo model %s on %s', model, port)

    zones = {int(k): v for k, v in conf[CONF_ZONES].items()}
    sources = {int(k): v[CONF_NAME] for k, v in conf[CONF_SOURCES].items()}

    page_source = int(conf.get(CONF_PAGE_SOURCE, DEFAULT_PAGE_SOURCE))
    page_volume_default = int(conf.get(CONF_PAGE_VOLUME, DEFAULT_PAGE_VOLUME))

    page_zones = []
    zone_page_volumes = []
    for zone_id, extra in zones.items():
        page_zones.append(zone_id)
        pv = extra.get(CONF_ZONE_PAGE_VOLUME)
        vol_val = int(pv) if pv else page_volume_default
        zone_page_volumes.append(vol_val)
        _LOGGER.info("Page zone %d with volume %d%%", zone_id, vol_val)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        'nuvo': nuvo,
        CONF_PAGE_SOURCE: page_source,
        CONF_PAGE_VOLUME: page_volume_default,
        CONF_MIN_OFFSET: int(conf.get(CONF_MIN_OFFSET, DEFAULT_MIN_OFFSET)),
        CONF_MAX_OFFSET: int(conf.get(CONF_MAX_OFFSET, DEFAULT_MAX_OFFSET)),
        CONF_SOURCES: sources,
        CONF_ZONES: zones,
        MODEL: model,
        PAGE_ZONES: page_zones,
        ZONE_PAGE_VOLUME: zone_page_volumes,
    }

    # The amplifier itself is a hub device; each zone is a child device of it
    # (see zone_device_info) so zones keep their own short names and can be
    # assigned to areas individually.
    hub_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer='Nuvo',
        model=model,
    )
    _HUB_DEVICE_IDS[entry.entry_id] = hub_device.id

    # Migrate pre-multi-amp unique IDs (nuvo_simple_zone_X...) to the
    # entry-scoped scheme so existing entities keep their history.
    @callback
    def _migrate_unique_id(entity_entry):
        old = entity_entry.unique_id
        if old and old.startswith(LEGACY_UNIQUE_ID_PREFIX):
            return {'new_unique_id':
                    f'{entry.entry_id}_zone_{old[len(LEGACY_UNIQUE_ID_PREFIX):]}'}
        return None

    await er.async_migrate_entries(hass, entry.entry_id, _migrate_unique_id)

    def service_handle(service):
        """Handle for services, applied to every configured amplifier."""
        _LOGGER.debug("Nuvo service handler called.")
        for entry_data in list(hass.data.get(DOMAIN, {}).values()):
            _nuvo = entry_data['nuvo']
            _page_source = entry_data[CONF_PAGE_SOURCE]
            _page_zones = entry_data[PAGE_ZONES]
            _page_volume = entry_data[ZONE_PAGE_VOLUME]

            if service.service == SERVICE_PAGE_OFF:
                _LOGGER.info("Paging off service called.")
                _nuvo.page_off(_page_source, _page_zones)

            elif service.service == SERVICE_PAGE_ON:
                _LOGGER.info("Paging on service called.")
                volume_offset = int(service.data.get('volume_offset', 0))
                adjusted_volume = [min(100, max(0, int(v) + volume_offset)) for v in _page_volume]
                _nuvo.page_on(_page_source, _page_zones, adjusted_volume)

            elif service.service == SERVICE_MUTE:
                _LOGGER.info("Mute All service called.")
                _nuvo.mute_all()

            elif service.service == SERVICE_UNMUTE:
                _LOGGER.info("Unmute All service called.")
                _nuvo.unmute_all()

            elif service.service == SERVICE_ALL_OFF:
                _LOGGER.info("All Off service called.")
                _nuvo.all_off()

    if not hass.services.has_service(DOMAIN, SERVICE_PAGE_ON):
        hass.services.async_register(DOMAIN, SERVICE_PAGE_ON, service_handle, schema=None)
        hass.services.async_register(DOMAIN, SERVICE_PAGE_OFF, service_handle, schema=None)
        hass.services.async_register(DOMAIN, SERVICE_MUTE, service_handle, schema=None)
        hass.services.async_register(DOMAIN, SERVICE_UNMUTE, service_handle, schema=None)
        hass.services.async_register(DOMAIN, SERVICE_ALL_OFF, service_handle, schema=None)

    applied_options = dict(entry.options)

    async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
        # Title-only updates (the options flow renaming the entry after a
        # port change) land here too; reload only for real option changes so
        # one save doesn't run two setups back to back.
        if dict(entry.options) != applied_options:
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Remove entities for zones that are no longer configured on this entry
    expected_unique_ids = {f'{entry.entry_id}_zone_0'}
    for zone_id in zones:
        expected_unique_ids.update([
            f'{entry.entry_id}_zone_{zone_id}',
            f'{entry.entry_id}_zone_{zone_id}_bass',
            f'{entry.entry_id}_zone_{zone_id}_treble',
            f'{entry.entry_id}_zone_{zone_id}_volume_offset',
            f'{entry.entry_id}_zone_{zone_id}_balance',
            f'{entry.entry_id}_zone_{zone_id}_source_group',
            f'{entry.entry_id}_zone_{zone_id}_volume_reset',
            f'{entry.entry_id}_zone_{zone_id}_keypad_lock',
            f'{entry.entry_id}_zone_{zone_id}_override',
        ])

    entity_registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity_entry.unique_id not in expected_unique_ids:
            _LOGGER.info("Removing stale entity: %s", entity_entry.entity_id)
            entity_registry.async_remove(entity_entry.entity_id)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        _HUB_DEVICE_IDS.pop(entry.entry_id, None)
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data and data.get('nuvo'):
            await hass.async_add_executor_job(data['nuvo'].close)
        if not hass.data.get(DOMAIN):
            for svc in [SERVICE_PAGE_ON, SERVICE_PAGE_OFF, SERVICE_MUTE, SERVICE_UNMUTE, SERVICE_ALL_OFF]:
                hass.services.async_remove(DOMAIN, svc)
    return unload_ok
