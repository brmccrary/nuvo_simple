# Changelog

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
