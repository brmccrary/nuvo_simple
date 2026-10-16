#!/usr/bin/env python3
"""Nuvo amplifier emulator for testing the nuvo_simple integration without hardware.

Creates a pty and symlinks it to a stable path that Home Assistant (or the
nuvo-simple library directly) can open as if it were a real serial port:

    python3 nuvo_emulator.py --link /tmp/nuvo-fake-1 --model ESSENTIA_D

Run a second instance with a different --link to simulate a second amplifier.

A control FIFO is created at <link>.ctl; any line written to it is sent to the
serial port verbatim (with trailing CR), which simulates unsolicited traffic
such as keypad presses:

    echo '#Z01PWRON,SRC2,GRP0,VOL-30' > /tmp/nuvo-fake-1.ctl

All received commands and sent responses are appended to <link>.log.

Stdlib only; no dependencies.
"""

import argparse
import os
import pty
import re
import select
import signal
import sys
import time
import tty

MODELS = ('ESSENTIA_D', 'CONCERTO', 'SIMPLESE')

VERSION_STRINGS = {
    'ESSENTIA_D': '#MPU_E6D v1.0',
    'SIMPLESE': '#MPU_A4D v1.0',
    'CONCERTO': '#NV-I8G FWv1.0 HWv0',
}


class Zone:
    def __init__(self):
        self.power = False
        self.src = 1
        self.vol = -78          # dB, -78..0
        self.mute = False
        self.lock = False
        self.bass = 0
        self.treble = 0
        self.balance = 0        # Concerto only, -6..6
        # GRP/VRST wire values are inverted from the switch sense:
        # the library treats GRP0 as "source group on" and VRST1 as
        # "volume reset off" (see ZonesetStatus in nuvo_simple).
        self.grp = 1
        self.vrst = 1
        self.override = 0


