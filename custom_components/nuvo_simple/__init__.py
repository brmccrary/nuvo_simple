"""The nuvo component."""
import logging

import voluptuous as vol

# Import the device class from home assistant component
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.components import zeroconf
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, \
     SOURCE_IMPORT
from homeassistant.const import (
     ATTR_ENTITY_ID, CONF_NAME, CONF_PORT, STATE_OFF, STATE_ON, Platform)
from homeassistant.exceptions import ConfigEntryNotReady, ConfigEntryAuthFailed
from homeassistant.helpers import config_validation as cv, entity_platform, \
     service, discovery

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.MEDIA_PLAYER, Platform.NUMBER, Platform.BINARY_SENSOR, Platform.SWITCH]

# Home Assistant depends on 3rd party packages for API specific code.
REQUIREMENTS = ['nuvo_simple==1.0']

DOMAIN = "nuvo_simple"
DATA_NUVO = "nuvo_simple"

CONF_PAGE_SOURCE = "page_source"
CONF_PAGE_VOLUME = "page_volume"
CONF_ZONE_PAGE_VOLUME = "zone_page_volume"
CONF_PORT = "port"
CONF_BAUD = "baud"
CONF_ZONES = "zones"
CONF_SOURCES = "sources"
CONF_NUVOSYNC = "nuvosync"
MODEL = "model"

DEFAULT_BAUD = "9600"
DEFAULT_PAGE_SOURCE = "6"
DEFAULT_PAGE_VOLUME = "50"

SERVICE_PAGE_ON = 'paging_on'
SERVICE_PAGE_OFF = 'paging_off'
SERVICE_MUTE = 'mute_all'
SERVICE_UNMUTE = 'unmute_all'
SERVICE_ALL_OFF = 'all_off'

PAGE_ZONES = 'page_zones'
ZONE_PAGE_VOLUME = 'zone_page_volume'

ZONE_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
    vol.Optional(CONF_ZONE_PAGE_VOLUME): cv.string,
})

SOURCE_SCHEMA = vol.Schema({
    vol.Required(CONF_NAME): cv.string,
})

# Valid zone ids: 1-12
ZONE_IDS = vol.All(vol.Coerce(int), vol.Any(
    vol.Range(min=1, max=12)))

# Valid source ids: 1-6
SOURCE_IDS = vol.All(vol.Coerce(int), vol.Range(min=1, max=6))

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_PORT): cv.string,
                vol.Optional(CONF_BAUD, default=DEFAULT_BAUD): cv.string,
                vol.Optional(CONF_PAGE_SOURCE, default=DEFAULT_PAGE_SOURCE): cv.string,
                vol.Optional(CONF_PAGE_VOLUME, default=DEFAULT_PAGE_VOLUME): cv.string,
                vol.Required(CONF_ZONES): vol.Schema({ZONE_IDS: ZONE_SCHEMA}),
                vol.Required(CONF_SOURCES): vol.Schema({SOURCE_IDS: SOURCE_SCHEMA}),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

_LOGGER = logging.getLogger(__name__)

from serial import SerialException
from nuvo_simple import get_nuvo

def setup(hass, config):
    conf = config[DOMAIN]
    hass.data[DOMAIN] = {}
    hass.data[DATA_NUVO][PAGE_ZONES] = []
    hass.data[DATA_NUVO][ZONE_PAGE_VOLUME] = []
    port = conf.get(CONF_PORT)
    baud = conf.get(CONF_BAUD)

    try:
        global NUVO
        NUVO = get_nuvo(port, baud)
    except SerialException:
        _LOGGER.error("Error opening serial port")
        return False

    model = NUVO.get_model()
    if model == 'Unknown':
        _LOGGER.error('This does not appear to be a supported Nuvo device.')
        return False
    else:
        _LOGGER.info('Detected Nuvo model %s', model)

    sources = {source_id: extra[CONF_NAME] for source_id, extra
               in conf[CONF_SOURCES].items()}
    hass.data[DOMAIN][CONF_PAGE_VOLUME] = int(conf.get(CONF_PAGE_VOLUME))
    hass.data[DOMAIN][CONF_PAGE_SOURCE] = int(conf.get(CONF_PAGE_SOURCE))
    hass.data[DOMAIN][CONF_SOURCES] = sources
    hass.data[DOMAIN][CONF_ZONES] = conf[CONF_ZONES]
    hass.data[DOMAIN][MODEL] = model
    zones = hass.data[DATA_NUVO][CONF_ZONES]
    page_source = int(hass.data[DATA_NUVO][CONF_PAGE_SOURCE])
    page_volume = hass.data[DATA_NUVO][ZONE_PAGE_VOLUME]
    page_zones = hass.data[DATA_NUVO][PAGE_ZONES]

    for zone_id, extra in zones.items():
        hass.data[DATA_NUVO][PAGE_ZONES].append(zone_id)
        try:
            hass.data[DATA_NUVO][ZONE_PAGE_VOLUME].append(extra[CONF_ZONE_PAGE_VOLUME])
            _LOGGER.info("Adding page zone %d with specific volume %s", \
                         zone_id, extra[CONF_ZONE_PAGE_VOLUME])
        except:
            hass.data[DATA_NUVO][ZONE_PAGE_VOLUME].append(hass.data[DATA_NUVO][CONF_PAGE_VOLUME])
            _LOGGER.info("Adding page zone %d with default volume %s", \
                         zone_id, hass.data[DATA_NUVO][CONF_PAGE_VOLUME])

    for platform in PLATFORMS:
        discovery.load_platform(hass, platform, DOMAIN, {}, config)

    def service_handle(service):
        """Handle for services."""
        _LOGGER.info("Nuvo service handler called.")
        if service.service == SERVICE_PAGE_OFF:
            _LOGGER.info("Paging off service called.")
            NUVO.page_off(page_source, page_zones)
            return

        if service.service == SERVICE_PAGE_ON:
            """Set system up for paging."""
            _LOGGER.info("Paging on service called.")
            NUVO.page_on(page_source, page_zones, page_volume)
            return

        if service.service == SERVICE_MUTE:
            """Mute all zones."""
            _LOGGER.info("Mute All service called.")
            NUVO.mute_all()
            return

        if service.service == SERVICE_UNMUTE:
            """Unmute all zones."""
            _LOGGER.info("Unmute All service called.")
            NUVO.unmute_all()
            return

        if service.service == SERVICE_ALL_OFF:
            """Turn off all zones."""
            _LOGGER.info("All Off service called.")
            NUVO.all_off()
            return

    hass.services.register(
        DOMAIN, SERVICE_PAGE_ON, service_handle, schema=None)

    hass.services.register(
        DOMAIN, SERVICE_PAGE_OFF, service_handle, schema=None)

    hass.services.register(
        DOMAIN, SERVICE_MUTE, service_handle, schema=None)

    hass.services.register(
        DOMAIN, SERVICE_UNMUTE, service_handle, schema=None)

    hass.services.register(
        DOMAIN, SERVICE_ALL_OFF, service_handle, schema=None)

    return True
