"""Nuvo amplifier serial protocol driver.

Vendored from the former standalone nuvo-simple PyPI package and rewritten
so that all state lives on the NuvoSync instance instead of module globals,
allowing multiple amplifiers (one instance per serial port) in one process.
"""
import logging
import queue
import re
import threading
import time
from functools import wraps
from threading import RLock

import serialx

_LOGGER = logging.getLogger(__name__)

'''
#ZxxPWRppp,SRCs,GRPt,VOL-yy
'''
CONSR_PATTERN = re.compile('Z(?P<zone>\\d{2})'
                     'PWR(?P<power>ON|OFF),'
                     'SRC(?P<source>\\d),'
                     'GRP(?P<group>0|1),'
                     'VOL(?P<volume>-\\d\\d|-MT|-XM)')
'''
#ZzzPWRonoff,SRCs,VOLvvv
'''
STATUS_PATTERN = re.compile('Z(?P<zone>\\d{2})'
                     'PWR(?P<power>ON|OFF),'
                     'SRC(?P<source>\\d),'
                     'VOL(?P<volume>-\\d\\d|-MT|-XM)')
'''
#ZzzPWROFF
'''
SIMPLESE_OFF_PATTERN = re.compile('Z(?P<zone>\\d{2})'
                     'PWR(?P<power>ON|OFF)')
'''
#ZxxORp,BASSyy,TREByy,GRPq,VRSTr
'''
ESSENTIA_D_SETSR_PATTERN = re.compile('Z(?P<zone>\\d{2})'
                     'OR(?P<override>\\d),'
                     'BASS(?P<bass>[+-]?\\d{2}),'
                     'TREB(?P<treble>[+-]?\\d{2}),'
                     'GRP(?P<group>0|1),'
                     'VRST(?P<volume_reset>1|0)')
'''
#Z0x,BASSyy,TREByy,GRPq
'''
SIMPLESE_SETSR_PATTERN = re.compile('Z(?P<zone>\\d{2})'
                     '(?P<override>.)'
                     'BASS(?P<bass>[+-]?\\d{2}),'
                     'TREB(?P<treble>[+-]?\\d{2}),'
                     'GRP(?P<group>0|1)')
'''
#ZzzBASSequ,TREBequ,BALbal,Gg,MAXVOLmax,INIVOLini
'''
CONCERTO_SETSR_PATTERN = re.compile('Z(?P<zone>\\d{2})'
                     'BASS(?P<bass>[+-]?\\d{2}),'
                     'TREB(?P<treble>[+-]?\\d{2}),'
                     'BAL(?P<balance>C|L+\\d|R+\\d),'
                     'G(?P<group>\\d),'
                     'MAXVOL(?P<maxvol>-\\d\\d),'
                     'INIVOL(?P<inivol>-\\d\\d)')
ESSENTIA_D_VERSION = re.compile('MPU_E6D[A-Za-z\t .]+')
SIMPLESE_VERSION = re.compile('MPU_A4D[A-Za-z\t .]+')
CONCERTO_VERSION = re.compile('MPU-I8_[A-Za-z\t .]+')
CONCERTO_VERSION2 = re.compile('NV-I8G[A-Za-z\t .]+')
ALL_OFF_PATTERN = re.compile('ALLOFF')
'''
#ZxxLKlll
'''
KEYPAD_LOCK_PATTERN = re.compile('Z(?P<zone>\\d{2})'
                     'LK(?P<lock>ON|OFF)')
ERROR_PATTERN = re.compile('\\?')

EOL = b'\r'
TIMEOUT_OP       = 0.2   # Number of seconds before serial operation timeout
TIMEOUT_RESPONSE = 1     # Number of seconds before command response timeout
TIMEOUT_FLUSH    = 2     # Seconds to wait for a port to confirm a write went out
POWER_UP_WAIT    = 0.3   # Seconds a zone needs after power-on before its next command
PAGE_GROUP       = 3     # Zones set up together when paging (fills POWER_UP_WAIT)
TIMEOUT_PAGE     = 120   # Seconds before a page that was never ended stops counting
NUM_ZONES = 20           # State arrays are indexed 0..20 (0 = group controller)


def _is_int(s):
    try:
        int(s)
        return True
    except ValueError:
        return False


