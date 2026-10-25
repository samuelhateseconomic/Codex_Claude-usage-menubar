"""Per-user setup safety, shortcut identity and terminal-free launch regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import install_usage_tray as setup
import setup_usage_tray as entry


@unittest.skipUnless(os.name == 'nt', 'Windows installer')
class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root/'download/UsageTray.exe'
        self.source.parent.mkdir()
        self.source.write_bytes(b'MZsynthetic-version-one')
        self.paths = setup.InstallPaths(self.root/'local/Programs/UsageTray',
                                      self.root/'menu/Usage Tray.lnk', self.root/'startup/Usage Tray.lnk')
        self.settings = self.root/'local/UsageTray/settings.json'
        self.settings.parent.mkdir(parents=True)
        self.settings.write_text('preserved settings', encoding='utf-8')

    def shortcut(self, action, path, executable=None):
        if action == 'read':
            return json.loads(Path(path).read_text(encoding='utf-8'))
        Path(path).write_text(json.dumps({'target':str(executable),'arguments':''}), encoding='utf-8')

    def install(self, **kwargs):
        return setup.install(self.source, self.paths, shortcut_action=self.shortcut, **kwargs)

    def test_install_and_repeat_preserve_source_settings_and_live_default_shortcuts(self):
        original = self.source.read_bytes()
        first = self.install()
        self.assertEqual(first.executable.read_bytes(), original)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(self.settings.read_text(), 'preserved settings')
        for path in (self.paths.menu, self.paths.startup):
            self.assertEqual(self.shortcut('read',path), {'target':str(first.executable),'arguments':''})
        again = self.install()
        self.assertEqual(again, first)
        self.assertEqual(list((self.paths.root/'versions').iterdir()), [first.executable.parent])

    def test_upgrade_keeps_old_executable_and_retargets_both_shortcuts(self):
        old = self.install()
        old_bytes = old.executable.read_bytes()
        self.source.write_bytes(b'MZsynthetic-version-two')
        new = self.install()
        self.assertNotEqual(old.executable, new.executable)
        self.assertEqual(old.executable.read_bytes(), old_bytes)
        for path in (self.paths.menu,self.paths.startup):
            self.assertEqual(self.shortcut('read',path)['target'], str(new.executable))
        self.assertEqual(self.settings.read_text(), 'preserved settings')

    def test_no_autostart_only_creates_menu_link(self):
        result = self.install(auto_start=False)
        self.assertFalse(result.auto_start)
        self.assertTrue(self.paths.menu.is_file())
        self.assertFalse(self.paths.startup.exists())

    def test_conflicting_shortcut_is_preserved_without_installing_payload(self):
        self.paths.startup.parent.mkdir(parents=True)
        self.paths.startup.write_text(json.dumps({'target':str(self.root/'other.exe'),'arguments':''}))
        before = self.paths.startup.read_bytes()
        with self.assertRaises(setup.InstallError): self.install()
        self.assertEqual(self.paths.startup.read_bytes(),before)
        self.assertFalse((self.paths.root/'versions').exists())
        self.assertFalse(self.paths.menu.exists())

    def test_failed_second_shortcut_keeps_previous_links_and_old_executable(self):
        old = self.install()
        before = {p:p.read_bytes() for p in (self.paths.menu,self.paths.startup)}
        self.source.write_bytes(b'MZnew-build')
        writes = []
        def failing(action,path,executable=None):
            if action == 'write':
                writes.append(path)
                if len(writes) == 2: raise setup.InstallError('Synthetic shortcut failure')
            return self.shortcut(action,path,executable)
        with self.assertRaises(setup.InstallError):
            setup.install(self.source,self.paths,shortcut_action=failing)
        for path, data in before.items(): self.assertEqual(path.read_bytes(),data)
        self.assertEqual(old.executable.read_bytes(), b'MZsynthetic-version-one')
        self.assertEqual(list(self.paths.menu.parent.glob('.usage-tray-*.lnk')), [])
        self.assertEqual(list(self.paths.startup.parent.glob('.usage-tray-*.lnk')), [])

    def test_failed_second_publication_rolls_back_first_link(self):
        self.install()
        before = {p:p.read_bytes() for p in (self.paths.menu,self.paths.startup)}
        self.source.write_bytes(b'MZnew-build')
        replace = os.replace
        def failing(source,target):
            if Path(target) == self.paths.startup: raise PermissionError('Synthetic lock')
            return replace(source,target)
        with patch.object(setup.os,'replace',side_effect=failing), self.assertRaises(setup.InstallError):
            self.install()
        for path, data in before.items(): self.assertEqual(path.read_bytes(),data)

    def test_modified_existing_payload_is_not_overwritten(self):
        installed = self.install()
        installed.executable.write_bytes(b'changed')
        with self.assertRaises(setup.InstallError):self.install()
        self.assertEqual(installed.executable.read_bytes(),b'changed')

    def test_parallel_install_lock_rejects_contender_and_releases(self):
        with setup.install_owner(self.paths.root):
            with self.assertRaises(setup.InstallError):self.install()
        self.assertTrue(self.install().executable.exists())

    def test_actual_shortcut_handles_unicode_spaces_and_shell_metacharacters(self):
        folder = self.root/"béta & 'quoted' $(literal)"
        folder.mkdir()
        executable = folder/'UsageTray.exe'; executable.write_bytes(b'MZfixture')
        link = folder/'Usage Tray.lnk'
        setup.shortcut('write', link, executable)
        result = setup.shortcut('read', link)
        self.assertEqual(Path(result['target']), executable)
        self.assertEqual(result['arguments'], '')

    def test_launch_passes_no_dashboard_flags_and_hides_console(self):
        with patch.object(setup.subprocess,'Popen') as popen:
            setup.launch(self.source)
        self.assertEqual(popen.call_args.args[0],[str(self.source)])
        self.assertEqual(popen.call_args.kwargs['creationflags'],subprocess.CREATE_NO_WINDOW)
        self.assertNotIn('shell',popen.call_args.kwargs)

    def test_windowed_setup_defaults_install_and_start_without_dialog_in_quiet_mode(self):
        installed = setup.Installation(self.source, 'digest', True)
        with patch.object(sys,'argv',['setup','--quiet']),patch.object(entry,'install',return_value=installed) as install,patch.object(entry,'launch') as launch,patch.object(entry,'message',side_effect=AssertionError('No dialog')):
            self.assertEqual(entry.main(),0)
        self.assertTrue(install.call_args.kwargs['auto_start'])
        launch.assert_called_once_with(self.source)

    def test_no_start_mode_does_not_launch_and_cancel_does_not_install(self):
        with patch.object(sys,'argv',['setup','--quiet','--no-start','--no-autostart']),patch.object(entry,'install',return_value=setup.Installation(self.source,'digest',False)) as install,patch.object(entry,'launch') as launch:
            self.assertEqual(entry.main(),0)
        self.assertFalse(install.call_args.kwargs['auto_start']);launch.assert_not_called()
        with patch.object(sys,'argv',['setup']),patch.object(entry,'message',return_value=2),patch.object(entry,'install') as install:
            self.assertEqual(entry.main(),0)
        install.assert_not_called()
