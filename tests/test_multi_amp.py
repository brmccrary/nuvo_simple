"""End-to-end tests: two Nuvo amplifiers as two config entries in Home Assistant."""
import asyncio

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import rx_lines

DOMAIN = 'nuvo_simple'


def _entry_data(port, tag):
    return {
        'port': port,
        'page_source': '6',
        'page_volume': '35',
        'all_off_recall': False,
        'min_offset': '-20',
        'max_offset': '20',
        'sources': {'1': {'name': 'Radio'}, '2': {'name': 'Streamer'}},
        'zones': {'1': {'name': f'{tag} Kitchen'}, '2': {'name': f'{tag} Patio'}},
    }


def _make_entry(port, tag):
    return MockConfigEntry(
        domain=DOMAIN,
        title=f'Nuvo {tag}',
        data=_entry_data(port, tag),
        unique_id=slugify(port),
    )


async def _setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def _settle(hass, seconds=2.0):
    """Let serial round-trips and callback-driven updates land."""
    await asyncio.sleep(seconds)
    await hass.async_block_till_done()


async def test_two_amps_setup_and_route_independently(hass, two_amps):
    link_a, link_b = two_amps
    entry_a = _make_entry(link_a, 'Alpha')
    entry_b = _make_entry(link_b, 'Beta')
    await _setup(hass, entry_a)
    await _setup(hass, entry_b)
    assert entry_a.state is ConfigEntryState.LOADED
    assert entry_b.state is ConfigEntryState.LOADED
    await _settle(hass)

    # Entities from both amps exist side by side
    assert hass.states.get('media_player.alpha_kitchen') is not None
    assert hass.states.get('media_player.beta_kitchen') is not None
    # Model-specific entities: balance numbers only on the Concerto (B),
    # override binary sensors and source-group switches only on the Essentia D (A)
    assert hass.states.get('number.beta_kitchen_balance') is not None
    assert hass.states.get('number.alpha_kitchen_balance') is None
    assert hass.states.get('binary_sensor.alpha_kitchen_override') is not None
    assert hass.states.get('binary_sensor.beta_kitchen_override') is None

    # Friendly names are the bare zone names — no device-name prefix
    # (regression: a single shared amp device made HA prefix every entity
    # with "Nuvo Classic (/dev/…)" and cards showed no zone name)
    assert hass.states.get('media_player.alpha_kitchen') \
        .attributes['friendly_name'] == 'Alpha Kitchen'
    assert hass.states.get('number.alpha_kitchen_bass') \
        .attributes['friendly_name'] == 'Alpha Kitchen bass'

    # Each zone is its own device; zones of different amps are distinct
    registry = er.async_get(hass)
    dev_a = registry.async_get('media_player.alpha_kitchen').device_id
    dev_b = registry.async_get('media_player.beta_kitchen').device_id
    assert dev_a is not None and dev_b is not None and dev_a != dev_b
    # A zone's media player and its settings entities share the zone device
    assert registry.async_get('number.alpha_kitchen_bass').device_id == dev_a

    # Commands route to the correct amp only
    a_before, b_before = len(rx_lines(link_a)), len(rx_lines(link_b))
    await hass.services.async_call(
        'media_player', 'turn_on',
        {'entity_id': 'media_player.beta_kitchen'}, blocking=True)
    await _settle(hass, 1.0)
    assert 'Z01ON' in rx_lines(link_b)[b_before:]
    assert 'Z01ON' not in rx_lines(link_a)[a_before:]

    # State lands on the right entity
    assert hass.states.get('media_player.beta_kitchen').state == 'on'
    assert hass.states.get('media_player.alpha_kitchen').state == 'off'

    # Domain services fan out to every amp
    a_before, b_before = len(rx_lines(link_a)), len(rx_lines(link_b))
    await hass.services.async_call(DOMAIN, 'all_off', {}, blocking=True)
    await _settle(hass, 2.0)
    assert 'ALLOFF' in rx_lines(link_a)[a_before:]
    assert 'ALLOFF' in rx_lines(link_b)[b_before:]

    assert await hass.config_entries.async_unload(entry_a.entry_id)
    assert await hass.config_entries.async_unload(entry_b.entry_id)