def db_to_percent(db):
    if int(db) > -24:
        return int((( int(db) + 24) / 24 / 2 +.5) * 100)
    else:
        return int((( int(db) + 78) / 54 / 2) * 100)


def percent_to_db(percent):
    if percent > 50:
        return int(((percent / 100) * 48) - 48)
    else:
        return int(((percent / 100) * 108) - 78)


def _synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper


class ZoneStatus:
    """Snapshot of a zone's playback state."""

    def __init__(self, zone, power, source, volume, mute, zonegroup_members):
        self.zone = zone
        self.power = power
        self.source = str(source)
        self.volume = volume
        self.mute = mute
        self.zonegroup_members = zonegroup_members


class ZonesetStatus:
    """Snapshot of a zone's settings (Essentia D / Simplese)."""

    def __init__(self, zone, bass, treble, override, volume_reset, group,
                 keypad_lock, volume_offset):
        self.zone = zone
        self.bass = bass
        self.treble = treble
        self.override = override
        self.volume_reset = volume_reset
        self.group = group
        self.keypad_lock = keypad_lock
        self.volume_offset = volume_offset


class ConcertoZonesetStatus:
    """Snapshot of a zone's settings (Concerto)."""

    def __init__(self, zone, bass, treble, balance, volume_offset):
        self.zone = zone
        self.bass = bass
        self.treble = treble
        self.balance = balance
        self.volume_offset = volume_offset


