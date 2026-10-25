"""Per-user installation of the windowed tray; no credentials or usage-data changes."""
from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid


class InstallError(Exception):
    """Static user-facing failure; never show raw paths or exception payloads."""


@dataclass(frozen=True)
class InstallPaths:
    root: Path
    menu: Path
    startup: Path

    @classmethod
    def for_user(cls):
        if os.name != 'nt':
            raise InstallError('Usage Tray Setup requires Windows.')
        try:
            local, roaming = Path(os.environ['LOCALAPPDATA']), Path(os.environ['APPDATA'])
        except KeyError:
            raise InstallError('Windows user folders are unavailable.') from None
        if not local.is_absolute() or not roaming.is_absolute():
            raise InstallError('Windows user folders must be absolute paths.')
        programs = roaming/'Microsoft/Windows/Start Menu/Programs'
        return cls(local/'Programs/UsageTray', programs/'Usage Tray.lnk',
                   programs/'Startup/Usage Tray.lnk')


@dataclass(frozen=True)
class Installation:
    executable: Path
    sha256: str
    auto_start: bool


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


# Paths are environment data, never interpolated into executable shell text.
SHORTCUT_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:USAGE_SETUP_LINK)
if ($env:USAGE_SETUP_ACTION -eq 'read') {
    @{target=$link.TargetPath;arguments=$link.Arguments} | ConvertTo-Json -Compress
} else {
    $link.TargetPath = $env:USAGE_SETUP_EXE
    $link.Arguments = ''
    $link.WorkingDirectory = [IO.Path]::GetDirectoryName($env:USAGE_SETUP_EXE)
    $link.IconLocation = $env:USAGE_SETUP_EXE + ',0'
    $link.Description = 'Usage Tray - local usage and live subscription limits'
    $link.WindowStyle = 1
    $link.Save()
}
"""


def shortcut(action, path, executable=None):
    if os.name != 'nt':
        raise InstallError('Windows shortcut support is unavailable.')
    environment = dict(os.environ, USAGE_SETUP_ACTION=action,
                       USAGE_SETUP_LINK=str(path), USAGE_SETUP_EXE=str(executable or ''))
    # Use the Windows-bundled PowerShell path, not an executable from PATH.
    powershell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive',
                                 '-Command', SHORTCUT_SCRIPT], env=environment,
                                capture_output=True, encoding="utf-8", timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW, check=True)
        if action == 'read':
            value = json.loads(result.stdout)
            if not isinstance(value, dict) or not isinstance(value.get('target'), str):
                raise ValueError()
            return value
    except (OSError, subprocess.SubprocessError, ValueError):
        raise InstallError('Cannot create Windows shortcuts. Existing startup settings were preserved where possible.') from None


def _install(source, paths=None, *, auto_start=True, shortcut_action=shortcut):
    """Install a content-addressed version; replace only app-owned shortcuts.

    Windows can lock a running executable. Versioned files avoid overwriting it;
    upgrades take effect after the existing tray quits and the new shortcut opens.
    """
    paths = paths or InstallPaths.for_user()
    source = Path(source).resolve()
    root = paths.root.resolve()
    try:
        if not source.is_file() or source.stat().st_size < 2:
            raise InstallError('The bundled Usage Tray executable is missing.')
        with source.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise InstallError('The bundled Usage Tray executable is invalid.')
        digest = sha256(source)
        destination = root/'versions'/digest/'UsageTray.exe'
        links = [paths.menu] + ([paths.startup] if auto_start else [])
        # Preflight every existing shortcut before modifying files or shortcuts.
        for link in links:
            if link.is_symlink():
                raise InstallError('A conflicting shortcut exists. Preserve it before installing.')
            if link.exists():
                old = shortcut_action('read', link)
                target = Path(old['target'])
                if (not target.is_absolute() or not target.resolve().is_relative_to(root)
                        or target.name.lower() != 'usagetray.exe' or old.get('arguments')):
                    raise InstallError('A shortcut with this name belongs to another installation. Preserve it before installing.')
        if not destination.resolve().is_relative_to(root):
            raise InstallError('The installation folder is redirected outside the app folder.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if sha256(destination) != digest:
                raise InstallError('An installed executable was modified. Preserve the app folder before reinstalling.')
        else:
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.install-', delete=False) as stream:
                    temporary = Path(stream.name)
                    with source.open('rb') as original:
                        shutil.copyfileobj(original, stream)
                    stream.flush(); os.fsync(stream.fileno())
                if sha256(temporary) != digest:
                    raise InstallError('The executable changed during installation. Retry with a complete download.')
                os.replace(temporary, destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        staged = []
        previous = {link:link.read_bytes() if link.exists() else None for link in links}
        committed = []
        try:
            for link in links:
                link.parent.mkdir(parents=True, exist_ok=True)
                temporary = link.with_name('.usage-tray-'+uuid.uuid4().hex+'.lnk')
                staged.append((temporary, link))
                shortcut_action('write', temporary, destination)
                if not temporary.is_file():
                    raise InstallError('Windows did not create the app shortcut.')
            for temporary, link in staged:
                os.replace(temporary, link); committed.append(link)
        except Exception:
            # Restore the small shortcut set; never remove a running version/data.
            for link in reversed(committed):
                if previous[link] is None:
                    link.unlink(missing_ok=True)
                else:
                    link.write_bytes(previous[link])
            raise
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)
        return Installation(destination, digest, auto_start)
    except InstallError:
        raise
    except OSError:
        raise InstallError('Installation could not finish. Check permissions or disk space and retry; usage data was not changed.') from None



@contextmanager
def install_owner(root):
    """Keep concurrent setup processes from racing shortcut publication."""
    if os.name != 'nt':
        raise InstallError('Usage Tray Setup requires Windows.')
    import msvcrt
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root/'setup.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise InstallError('Another Usage Tray setup is running. Wait for it to finish.') from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def install(source, paths=None, *, auto_start=True, shortcut_action=shortcut):
    paths = paths or InstallPaths.for_user()
    try:
        with install_owner(paths.root):
            return _install(source, paths, auto_start=auto_start, shortcut_action=shortcut_action)
    except InstallError:
        raise
    except OSError:
        raise InstallError('Installation could not finish. Check permissions or disk space and retry; usage data was not changed.') from None


def launch(executable):
    # No dashboard flag: enable normal live checks, no terminal or browser.
    return subprocess.Popen([str(executable)], cwd=str(Path(executable).parent),
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