async def test_legacy_unique_ids_migrate(hass, two_amps):
    link_a, _ = two_amps
    entry = _make_entry(link_a, 'Alpha')
    entry.add_to_hass(hass)

    # Simulate an entity created by the pre-multi-amp version
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        'media_player', DOMAIN, 'nuvo_simple_zone_1',
        suggested_object_id='alpha_kitchen', config_entry=entry)
    assert old.unique_id == 'nuvo_simple_zone_1'

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await _settle(hass)

    migrated = registry.async_get('media_player.alpha_kitchen')
    assert migrated is not None
    assert migrated.unique_id == f'{entry.entry_id}_zone_1'
    # And the running entity is bound to the migrated registry entry
    assert hass.states.get('media_player.alpha_kitchen') is not None

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_duplicate_port_aborts(hass, two_amps):
    link_a, _ = two_amps
    entry = _make_entry(link_a, 'Alpha')
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': 'user'})
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'],
        {'port': link_a, 'page_source': '6', 'page_volume': '35',
         'all_off_recall': False, 'min_offset': '-20', 'max_offset': '20'})
    assert result['type'] == 'abort'
    assert result['reason'] == 'already_configured'


async def test_unload_one_amp_keeps_the_other(hass, two_amps):
    link_a, link_b = two_amps
    entry_a = _make_entry(link_a, 'Alpha')
    entry_b = _make_entry(link_b, 'Beta')
    await _setup(hass, entry_a)
    await _setup(hass, entry_b)
    await _settle(hass)

    assert await hass.config_entries.async_unload(entry_a.entry_id)
    await hass.async_block_till_done()
    assert entry_a.state is ConfigEntryState.NOT_LOADED
    assert entry_b.state is ConfigEntryState.LOADED
    # Services survive while any amp remains
    assert hass.services.has_service(DOMAIN, 'all_off')

    # Amp B must still respond after A is gone
    b_before = len(rx_lines(link_b))
    await hass.services.async_call(
        'media_player', 'turn_on',
        {'entity_id': 'media_player.beta_kitchen'}, blocking=True)
    await _settle(hass, 1.0)
    assert 'Z01ON' in rx_lines(link_b)[b_before:]

    assert await hass.config_entries.async_unload(entry_b.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, 'all_off')


async def test_port_picker_and_remote_port_title(hass):
    """The port field is HA's serial port picker; network ports get readable titles."""
    from unittest.mock import patch

    from homeassistant.helpers import device_registry as dr

    from custom_components.nuvo_simple import config_flow

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': 'user'})
    port_field = next(k for k in result['data_schema'].schema if k == 'port')
    assert 'serial_port' in result['data_schema'].schema[port_field].serialize()['selector']

    # A serial proxy as ESPHome registers it, before and after the user renames it
    esphome_entry = MockConfigEntry(domain='esphome', title='Serial Proxy')
    esphome_entry.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=esphome_entry.entry_id,
        connections={(dr.CONNECTION_NETWORK_MAC, '02:00:00:1a:2b:3c')},
        manufacturer='Espressif', model='Serial Proxy',
        name='Serial Proxy 1a2b3c')
    proxy_port = f'esphome-hass://esphome/{esphome_entry.entry_id}?port_name=RS-232+Port+1'

    assert await config_flow._async_port_title(hass, proxy_port) == \
        'Nuvo Classic (Serial Proxy 1a2b3c · RS-232 Port 1)'
    dev_reg.async_update_device(device.id, name_by_user='Rack Proxy')
    assert await config_flow._async_port_title(hass, proxy_port) == \
        'Nuvo Classic (Rack Proxy · RS-232 Port 1)'
    # Local paths are already readable and keep the path as the title
    with patch('homeassistant.components.usb.async_scan_serial_ports', return_value=[]):
        assert await config_flow._async_port_title(hass, '/dev/ttyUSB0') == \
            'Nuvo Classic (/dev/ttyUSB0)'


