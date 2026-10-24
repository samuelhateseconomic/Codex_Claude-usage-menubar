"""Real Windows sharing-violation regression for owned smoke-fixture cleanup."""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from packaged_local_hub_smoke import synthetic_workspace


@unittest.skipUnless(os.name == 'nt', 'Windows file-sharing semantics')
class PackagedFixtureCleanup(unittest.TestCase):
    def test_locked_fixture_waits_for_handle_release_and_preserves_neighbor(self):
        with tempfile.TemporaryDirectory() as folder:
            scratch = Path(folder)
            neighbor = scratch/'preserve.txt'
            neighbor.write_text('unrelated fixture', encoding='utf-8')
            stream = worker = None
            try:
                with synthetic_workspace(scratch, cleanup_timeout=5) as owned:
                    lock = owned/'runtime.lock'
                    lock.write_bytes(b'0')
                    stream = lock.open('rb')
                    def release():
                        time.sleep(.2)
                        stream.close()
                    worker = threading.Thread(target=release)
                    worker.start()
                self.assertFalse(owned.exists())
                self.assertEqual(neighbor.read_text(encoding='utf-8'), 'unrelated fixture')
            finally:
                if stream is not None:stream.close()
                if worker is not None:worker.join(timeout=3)

    def test_persistent_sharing_failure_is_reported_without_ignoring_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            stream = None
            try:
                with self.assertRaises(PermissionError):
                    with synthetic_workspace(Path(folder), cleanup_timeout=.15) as owned:
                        lock = owned/'runtime.lock'
                        lock.write_bytes(b'0')
                        stream = lock.open('rb')
                self.assertTrue(owned.exists())
            finally:
                if stream is not None:stream.close()


class PackagedUnsupportedFixture(unittest.TestCase):
    def make_backup(self, folder):
        from usage_config import Settings,effective_settings,save_settings
        from usage_index import UsageIndex
        from usage_valuation import Price
        from test_index import header,counter,context
        import json
        root=Path(folder)
        logs=root/'sources';logs.mkdir()
        (logs/'synthetic.jsonl').write_text('\n'.join(map(json.dumps,header()+[counter(100,10),counter(200,20)]))+'\n',encoding='utf-8')
        config=root/'settings.json'
        save_settings(effective_settings(Settings(),timezone='UTC',codex_roots=[logs],claude_roots=[],prices={'fixture-model':Price('2','10','.1')}),config)
        store=UsageIndex(root/'original.sqlite3',config_path=config)
        store.import_settings()
        return root,store,config,store.backup(),context()

    def test_unsupported_copy_preserves_original_backup_and_configuration(self):
        from contextlib import closing
        import sqlite3
        from packaged_hub_release import unsupported_copy
        with tempfile.TemporaryDirectory() as folder:
            root,store,config,backup,context=self.make_backup(folder)
            original=store.path.read_bytes();archived=backup.read_bytes();settings=config.read_bytes()
            destination=root/'unsupported'/'index.sqlite3';new_config=destination.with_name('settings.json')
            unsupported_copy(backup,destination,new_config)
            with closing(sqlite3.connect(destination)) as connection:
                self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0],99)
                self.assertEqual(connection.execute('SELECT sum(total) FROM events').fetchone()[0],200)
            self.assertEqual(store.path.read_bytes(),original)
            self.assertEqual(backup.read_bytes(),archived)
            self.assertEqual(config.read_bytes(),settings)
            self.assertEqual(store.query(context).result.total.tokens.total,200)

    def test_unsupported_copy_refuses_existing_target_instead_of_mutating_it(self):
        from packaged_hub_release import unsupported_copy
        with tempfile.TemporaryDirectory() as folder:
            root,store,config,backup,context=self.make_backup(folder)
            original=store.path.read_bytes();settings=config.read_bytes()
            with self.assertRaises(ValueError):unsupported_copy(backup,store.path,config)
            self.assertEqual(store.path.read_bytes(),original)
            self.assertEqual(config.read_bytes(),settings)
            self.assertEqual(store.query(context).result.total.tokens.total,200)


if __name__ == '__main__':unittest.main()
