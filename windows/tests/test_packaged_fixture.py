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


if __name__ == '__main__':unittest.main()