async def test_moving_amp_to_network_port_retitles_entry(hass, two_amps):
    """Changing the port in Configure updates an auto-generated title only."""
    link_a, _ = two_amps
    entry = _make_entry(link_a, 'Alpha')
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, title=f'Nuvo Classic ({link_a})')
    new_port = 'socket://127.0.0.1:1'

    async def _change_port(port):
        with patch_setup():
            flow = await hass.config_entries.options.async_init(entry.entry_id)
            flow = await hass.config_entries.options.async_configure(
                flow['flow_id'], {'port': port})
            flow = await hass.config_entries.options.async_configure(flow['flow_id'], {})
            flow = await hass.config_entries.options.async_configure(flow['flow_id'], {})
        assert flow['type'] == 'create_entry'

    await _change_port(new_port)
    assert entry.title == f'Nuvo Classic ({new_port})'
    assert entry.options['zones'] == entry.data['zones']

    # Setting up the amp's new port again is a duplicate, not a second amp
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={'source': 'user'})
    result = await hass.config_entries.flow.async_configure(
        result['flow_id'],
        {'port': new_port, 'page_source': '6', 'page_volume': '35',
         'all_off_recall': False, 'min_offset': '-20', 'max_offset': '20'})
    assert result['type'] == 'abort'
    assert result['reason'] == 'already_configured'

    hass.config_entries.async_update_entry(entry, title='Basement amp')
    await _change_port(link_a)
    assert entry.title == 'Basement amp'


async def test_title_update_does_not_reload(hass, two_amps):
    """Only real option changes reload the entry.

    A port change in Configure renames the entry and saves options; if both
    reloaded, two setups would race for the port.
    """
    from unittest.mock import AsyncMock, patch

    link_a, _ = two_amps
    entry = _make_entry(link_a, 'Alpha')
    await _setup(hass, entry)
    await _settle(hass)

    with patch.object(hass.config_entries, 'async_reload',
                      AsyncMock(return_value=True)) as reload:
        hass.config_entries.async_update_entry(entry, title='Renamed amp')
        await hass.async_block_till_done()
        assert reload.call_count == 0

        hass.config_entries.async_update_entry(
            entry, options={**entry.data, 'page_volume': '40'})
        await hass.async_block_till_done()
        assert reload.call_count == 1

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def patch_setup():
    from unittest.mock import patch
    return patch('custom_components.nuvo_simple.async_setup_entry', return_value=True)


async def test_waits_for_offline_network_port(hass):
    """A network port whose device is not connected retries quietly."""
    from unittest.mock import patch

    entry = _make_entry('esphome-hass://esphome/01TEST?port_name=RS-232+Port+1', 'Aux')
    entry.add_to_hass(hass)

    # No scanner offers the port: the serial proxy is offline
    with patch('homeassistant.components.usb.async_scan_serial_ports',
               return_value=[]), \
            patch('custom_components.nuvo_simple.get_nuvo') as get_nuvo:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY
    # The driver is never started, so nothing hammers a port that cannot open
    get_nuvo.assert_not_called()


async def test_paging_survives_a_flush_that_never_returns(hass, two_amps):
    """A dropped network port must not wedge the sender (and so the lock)."""
    import threading
    link_a, _ = two_amps
    entry = _make_entry(link_a, 'Alpha')
    await _setup(hass, entry)
    await _settle(hass)

    nuvo = hass.data[DOMAIN][entry.entry_id]['nuvo']
    hang = threading.Event()
    nuvo._port.flush = hang.wait  # what a lost ESPHome connection does
    try:
        await asyncio.wait_for(
            hass.services.async_call(DOMAIN, 'paging_on', {}, blocking=True),
            timeout=15)
        await asyncio.wait_for(
            hass.services.async_call(DOMAIN, 'paging_off', {}, blocking=True),
            timeout=15)
        # Other calls into the amp are not stuck behind the lock either
        await asyncio.wait_for(
            hass.services.async_call(DOMAIN, 'all_off', {}, blocking=True),
            timeout=15)
    finally:
        hang.set()
    await _settle(hass, 1.5)  # ALLOFF holds the sender for a second
    assert await hass.config_entries.async_unload(entry.entry_id)
    await _settle(hass, 0.5)


