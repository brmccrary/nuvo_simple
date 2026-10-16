# Changelog

## 3.0.0 (2026-10-16)

### New Features
- **Multiple amplifier support** — add the integration once per amplifier (one config entry per serial port). Mixed models (e.g. an Essentia D and a Concerto) are supported.
- **Zones are devices** — each zone is now its own device (named after the zone, child of the amplifier's hub device), so zones can be assigned to Home Assistant areas individually and each zone's media player and settings entities are grouped together. Friendly names are unchanged from 2.x ("Office", "Office bass", …); entities adopt modern `has_entity_name` naming, which avoids Home Assistant 2026-style device-name prefixes leaking into dashboards.
- The `nuvo_simple.paging_on/paging_off/mute_all/unmute_all/all_off` services now apply to every configured amplifier
- Config flow rejects adding the same serial port twice, including a port an existing amp was moved to in **Configure**
- **Network serial ports (ESPHome serial proxy)** — the serial port field is now Home Assistant's serial port picker, listing local ports alongside ESPHome serial proxy ports (e.g. "Serial Proxy (RS-232 Port 1)"). Manual entry of a path or `socket://` URL still works. Entries on a network port are titled after the device and port as shown in the picker (e.g. "Nuvo Classic (Serial Proxy 1a2b3c · RS-232 Port 1)", or your own device name if you renamed it), and changing an amp's port in **Configure** updates the title too unless you renamed the entry.

### Improvements
- The Nuvo serial protocol driver is now vendored inside the integration (formerly the `nuvo-simple` PyPI package) and rewritten with per-instance state so multiple amps cannot interfere with each other. The `numpy` dependency is gone, and `pyserial` has been replaced by [`serialx`](https://github.com/puddly/serialx), the serial library Home Assistant core uses (already installed with Home Assistant).
- Existing entities are migrated to the new per-amp unique ID scheme automatically — entity IDs, history, dashboards, and automations are preserved
- The config flow now closes its probe connection instead of leaking the port
- On a restart, an amplifier on a network port now waits quietly for its device (e.g. an ESPHome serial proxy) to reconnect, instead of logging connection errors until it appears
- If the port goes away while Home Assistant is running (device rebooted or unreachable), the reconnect loop now logs one warning per outage and an info line when it reconnects, instead of an error every 5 seconds
- `paging_on`/`paging_off` once again return only after the amp has received every command when it is on a network port: ESPHome serial proxy writes are queued and return immediately, so each command is now flushed (acknowledged by the device) before the next is paced out. Local serial ports flush with `tcdrain`; `socket://` is unaffected
- Changing a zone's entity ID no longer breaks speaker grouping: joining the renamed zone works, grouped zones report the new ID in `group_members`, and the rename no longer leaves duplicate update callbacks behind. Entities also implement `async_entity_id_changed`, so they are ready for Home Assistant changing entity IDs in place (2026.11) ([#7](https://github.com/brmccrary/nuvo_simple/issues/7))
- Overlapping pages now share the zones: a `paging_off` that arrives while another page is still active leaves the zones paged, and the last `paging_off` restores them. Previously the first page to end restored the zones underneath the one still playing. A page that is never ended stops counting after two minutes
- `paging_on` is faster: zones are set up three at a time, so the pause a zone needs after power-on is spent on the other zones' commands instead of idle. That pause is also longer (0.3 s, was 0.15 s): a zone sent a command too soon after power-on answers as still off and ignores it, e.g. keeps its old source
- Compatible with Home Assistant 2026.9, which turned the deprecated `via_device` device-info parameter into a hard error (zone devices now link to their amplifier via `via_device_id`)
- Added `tools/nuvo_emulator.py`, a hardware-free Nuvo amplifier emulator (pty-based) for development and testing, and a pytest suite (`tests/`) covering two-amp setup, command routing, unique ID migration, and unload behavior

### Breaking Changes
- Requires Home Assistant 2026.5.0 or newer (serial port picker and `serialx`)
- Legacy `platform: nuvo_simple` YAML platform setup (deprecated since 2.0.0) has been removed; the config-entry import path for `nuvo_simple:` YAML remains

## 2.1.0 (2026-08-02)

- Serial I/O no longer blocks the Home Assistant event loop: all blocking `nuvo-simple` calls in async entity methods (`number`, `switch`) and the initial status reads in `async_added_to_hass` (`media_player`, `binary_sensor`, `number`, `switch`) are now offloaded via `async_add_executor_job`
- Added in-tree brand assets at `custom_components/nuvo_simple/brand/` (`icon.png`, `icon@2x.png`) so the integration displays an icon (HA 2026.3+)

## 2.0.3 (2026-07-22)

- Added MIT LICENSE file at the repository root (required for HACS default inclusion)

## 2.0.2 (2026-07-18)

- Fixed documentation and issue tracker links in manifest.json

## 2.0.0 (2026-04-22)

### Breaking Changes
- Requires Home Assistant 2026.5.0 or newer (serial port picker and `serialx`)
- Configuration via `configuration.yaml` is now deprecated. Existing YAML configurations will be automatically imported into the UI on first run. Please remove the `nuvo_simple:` section from `configuration.yaml` after upgrading.

### New Features
- Full UI configuration flow — set up and manage the integration entirely through **Settings → Integrations**, no YAML required
- **Configure** button allows reconfiguring connection settings, sources, and zones at any time without restarting Home Assistant
- Zone enable/disable checkboxes make it clear which zones are active
- Renaming or disabling a zone takes effect immediately — stale entities are automatically removed
- All entities now have unique IDs, enabling full entity registry support (renaming, disabling, history)
- Optional `volume_offset` parameter on the `nuvo_simple.paging_on` service to adjust paging volume at call time

### Improvements
- Paging on/off now blocks until all serial commands complete before returning, making automations that follow paging calls reliable
- Integration reloads cleanly without requiring a full Home Assistant restart
- Display name updated to **Nuvo Classic**

## 1.x

Initial releases with configuration.yaml-based setup.