class NuvoSync:
    """Synchronous interface to one Nuvo amplifier on one serial port."""

    def __init__(self, port_url, baud, all_off_recall):
        self._port_url = port_url
        self._baud = baud
        self._all_off_recall = all_off_recall

        self._lock = RLock()
        self._cmd_queue = queue.Queue()
        self._port = None
        self._unflushable = None
        self._model = None
        self._listen_active = True
        self._setup = False

        n = NUM_ZONES + 1
        self._zoneinit = [0] * n
        self._zoneinit[0] = 1
        self._zonesetinit = [0] * n
        self._zonepwr = [0] * n
        self._zonepwrsave = [0] * n
        self._zonepwralloff = [0] * n
        self._zonevol = [-78] * n
        self._zonevolsave = [-78] * n
        self._zonesrc = [1] + [0] * NUM_ZONES
        self._zonesrcsave = [0] + [1] * NUM_ZONES
        self._zonemute = [0] * n
        self._zonemutesave = [0] * n
        self._zonelock = [0] * n
        self._zonebass = [0] * n
        self._zonetreble = [0] * n
        self._zonebalance = [0] * n
        self._zonegroupsrc = [1] * n
        self._zoneoverride = [0] * n
        self._zonevolreset = [0] + [1] * NUM_ZONES
        self._zonevoloffset = [0] * n

        self._media_zonetable = []
        self._media_callback = []
        self._settings_zonetable = []
        self._settings_callback = []
        self._entitytable = []
        self._groupzone_members = []

        self._page_active = [0, 0]
        self._page_holds = []

        self._send_thread = threading.Thread(
            target=self._send_loop, daemon=True,
            name=f'nuvo-send-{port_url}')
        self._listen_thread = threading.Thread(
            target=self._listen_loop, daemon=True,
            name=f'nuvo-listen-{port_url}')
        self._send_thread.start()
        self._listen_thread.start()

    # ---- lifecycle -------------------------------------------------------

    def close(self):
        self._listen_active = False
        self._cmd_queue.put(None)
        # Let the listener's timed read return before closing the port under
        # it: remote (ESPHome) ports stop their I/O loop on close, which
        # would strand a read still in flight.
        if threading.current_thread() is not self._listen_thread:
            self._listen_thread.join(timeout=5)
        port = self._port
        if port:
            try:
                port.close()
            except Exception:
                pass

    def get_model(self):
        findmodelcount = 0
        while findmodelcount < 10:
            self._process_request('VER')
            time.sleep(TIMEOUT_RESPONSE)
            if self._model is not None:
                break
            findmodelcount += 1
        if self._model is None:
            _LOGGER.error('This does not appear to be a supported Nuvo device.')
            self._model = 'Unknown'
        return self._model

    # ---- serial I/O threads ----------------------------------------------

    def _process_request(self, request: str):
        self._cmd_queue.put(request)

    def _send_loop(self):
        # Wait for the listener to open the port before the first send
        deadline = time.time() + 15
        while self._port is None and self._listen_active and time.time() < deadline:
            time.sleep(0.05)
        zone_ready = {}
        while True:
            request = self._cmd_queue.get(block=True)
            if request is None:
                self._cmd_queue.task_done()
                return
            lineout = '*' + request + '\r'
            _LOGGER.debug('Sending "%s"', request)
            try:
                # A zone that was just powered on is not ready for its next
                # command yet; commands to other zones can go in the meantime
                zone = request[:3]
                wait = zone_ready.get(zone, 0) - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                port = self._port
                port.write(lineout.encode())
                # A network port (ESPHome serial proxy) only queues the write;
                # flush returns once the device acknowledges the bytes went
                # out, so the pacing below and page_on/page_off's queue join
                # track what the amp has actually received.
                self._flush(port)
                if request == 'ALLOFF':
                    time.sleep(1) # Nuvo does NOT process commands immediately after ALLOFF
                if request[3:5] == 'ON':
                    # Sent sooner, the zone answers as still off and
                    # ignores the command (e.g. keeps its old source)
                    zone_ready[zone] = time.monotonic() + POWER_UP_WAIT
                time.sleep(0.1)  # Must wait in between commands for MPU to process
            except Exception:
                if self._listen_active:
                    _LOGGER.error('Unexpected port error when sending command.')
            self._cmd_queue.task_done()

    def _flush(self, port):
        """Flush a port, giving up if it does not return.

        A network port's flush never returns when its connection drops
        while the flush is in flight. This thread must not hang on that:
        page_on/page_off wait on the queue while holding the lock, so a
        stuck sender would block every later call into the amp.
        """
        if port is self._unflushable:
            return
        done = threading.Event()

        def run():
            try:
                port.flush()
            except Exception:
                pass
            done.set()

        threading.Thread(target=run, daemon=True,
                         name=f'nuvo-flush-{self._port_url}').start()
        if not done.wait(TIMEOUT_FLUSH):
            # Stop flushing this handle; the listener reopens the port
            self._unflushable = port
            if self._listen_active:
                _LOGGER.warning('Flush of %s timed out, connection lost?',
                                self._port_url)

    def _listen_loop(self):
        _LOGGER.info('Attempting connection - "%s" at %s baud',
                     self._port_url, self._baud)
        # Warn once per outage; a network port's device can be gone for hours
        port_down = False
        while self._listen_active:
            try:
                # serialx resolves local devices, socket:// and remote ports
                # such as an ESPHome serial proxy (esphome-hass://). The read
                # timeout lets this loop notice close() instead of blocking.
                port = serialx.serial_for_url(
                    self._port_url,
                    baudrate=int(self._baud),
                    byte_size=8,
                    parity=serialx.Parity.NONE,
                    stopbits=serialx.StopBits.ONE,
                    read_timeout=1,
                )
                port.open()
            except Exception:
                if not self._listen_active:
                    return
                if port_down:
                    _LOGGER.debug('Cannot open %s, retrying in 5 seconds',
                                  self._port_url)
                else:
                    _LOGGER.warning('Cannot open %s, retrying every 5 '
                                    'seconds until it is available',
                                    self._port_url)
                    port_down = True
                time.sleep(5)
                continue
            if not self._listen_active:
                # close() gave up waiting while this open was in flight (a
                # slow network port); nobody else will close this handle,
                # and a leftover one keeps the port's data subscription.
                try:
                    port.close()
                except Exception:
                    pass
                return
            if port_down:
                _LOGGER.info('Reconnected to %s', self._port_url)
                port_down = False
            self._port = port
            receive_buffer = b''
            try:
                while self._listen_active:
                    data = port.read(1)
                    if data:
                        receive_buffer += data
                        while EOL in receive_buffer:
                            message, _, receive_buffer = \
                                receive_buffer.partition(EOL)
                            _LOGGER.debug('Received: %s', message)
                            self._parse_response(
                                message.decode(errors='replace'))
            except Exception:
                if not self._listen_active:
                    return
                _LOGGER.error('Unexpected port error, retrying.')
                self._port = None
                try:
                    port.close()
                except Exception:
                    pass
                time.sleep(5)

    # ---- response parsing ------------------------------------------------

    def _parse_response(self, string: str):
        match = re.search(ESSENTIA_D_SETSR_PATTERN, string)
        if match:
            _LOGGER.debug('Essentia D SETSR received')
            self._recv_zoneset(match.group('zone'), match.group('override'),
                               match.group('bass'), match.group('treble'),
                               match.group('group'),
                               match.group('volume_reset'))
            return

        match = re.search(CONSR_PATTERN, string)
        if match:
            _LOGGER.debug('CONSR received')
            self._recv_zone_status(match.group('zone'), match.group('power'),
                                   match.group('source'),
                                   match.group('volume'), sync_group=True)
            return

        match = re.search(STATUS_PATTERN, string)
        if match:
            _LOGGER.debug('STATUS received')
            self._recv_zone_status(match.group('zone'), match.group('power'),
                                   match.group('source'),
                                   match.group('volume'), sync_group=False)
            return

        match = re.search(SIMPLESE_SETSR_PATTERN, string)
        if match:
            _LOGGER.debug('Simplese SETSR received')
            self._recv_zoneset(match.group('zone'), match.group('override'),
                               match.group('bass'), match.group('treble'),
                               match.group('group'), '1')
            return

        match = re.search(CONCERTO_SETSR_PATTERN, string)
        if match:
            _LOGGER.debug('Concerto SETSR received')
            self._recv_concerto_zoneset(match.group('zone'),
                                        match.group('bass'),
                                        match.group('treble'),
                                        match.group('balance'))
            return

        match = re.search(SIMPLESE_OFF_PATTERN, string)
        if match:
            _LOGGER.debug('Simplese PWROFF received')
            zone = abs(int(match.group('zone')))
            self._zonepwr[zone] = 0
            self._fire_media_callback(zone)
            return

        match = re.search(ALL_OFF_PATTERN, string)
        if match:
            _LOGGER.debug('ALL OFF received')
            self._all_off_keypad()
            return

        match = re.search(KEYPAD_LOCK_PATTERN, string)
        if match:
            _LOGGER.debug('Keypad lock status received')
            zone = abs(int(match.group('zone')))
            self._zonelock[zone] = 1 if match.group('lock') == 'ON' else 0
            self._fire_settings_callbacks(zone)
            return

        match = re.search(ERROR_PATTERN, string)
        if match:
            _LOGGER.error('Received error response from Nuvo on last command')
            return

        match = re.search(ESSENTIA_D_VERSION, string)
        if match:
            _LOGGER.info('Nuvo returned model Essentia D')
            self._model = 'ESSENTIA_D'
            return

        match = re.search(SIMPLESE_VERSION, string)
        if match:
            _LOGGER.info('Nuvo returned model Simplese')
            self._model = 'SIMPLESE'
            return

        match = re.search(CONCERTO_VERSION, string)
        if match:
            _LOGGER.info('Nuvo returned model Concerto')
            self._model = 'CONCERTO'
            return

        match = re.search(CONCERTO_VERSION2, string)
        if match:
            _LOGGER.info('Nuvo returned model Concerto (NV-I8G)')
            self._model = 'CONCERTO'
            return

        if '#Busy' in string:
            _LOGGER.warning('BUSY RESPONSE - TRY AGAIN')
            return

        _LOGGER.debug('NO MATCH - %s', string)

    def _recv_zone_status(self, zone, power, source, volume, sync_group):
        zone = abs(int(zone))
        if 'ON' in power:
            self._zonepwr[zone] = 1
            if sync_group and self._zonegroupsrc[zone] == 0:
                """ Nuvo does not send update from other zones using source
                    grouping.  See if it is enabled and if so, update the
                    other zones that are powered on. """
                for count in range(1, 13):
                    if self._zonegroupsrc[count] == 0 and \
                            self._zonepwr[count] == 1:
                        if int(self._zonesrc[count]) != int(source):
                            self._zonesrc[count] = int(source)
                            self._fire_media_callback(count)
        else:
            self._zonepwr[zone] = 0

        if 'MT' in volume:
            self._zonemute[zone] = 1
        else:
            self._zonemute[zone] = 0
            self._zonevol[zone] = int(volume)
        self._zonesrc[zone] = int(source)

        _LOGGER.debug('Zone: %s, Power: %s, Vol: %sdb, Mute: %s, Source: %s',
                      zone, self._zonepwr[zone], self._zonevol[zone],
                      self._zonemute[zone], self._zonesrc[zone])
        self._fire_media_callback(zone)

    def _recv_zoneset(self, zone, override, bass, treble, group, volume_reset):
        zone = abs(int(zone))
        self._zonebass[zone] = int(bass)
        self._zonetreble[zone] = int(treble)
        self._zonegroupsrc[zone] = int(group)
        self._zonevolreset[zone] = int(volume_reset)
        if self._model == 'ESSENTIA_D':
            self._zoneoverride[zone] = int(override)
        _LOGGER.debug('Zone: %s, Bass: %s, Treble: %s, Group: %s, VolReset: %s',
                      zone, bass, treble, group, volume_reset)
        self._fire_settings_callbacks(zone)

    def _recv_concerto_zoneset(self, zone, bass, treble, balance):
        zone = abs(int(zone))
        self._zonebass[zone] = int(bass)
        self._zonetreble[zone] = int(treble)
        if balance[0] == 'L':
            self._zonebalance[zone] = -int(balance[1])
        elif balance[0] == 'R':
            self._zonebalance[zone] = int(balance[1])
        else:
            self._zonebalance[zone] = 0
        _LOGGER.debug('Zone: %s, Bass: %s, Treble: %s, Balance: %s',
                      zone, bass, treble, self._zonebalance[zone])
        self._fire_settings_callbacks(zone)

    def _all_off_keypad(self):
        zonesalloff = 1
        for count in range(0, NUM_ZONES + 1):
            if self._zonepwr[count] == 1:
                zonesalloff = 0
        for count in range(0, NUM_ZONES + 1):
            if zonesalloff == 0:
                self._zonepwralloff[count] = self._zonepwr[count]
                self._zonepwr[count] = 0
            else:
                if self._zonepwralloff[count] == 1 and self._all_off_recall:
                    self._zonepwr[count] = 1
            self._fire_media_callback(count)

    # ---- callbacks -------------------------------------------------------

    def add_callback(self, callback, zone, entity_id, entity_type) -> None:
        """Add entity subscription for updates."""
        zone = int(zone)
        if entity_type == 'media':
            if zone in self._media_zonetable:
                # The zone's entity was removed and added again (e.g. its
                # entity_id was changed): replace its row, keep its group.
                index = self._media_zonetable.index(zone)
                renamed = self._entitytable[index] != entity_id
                self._entitytable[index] = entity_id
                self._media_callback[index] = callback
                if renamed:
                    # Grouped zones report their members by entity_id
                    for i, other in enumerate(self._media_callback):
                        if i != index:
                            other()
            else:
                self._entitytable.append(entity_id)
                self._media_zonetable.append(zone)
                self._media_callback.append(callback)
                self._groupzone_members.append([zone])
            self._setup = True
            _LOGGER.debug('Added %s media callback', entity_id)
        if entity_type == 'settings':
            if (zone, callback) not in zip(self._settings_zonetable,
                                           self._settings_callback):
                self._settings_zonetable.append(zone)
                self._settings_callback.append(callback)
            _LOGGER.debug('Added %s settings callback', entity_id)

    def update_entity_id(self, old_entity_id, new_entity_id) -> None:
        """Follow a media player whose entity_id was changed in place."""
        for index, entity_id in enumerate(self._entitytable):
            if entity_id == old_entity_id:
                self._entitytable[index] = new_entity_id
        # Grouped zones report their members by entity_id
        for callback in self._media_callback:
            callback()

    def _fire_media_callback(self, zone):
        if zone in self._media_zonetable:
            self._media_callback[self._media_zonetable.index(zone)]()

    def _fire_settings_callbacks(self, zone):
        for i, z in enumerate(self._settings_zonetable):
            if z == zone:
                self._settings_callback[i]()

    def _zonegroup_entity_members(self, zone):
        try:
            zoneindex = self._media_zonetable.index(zone)
            members = []
            for grpzonembr in self._groupzone_members[zoneindex]:
                members.append(
                    self._entitytable[self._media_zonetable.index(grpzonembr)])
            return members
        except (ValueError, IndexError):
            return None

    # ---- status ----------------------------------------------------------

    @_synchronized
    def zone_status(self, zone: int):
        """Get the status of a zone, or None if not yet initialized.

        The first call queues a status request to the amplifier and returns
        None; the response arrives asynchronously and triggers the zone's
        callback, after which subsequent calls return cached state.
        """
        zone = int(zone)
        if self._zoneinit[zone] == 0:
            if self._model == 'CONCERTO':
                self._process_request('Z{:0=2}STATUS'.format(zone))
            else:
                self._process_request('Z{:0=2}CONSR'.format(zone))
            self._zoneinit[zone] += 1
            return None

        if self._zonepwralloff[zone] == 1 and self._zonepwr[zone] == 1:
            self.set_power(zone, True)
            self._zonepwralloff[zone] = 0

        if self._setup and zone in self._media_zonetable:
            # Propagate the controller zone's state to joined group members
            zoneindex = self._media_zonetable.index(zone)
            for group_member in self._groupzone_members[zoneindex][1:]:
                group_member = int(group_member)
                _LOGGER.debug('Zone %s: update group member zone %s',
                              zone, group_member)
                if self._zonepwr[zone] != self._zonepwr[group_member]:
                    self.set_power(group_member, self._zonepwr[zone] == 1)
                if self._zonevol[zone] != self._zonevol[group_member]:
                    if self._zonevoloffset[group_member] != 0:
                        offsetvolpct = db_to_percent(self._zonevol[zone]) + \
                            self._zonevoloffset[group_member]
                        offsetvol = percent_to_db(offsetvolpct)
                        offsetvol = max(-78, min(offsetvol, 0))
                        self.set_volume(group_member, offsetvol)
                    else:
                        self.set_volume(group_member, self._zonevol[zone])
                if self._zonemute[zone] != self._zonemute[group_member]:
                    self.set_mute(group_member, self._zonemute[zone] == 1)
                if self._zonesrc[zone] != self._zonesrc[group_member]:
                    self.set_source(group_member, self._zonesrc[zone])

        return ZoneStatus(zone,
                          self._zonepwr[zone] == 1,
                          self._zonesrc[zone],
                          int(self._zonevol[zone]),
                          self._zonemute[zone] == 1,
                          self._zonegroup_entity_members(zone))

    @_synchronized
    def zoneset_status(self, zone: int):
        """Get the settings of a zone, or None if not yet initialized."""
        zone = int(zone)
        if self._zonesetinit[zone] == 0:
            self._process_request('Z{:0=2}SETSR'.format(zone))
            self._zonesetinit[zone] += 1
            return None

        if self._model == 'CONCERTO':
            return ConcertoZonesetStatus(zone,
                                         self._zonebass[zone],
                                         self._zonetreble[zone],
                                         self._zonebalance[zone],
                                         self._zonevoloffset[zone])
        return ZonesetStatus(zone,
                             self._zonebass[zone],
                             self._zonetreble[zone],
                             self._zoneoverride[zone] == 1,
                             self._zonevolreset[zone] != 1,
                             self._zonegroupsrc[zone] != 1,
                             self._zonelock[zone] != 0,
                             self._zonevoloffset[zone])

    # ---- speaker grouping ------------------------------------------------

    @_synchronized
    def join_players(self, zone, group_members):
        zoneindex = self._media_zonetable.index(zone)
        for group_member in group_members:
            entityindex = self._entitytable.index(group_member)
            addedzone = int(self._media_zonetable[entityindex])
            del self._groupzone_members[entityindex][:]
            self._groupzone_members[entityindex].append(
                self._media_zonetable[entityindex])
            for zonesindex, zones in enumerate(self._media_zonetable):
                if zones != zone:
                    if zone in self._groupzone_members[zonesindex]:
                        self._groupzone_members[zonesindex].remove(zone)
                if zones != addedzone:
                    if addedzone in self._groupzone_members[zonesindex]:
                        self._groupzone_members[zonesindex].remove(addedzone)
                self._media_callback[zonesindex]()
            self._groupzone_members[zoneindex].append(addedzone)
            self._media_callback[entityindex]()
            _LOGGER.debug('Join zone %s to controller zone %s.  '
                          'All slave zones: %s', addedzone, zone,
                          self._groupzone_members[zoneindex])
        self._fire_media_callback(zone)

    @_synchronized
    def unjoin_player(self, zone):
        _LOGGER.debug('Unjoin zone %s from all groups', zone)
        zoneindex = self._media_zonetable.index(zone)
        if len(self._groupzone_members[zoneindex]) == 1:
            self.set_power(zone, False)
        for control_zoneindex, control_zone in \
                enumerate(self._media_zonetable):
            if zone != control_zone:
                if zone in self._groupzone_members[control_zoneindex]:
                    self._groupzone_members[control_zoneindex].remove(zone)
            else:
                del self._groupzone_members[control_zoneindex][:]
                self._groupzone_members[control_zoneindex].append(control_zone)
            self._media_callback[control_zoneindex]()

    # ---- commands --------------------------------------------------------

    @_synchronized
    def set_power(self, zone: int, power: bool):
        zone = int(zone)
        self._zonepwr[zone] = 1 if power else 0
        if zone == 0:
            self._fire_media_callback(0)
        else:
            self._process_request('Z{:0=2}{}'.format(
                zone, 'ON' if power else 'OFF'))

    @_synchronized
    def set_mute(self, zone: int, mute: bool):
        zone = int(zone)
        self._zonemute[zone] = 1 if mute else 0
        if zone == 0:
            self._fire_media_callback(0)
        else:
            self._process_request('Z{:0=2}MT{}'.format(
                zone, 'ON' if mute else 'OFF'))

    @_synchronized
    def set_keypad_lock(self, zone: int, lock: bool):
        zone = int(zone)
        self._zonelock[zone] = 1 if lock else 0
        if zone == 0:
            self._fire_media_callback(0)
        else:
            self._process_request('Z{:0=2}LK{}'.format(
                zone, 'ON' if lock else 'OFF'))

    @_synchronized
    def set_volume(self, zone: int, volume: float):
        zone = int(zone)
        if zone == 0:
            self._zonevol[0] = volume
            self._fire_media_callback(0)
            return
        # If muted, status has no info on volume level
        if _is_int(volume):
            self._zonevol[zone] = int(volume)
            # Negative sign in volume parm produces erroneous result
            volume = round(abs(volume), 0)
        self._process_request('Z{:0=2}VOL{:0=2}'.format(zone, volume))

    @_synchronized
    def set_volume_offset(self, zone: int, volume: float):
        zone = int(zone)
        self._zonevoloffset[zone] = volume
        self._fire_settings_callbacks(zone)

    @_synchronized
    def set_group(self, zone: int, group: bool):
        self._process_request('Z{:0=2}GRP{}'.format(
            int(zone), 'ON' if group else 'OFF'))

    @_synchronized
    def set_volume_reset(self, zone: int, volreset: bool):
        self._process_request('Z{:0=2}VRST{}'.format(
            int(zone), 'ON' if volreset else 'OFF'))

    @_synchronized
    def set_treble(self, zone: int, treble: float):
        zone = int(zone)
        self._zonetreble[zone] = treble
        if treble >= 0:
            self._process_request('Z{:0=2}TREB+{:0=2}'.format(zone, int(treble)))
        else:
            self._process_request('Z{:0=2}TREB{:0=3}'.format(zone, int(treble)))

    @_synchronized
    def set_bass(self, zone: int, bass: float):
        zone = int(zone)
        self._zonebass[zone] = bass
        if bass >= 0:
            self._process_request('Z{:0=2}BASS+{:0=2}'.format(zone, int(bass)))
        else:
            self._process_request('Z{:0=2}BASS{:0=3}'.format(zone, int(bass)))

    @_synchronized
    def set_balance(self, zone: int, balance: float):
        zone = int(zone)
        self._zonebalance[zone] = balance
        if balance > 0:
            self._process_request('Z{:0=2}BALR{:0=1}'.format(zone, int(balance)))
        elif balance < 0:
            self._process_request('Z{:0=2}BALL{:0=1}'.format(zone, abs(int(balance))))
        else:
            self._process_request('Z{:0=2}BALC'.format(zone))

    @_synchronized
    def set_source(self, zone: int, source: int):
        zone = int(zone)
        source = int(max(1, min(int(source), 6)))
        self._zonesrc[zone] = source
        if zone == 0:
            self._fire_media_callback(0)
        else:
            self._process_request('Z{:0=2}SRC{}'.format(zone, source))

    # ---- paging / all-zone services --------------------------------------

    def _live_page_holds(self):
        """Pages that were started and not ended, oldest first.

        Overlapping pages share the zones: only the last one to end restores
        them. A page whose page_off never came (its caller failed) stops
        counting after TIMEOUT_PAGE so it cannot keep the zones paged.
        """
        cutoff = time.monotonic() - TIMEOUT_PAGE
        self._page_holds = [t for t in self._page_holds if t > cutoff]
        return self._page_holds

    @_synchronized
    def page_off(self, page_source, page_zones):
        holds = self._live_page_holds()
        if holds:
            holds.pop(0)
        if holds:
            _LOGGER.info('Another page is still active, leaving zones paged.')
            return
        while self._page_active[1] == 1:
            _LOGGER.info('Paging on service call currently in progress when '
                         'paging off service call requested!  This should be '
                         'ok, but could put zones in the incorrect state.')
        for zone in page_zones:
            zone = int(zone)
            self.set_volume(zone, self._zonevolsave[zone])
            if self._zonemutesave[zone] == 1:
                self.set_mute(zone, True)
            if self._zonepwrsave[zone] == 0:
                self.set_power(zone, False)
            else:
                if self._zonesrcsave[zone] != page_source:
                    self.set_source(zone, self._zonesrcsave[zone])
        self._cmd_queue.join()
        self._page_active[0] = 0

    @_synchronized
    def page_on(self, page_source, page_zones, page_volume):
        self._live_page_holds().append(time.monotonic())
        if self._page_active[0] != 0:
            _LOGGER.info('Paging already active, ignoring second request.')
            return
        self._page_active[1] = 1
        zones = [(int(zone), page_volume[zonecnt])
                 for zonecnt, zone in enumerate(page_zones)]
        # A few zones at a time: a zone needs a moment after power-on before
        # its next command, and the other zones' commands fill that wait.
        # Source still follows power-on closely so a zone is not left
        # playing the wrong source.
        for i in range(0, len(zones), PAGE_GROUP):
            group = zones[i:i + PAGE_GROUP]
            for zone, volume in group:
                _LOGGER.debug('Page Zone: %s, Vol: %s, Src: %s', zone,
                              volume, page_source)
                self._zonepwrsave[zone] = self._zonepwr[zone]
                self._zonesrcsave[zone] = self._zonesrc[zone]
                self._zonevolsave[zone] = self._zonevol[zone]
                self._zonemutesave[zone] = self._zonemute[zone]
                if self._zonepwr[zone] == 0:
                    self.set_power(zone, True)
            for zone, volume in group:
                if self._zonesrc[zone] != page_source:
                    self.set_source(zone, page_source)
            for zone, volume in group:
                self.set_volume(zone, percent_to_db(int(volume)))
            self._page_active[0] = 1
        self._cmd_queue.join()
        self._page_active[1] = 0

    @_synchronized
    def mute_all(self):
        self._process_request('ALLMON')
        for count in range(1, NUM_ZONES + 1):
            self._zonemute[count] = 1
            self._fire_media_callback(count)

    @_synchronized
    def unmute_all(self):
        self._process_request('ALLMOFF')
        for count in range(1, NUM_ZONES + 1):
            self._zonemute[count] = 0
            self._fire_media_callback(count)

    @_synchronized
    def all_off(self):
        self._process_request('ALLOFF')
        for count in range(0, NUM_ZONES + 1):
            self._zonepwralloff[count] = 0
            self._zonepwr[count] = 0
            self._fire_media_callback(count)


def get_nuvo(port_url, baud, all_off_recall):
    """
    Return synchronous version of Nuvo interface
    :param port_url: serial port path or URL, i.e. '/dev/ttyUSB0'
    :param baud: baud, i.e '9600'
    :return: synchronous implementation of Nuvo interface
    """
    return NuvoSync(port_url, baud, all_off_recall)