async def test_grouping_follows_an_entity_id_change(hass, two_amps):
    link_a, _ = two_amps
    entry = _make_entry(link_a, 'Alpha')
    await _setup(hass, entry)
    await _settle(hass)
    nuvo = hass.data[DOMAIN][entry.entry_id]['nuvo']
    media_rows = len(nuvo._media_callback)
    settings_rows = len(nuvo._settings_callback)

    async def join(member):
        await hass.services.async_call(
            'media_player', 'join',
            {'entity_id': 'media_player.alpha_kitchen',
             'group_members': [member]}, blocking=True)
        await _settle(hass, 1.0)

    def members(entity_id):
        return hass.states.get(entity_id).attributes.get('group_members')

    await join('media_player.alpha_patio')
    assert members('media_player.alpha_kitchen') == [
        'media_player.alpha_kitchen', 'media_player.alpha_patio']

    # Renaming a grouped zone and one of its settings entities: before Home
    # Assistant changes entity_ids in place this removes and re-adds them,
    # which must replace the zone's row rather than add a second one
    registry = er.async_get(hass)
    registry.async_update_entity(
        'media_player.alpha_patio', new_entity_id='media_player.alpha_deck')
    registry.async_update_entity(
        'number.alpha_patio_bass', new_entity_id='number.alpha_deck_bass')
    await _settle(hass, 1.0)
    assert len(nuvo._media_callback) == media_rows
    assert len(nuvo._settings_callback) == settings_rows
    assert members('media_player.alpha_kitchen') == [
        'media_player.alpha_kitchen', 'media_player.alpha_deck']

    # The renamed zone can still be joined by its new entity_id
    await hass.services.async_call(
        'media_player', 'unjoin',
        {'entity_id': 'media_player.alpha_deck'}, blocking=True)
    await _settle(hass, 1.0)
    assert members('media_player.alpha_kitchen') == [
        'media_player.alpha_kitchen']
    await join('media_player.alpha_deck')
    assert members('media_player.alpha_kitchen') == [
        'media_player.alpha_kitchen', 'media_player.alpha_deck']

    # In-place change (async_entity_id_changed): the driver follows the new id
    nuvo.update_entity_id('media_player.alpha_deck', 'media_player.alpha_porch')
    await _settle(hass, 1.0)
    assert members('media_player.alpha_kitchen') == [
        'media_player.alpha_kitchen', 'media_player.alpha_porch']

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_overlapping_pages_end_with_the_last_one(hass, two_amps):
    """A page that ends while another is still running leaves the zones paged."""
    from custom_components.nuvo_simple import nuvo as nuvo_module
    link_a, _ = two_amps
    entry = _make_entry(link_a, 'Alpha')
    await _setup(hass, entry)
    await _settle(hass)
    nuvo = hass.data[DOMAIN][entry.entry_id]['nuvo']

    async def page(service):
        before = len(rx_lines(link_a))
        await hass.services.async_call(DOMAIN, service, {}, blocking=True)
        await _settle(hass, 0.5)
        return rx_lines(link_a)[before:]

    assert 'Z01ON' in await page('paging_on')
    assert await page('paging_on') == []     # second page joins the first
    assert await page('paging_off') == []    # first one ends: still paged
    assert 'Z01OFF' in await page('paging_off')

    # A page that was never ended stops counting, so it cannot keep the
    # zones paged after the next page ends
    assert 'Z01ON' in await page('paging_on')
    nuvo._page_holds[0] -= nuvo_module.TIMEOUT_PAGE + 1
    assert await page('paging_on') == []
    assert 'Z01OFF' in await page('paging_off')

    assert await hass.config_entries.async_unload(entry.entry_id)
