"""Standalone, standard-library-only host adapter for systemd-timesyncd.

Reports operational synchronization status, never an accuracy estimate. This
file can be installed on a Linux host independently of the relay package.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


SYNC_FILE = Path('/run/systemd/timesync/synchronized')
MAX_SYNC_AGE_MS = 2 * 60 * 60 * 1000


def command(argv):
    return subprocess.run(argv, check=True, capture_output=True, text=True,
                          timeout=5, env={**os.environ, 'LC_ALL': 'C',
                                          'SYSTEMD_PAGER': 'cat'}).stdout.strip()


def collect(*, sync_file=SYNC_FILE, run=command):
    checked = int(time.time() * 1000)
    result = dict(mode='operational', source='systemd-timesyncd', synchronized=False,
                  checked_at_ms=checked, uncertainty_ms=None, last_sync_at_ms=None,
                  reason='monitor-error')
    try:
        active = run(['systemctl', 'is-active', 'systemd-timesyncd.service']) == 'active'
        synchronized = run(['timedatectl', 'show', '--property=NTPSynchronized',
                            '--value', '--no-pager']) == 'yes'
        last_sync = sync_file.stat().st_mtime_ns // 1000000
        now = int(time.time() * 1000)
        # checked_at is the START of the check, not a claim of a fresh NTP packet.
        # A concurrent successful synchronization may be newer than checked_at;
        # this sample safely reports unhealthy and the next check can accept it.
        recent = 0 <= checked - last_sync <= MAX_SYNC_AGE_MS and 0 <= now - last_sync <= MAX_SYNC_AGE_MS
        result.update(last_sync_at_ms=last_sync, synchronized=active and synchronized and recent,
                      reason='ok' if active and synchronized and recent else 'unsynchronized-or-stale')
    except (OSError, subprocess.SubprocessError):
        pass
    return result


def write_health(path, data):
    """Replace a public status file atomically; directory must be trusted."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, prefix='.clock-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = collect()
    write_health(args.output, data)
    print(json.dumps(data, sort_keys=True))


if __name__ == '__main__':
    main()
