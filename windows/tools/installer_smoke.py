"""Actual windowed setup acceptance, isolated user folders, never launches providers."""
import argparse
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from install_usage_tray import sha256, shortcut
from usage_process import ChildTree


def gui_subsystem(path):
    with Path(path).open('rb') as stream:
        stream.seek(0x3c); position = struct.unpack('<I', stream.read(4))[0]
        stream.seek(position); assert stream.read(4) == b'PE\0\0'
        stream.seek(position + 4 + 20 + 68)
        return struct.unpack('<H', stream.read(2))[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', type=Path, required=True)
    parser.add_argument('--app', type=Path, required=True)
    args = parser.parse_args()
    setup, app = args.setup.resolve(), args.app.resolve()
    assert gui_subsystem(setup) == 2, 'Setup must not open a console'
    assert gui_subsystem(app) == 2, 'Tray must not open a console'
    expected = sha256(app)
    with tempfile.TemporaryDirectory(prefix='usage-setup-smoke-') as folder:
        root = Path(folder)
        environment = dict(os.environ, LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'roaming'),
                           CODEX_HOME=str(root/'empty-codex'), CLAUDE_CONFIG_DIR=str(root/'empty-claude'))
        user_data = root/'local/UsageTray'; user_data.mkdir(parents=True)
        (user_data/'settings.json').write_text('settings sentinel', encoding='utf-8')
        (user_data/'usage-hub.sqlite3').write_bytes(b'index sentinel')
        before = {p.name:p.read_bytes() for p in user_data.iterdir()}
        def invoke(*flags):
            tree = ChildTree()
            try:
                tree.start([str(setup), '--quiet', '--no-start', *flags], env=environment,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                tree.process.communicate(timeout=120)
                assert tree.process.returncode == 0, 'Packaged setup failed'
            finally: tree.close()
        invoke()
        installed = root/'local/Programs/UsageTray/versions'/expected/'UsageTray.exe'
        assert sha256(installed) == expected, 'Payload must match the tested executable'
        programs = root/'roaming/Microsoft/Windows/Start Menu/Programs'
        for link in (programs/'Usage Tray.lnk',programs/'Startup/Usage Tray.lnk'):
            value = shortcut('read',link)
            assert Path(value['target']) == installed
            assert value['arguments'] == '', 'Startup must enable normal live mode'
        invoke()
        assert len(list(installed.parent.parent.iterdir())) == 1, 'Reinstall must reuse the identical payload'
        for name, value in before.items(): assert (user_data/name).read_bytes() == value
        assert not list((root/'local').rglob('.usage-tray-*.lnk'))
        assert not list((root/'roaming').rglob('.usage-tray-*.lnk'))
    print('Packaged installer: PASS (GUI subsystem, isolated per-user install, exact payload, Start menu/startup shortcuts, repeat install, preserved settings/index)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