class Emulator:
    def __init__(self, link, model, zones, log_path):
        self.link = link
        self.model = model
        self.zones = {z: Zone() for z in range(1, zones + 1)}
        self.log_path = log_path
        self.master_fd = None
        self.ctl_fd = None
        self.ctl_path = link + '.ctl'

    # ---- wire formatting -------------------------------------------------

    @staticmethod
    def _fmt_vol(zone):
        return '-MT' if zone.mute else '-{:02d}'.format(abs(zone.vol))

    def status_line(self, zid):
        z = self.zones[zid]
        pwr = 'ON' if z.power else 'OFF'
        if self.model == 'CONCERTO':
            return '#Z{:02d}PWR{},SRC{},VOL{}'.format(zid, pwr, z.src, self._fmt_vol(z))
        return '#Z{:02d}PWR{},SRC{},GRP{},VOL{}'.format(
            zid, pwr, z.src, z.grp, self._fmt_vol(z))

    def setsr_line(self, zid):
        z = self.zones[zid]
        if self.model == 'CONCERTO':
            if z.balance == 0:
                bal = 'C'
            elif z.balance < 0:
                bal = 'L{}'.format(abs(z.balance))
            else:
                bal = 'R{}'.format(z.balance)
            return '#Z{:02d}BASS{:+03d},TREB{:+03d},BAL{},G0,MAXVOL-00,INIVOL-78'.format(
                zid, z.bass, z.treble, bal)
        if self.model == 'SIMPLESE':
            return '#Z{:02d},BASS{:+03d},TREB{:+03d},GRP{}'.format(
                zid, z.bass, z.treble, z.grp)
        return '#Z{:02d}OR{},BASS{:+03d},TREB{:+03d},GRP{},VRST{}'.format(
            zid, z.override, z.bass, z.treble, z.grp, z.vrst)

    # ---- command handling ------------------------------------------------

    def handle(self, cmd):
        if cmd == 'VER':
            return [VERSION_STRINGS[self.model]]
        if cmd == 'ALLOFF':
            for z in self.zones.values():
                z.power = False
            return ['#ALLOFF']
        if cmd in ('ALLMON', 'ALLMOFF'):
            mute = cmd == 'ALLMON'
            out = []
            for zid, z in self.zones.items():
                if z.power:
                    z.mute = mute
                    out.append(self.status_line(zid))
            return out

        m = re.fullmatch(r'Z(\d{2})(.+)', cmd)
        if not m:
            return ['#?']
        zid = int(m.group(1))
        if zid not in self.zones:
            return ['#?']
        z = self.zones[zid]
        sub = m.group(2)

        if sub in ('CONSR', 'STATUS'):
            return [self.status_line(zid)]
        if sub == 'SETSR':
            return [self.setsr_line(zid)]
        if sub == 'ON':
            z.power = True
            return [self.status_line(zid)]
        if sub == 'OFF':
            z.power = False
            return [self.status_line(zid)]
        if sub == 'MTON':
            z.mute = True
            return [self.status_line(zid)]
        if sub == 'MTOFF':
            z.mute = False
            return [self.status_line(zid)]
        if sub in ('LKON', 'LKOFF'):
            z.lock = sub == 'LKON'
            return ['#Z{:02d}LK{}'.format(zid, 'ON' if z.lock else 'OFF')]
        if sub in ('GRPON', 'GRPOFF'):
            z.grp = 0 if sub == 'GRPON' else 1
            return [self.setsr_line(zid)]
        if sub in ('VRSTON', 'VRSTOFF'):
            z.vrst = 0 if sub == 'VRSTON' else 1
            return [self.setsr_line(zid)]

        m2 = re.fullmatch(r'VOL(\d{1,2})', sub)
        if m2:
            z.vol = -int(m2.group(1))
            z.mute = False
            return [self.status_line(zid)]
        m2 = re.fullmatch(r'BASS([+-]?\d{2})', sub)
        if m2:
            z.bass = int(m2.group(1))
            return [self.setsr_line(zid)]
        m2 = re.fullmatch(r'TREB([+-]?\d{2})', sub)
        if m2:
            z.treble = int(m2.group(1))
            return [self.setsr_line(zid)]
        m2 = re.fullmatch(r'BAL(C|L\d|R\d)', sub)
        if m2:
            val = m2.group(1)
            if val == 'C':
                z.balance = 0
            elif val[0] == 'L':
                z.balance = -int(val[1])
            else:
                z.balance = int(val[1])
            return [self.setsr_line(zid)]
        m2 = re.fullmatch(r'SRC(\d)', sub)
        if m2:
            z.src = max(1, min(int(m2.group(1)), 6))
            return [self.status_line(zid)]

        return ['#?']

    # ---- plumbing --------------------------------------------------------

    def log(self, direction, text):
        line = '{:.3f} {} {}'.format(time.time(), direction, text)
        print('[{}] {} {}'.format(os.path.basename(self.link), direction, text),
              flush=True)
        with open(self.log_path, 'a') as f:
            f.write(line + '\n')

    def send(self, line):
        self.log('TX', line)
        os.write(self.master_fd, line.encode() + b'\r')

    def _open_ctl(self):
        self.ctl_fd = os.open(self.ctl_path, os.O_RDONLY | os.O_NONBLOCK)

    def run(self):
        self.master_fd, slave_fd = pty.openpty()
        tty.setraw(self.master_fd)
        slave_name = os.ttyname(slave_fd)
        if os.path.islink(self.link) or os.path.exists(self.link):
            os.unlink(self.link)
        os.symlink(slave_name, self.link)
        if os.path.exists(self.ctl_path):
            os.unlink(self.ctl_path)
        os.mkfifo(self.ctl_path)
        self._open_ctl()

        print('[{}] model={} zones={} pty={} link={}'.format(
            os.path.basename(self.link), self.model, len(self.zones),
            slave_name, self.link), flush=True)

        buf = b''
        ctl_buf = b''
        while True:
            rlist, _, _ = select.select([self.master_fd, self.ctl_fd], [], [])
            if self.master_fd in rlist:
                data = os.read(self.master_fd, 256)
                if not data:
                    break
                buf += data
                while b'\r' in buf:
                    raw, _, buf = buf.partition(b'\r')
                    cmd = raw.decode(errors='replace').strip().lstrip('*')
                    if not cmd:
                        continue
                    self.log('RX', cmd)
                    for line in self.handle(cmd):
                        self.send(line)
            if self.ctl_fd in rlist:
                data = os.read(self.ctl_fd, 256)
                if not data:
                    # writer closed; reopen so select stops spinning
                    os.close(self.ctl_fd)
                    self._open_ctl()
                else:
                    ctl_buf += data
                    while b'\n' in ctl_buf:
                        raw, _, ctl_buf = ctl_buf.partition(b'\n')
                        text = raw.decode(errors='replace').strip()
                        if text:
                            self.send(text)

    def cleanup(self):
        for path in (self.link, self.ctl_path):
            try:
                os.unlink(path)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--link', required=True,
                        help='stable symlink path for the pty, e.g. /tmp/nuvo-fake-1')
    parser.add_argument('--model', default='ESSENTIA_D', choices=MODELS)
    parser.add_argument('--zones', type=int, default=6)
    parser.add_argument('--log', default=None,
                        help='log file (default: <link>.log)')
    args = parser.parse_args()

    emu = Emulator(args.link, args.model, args.zones, args.log or args.link + '.log')
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    try:
        emu.run()
    except KeyboardInterrupt:
        pass
    finally:
        emu.cleanup()


if __name__ == '__main__':
    main()
