"""Windowed, current-user Usage Tray setup. No admin rights or terminal needed."""
import argparse
import ctypes
from pathlib import Path
import sys

from install_usage_tray import InstallError, install, launch


def message(text, *, question=False, error=False):
    flags = 0x40 | (0x1 if question else 0x0)
    if error: flags = 0x10
    return ctypes.windll.user32.MessageBoxW(None, text, 'Usage Tray Setup', flags)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quiet', action='store_true', help='Install without dialogs')
    parser.add_argument('--no-start', action='store_true', help='Install without launching the tray now')
    parser.add_argument('--no-autostart', action='store_true', help='Skip creating a new sign-in shortcut')
    args = parser.parse_args()
    if sys.platform != 'win32':
        return 1
    if not args.quiet:
        note = ('Install Usage Tray for your Windows account?\n\n'
                'It runs in the system tray without a terminal or browser.\n'
                + ('It will start automatically when you sign in.\n' if not args.no_autostart else '')
                + 'Live provider checks use your existing CLI sign-ins.\n'
                'Your settings and usage data are preserved.')
        if message(note, question=True) != 1:
            return 0
    source = Path(getattr(sys, '_MEIPASS', Path(__file__).parent/'dist'))/'UsageTray.exe'
    try:
        result = install(source, auto_start=not args.no_autostart)
    except (InstallError, OSError):
        if not args.quiet:
            message('Setup could not finish. Check permissions, disk space and existing Usage Tray shortcuts. Your usage data was not changed.', error=True)
        return 1
    if not args.no_start:
        try:
            launch(result.executable)
        except OSError:
            if not args.quiet:
                message('Installed, but the tray could not start. Open Usage Tray from the Start menu.', error=True)
            return 2
    if not args.quiet:
        message('Usage Tray is installed. Find it under Show hidden icons or in the Start menu.\n\n'
                'Open the dashboard from its tray menu. If an older tray is running, Quit it and open Usage Tray from the Start menu to use this installation.\n\n'
                'To disable automatic startup, remove Usage Tray from your Windows Startup folder.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
