# Changelog

## 2.1.0 (2026-08-02)

- Serial I/O no longer blocks the Home Assistant event loop: all blocking `nuvo-simple` calls in async entity methods (`number`, `switch`) and the initial status reads in `async_added_to_hass` (`media_player`, `binary_sensor`, `number`, `switch`) are now offloaded via `async_add_executor_job`
- Added in-tree brand assets at `custom_components/nuvo_simple/brand/` (`icon.png`, `icon@2x.png`) so the integration displays an icon (HA 2026.3+)

## 2.0.3 (2026-07-22)

- Added MIT LICENSE file at the repository root (required for HACS default inclusion)

## 2.0.2 (2026-07-18)

- Fixed documentation and issue tracker links in manifest.json

## 2.0.0 (2026-04-22)

### Breaking Changes
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
