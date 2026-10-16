"""Fixtures for nuvo_simple tests: two emulated amplifiers on pty serial ports."""
import os
import subprocess
import sys

import pytest

# Make the repo root importable so Home Assistant's loader can find
# the custom_components package regardless of pytest's import mode.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

pytest_plugins = "pytest_homeassistant_custom_component"

EMULATOR = os.path.join(os.path.dirname(__file__), '..', 'tools', 'nuvo_emulator.py')


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in all tests.

    pytest-homeassistant-custom-component pre-imports its own bundled
    custom_components package; evict it from sys.modules so Home Assistant's
    loader resolves the import to this repo's custom_components instead.
    """
    for mod in list(sys.modules):
        if mod == 'custom_components' or mod.startswith('custom_components.'):
            del sys.modules[mod]
    yield


def _spawn(link, model):
    return subprocess.Popen(
        [sys.executable, EMULATOR, '--link', link, '--model', model],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def rx_lines(link):
    """Return the commands an emulator has received so far."""
    try:
        with open(link + '.log') as f:
            return [l.split(' RX ', 1)[1].strip() for l in f if ' RX ' in l]
    except FileNotFoundError:
        return []


@pytest.fixture
def two_amps(tmp_path):
    """Two emulated amps: A is an Essentia D, B is a Concerto."""
    link_a = str(tmp_path / 'amp-a')
    link_b = str(tmp_path / 'amp-b')
    procs = [_spawn(link_a, 'ESSENTIA_D'), _spawn(link_b, 'CONCERTO')]
    import time
    time.sleep(0.5)
    yield link_a, link_b
    for p in procs:
        p.terminate()
        p.wait()
