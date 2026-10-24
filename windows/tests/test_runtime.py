"""S07 scheduling, ownership, cleanup and tray lifecycle acceptance."""
from dataclasses import replace
import errno
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import usage_core as core
import usage_runtime as runtime
import usage_tray as tray
import usage_process as owned
import usage_artifacts as artifacts
import usage_reports as reports
from usage_failures import report_failure


def wait_for(predicate, timeout=3):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate(): return
        time.sleep(.01)
    raise AssertionError("Fixture did not reach expected state")


class SchedulingTests(unittest.TestCase):
    def test_hung_provider_does_not_block_other_provider_and_refresh_fans_out(self):
        entered, release, done = threading.Event(), threading.Event(), threading.Event()
        def slow():
            entered.set(); release.wait(3)
            return core.demo_snapshot("Codex")
        fast=Mock(side_effect=lambda: (done.set(),core.demo_snapshot("Claude"))[1])
        engine=runtime.PollingRuntime({"Codex":slow,"Claude":fast})
        engine.start(); engine.start()
        try:
            self.assertTrue(entered.wait(1)); self.assertTrue(done.wait(1))
            for _ in range(30): engine.refresh()
            self.assertEqual(fast.call_count,1)
            self.assertEqual(len(engine.threads),2)
        finally:
            release.set(); self.assertTrue(engine.close(3))
        self.assertFalse(any(t.is_alive() for t in engine.threads))

    def test_each_provider_wakes_when_due_and_cooldown_requests_do_not_redraw(self):
        changed=Mock()
        calls={p:Mock(return_value=core.demo_snapshot(p)) for p in ("Codex","Claude")}
        engine=runtime.PollingRuntime(calls,changed=changed)
        engine.start()
        try:
            wait_for(lambda: all(state.delay()>0 for state in engine.states) and changed.call_count>=4)
            before=changed.call_count
            for _ in range(20): engine.refresh()
            time.sleep(.05)
            self.assertEqual(changed.call_count,before)
            self.assertTrue(all(fetch.call_count==1 for fetch in calls.values()))
            for state in engine.states:
                with state.lock: state.next_check=0
            engine.refresh()
            wait_for(lambda: all(fetch.call_count==2 for fetch in calls.values()))
        finally:
            self.assertTrue(engine.close(3))

    def test_same_provider_concurrent_refresh_has_one_request(self):
        entered, release=threading.Event(),threading.Event()
        def fetch():
            entered.set();release.wait(2);return core.demo_snapshot("Codex")
        fetch=Mock(side_effect=fetch)
        state=runtime.ProviderState("Codex",fetch)
        thread=threading.Thread(target=state.refresh);thread.start()
        try:
            self.assertTrue(entered.wait(1))
            others=[threading.Thread(target=state.refresh) for _ in range(15)]
            for worker in others: worker.start()
            for worker in others: worker.join(1);self.assertFalse(worker.is_alive())
            self.assertEqual(fetch.call_count,1)
            self.assertEqual(state.view().phase,"refreshing")
        finally:
            release.set();thread.join(2)
        self.assertEqual(state.view().phase,"cooldown")

    def test_monotonic_deadline_survives_wall_clock_changes_and_display_is_derived(self):
        mono,wall=[100.0],[2000.0]
        fetch=Mock(return_value=core.demo_snapshot("Codex"))
        state=runtime.ProviderState("Codex",fetch,monotonic=lambda:mono[0],wall_time=lambda:wall[0])
        state.refresh();self.assertEqual(state.next_check,400)
        self.assertEqual(state.view().retry_at,2300)
        wall[0]-=10000;mono[0]+=50
        self.assertEqual(state.view().retry_at,-7750)
        self.assertFalse(state.refresh());self.assertEqual(fetch.call_count,1)
        wall[0]+=100000;mono[0]=400
        self.assertTrue(state.refresh());self.assertEqual(fetch.call_count,2)

    def test_failure_categories_stale_snapshot_retry_after_and_recovery(self):
        clock=[10.0]
        good=core.demo_snapshot("Claude")
        fetch=Mock(side_effect=[good,core.UsageError("Sign in",category="login_required"),core.RateLimited(900),good])
        state=runtime.ProviderState("Claude",fetch,monotonic=lambda:clock[0])
        state.refresh();accepted=state.snapshot
        clock[0]=310;state.refresh()
        self.assertIs(state.snapshot,accepted);self.assertEqual(state.view().category,"login_required")
        self.assertIn("out of date"," ".join(state.lines()))
        clock[0]=610;state.refresh();self.assertEqual(state.next_check,1510)
        self.assertEqual(state.view().category,"cooldown")
        clock[0]=1510;state.refresh();self.assertEqual(state.failures,0)
        self.assertEqual(state.view().category,"success");self.assertEqual(state.error,"")
        self.assertIsInstance(state.snapshot.windows,tuple)

    def test_blocked_success_is_distinct_and_unknown_failures_are_sanitized(self):
        blocked=core.parse_codex({"ordinaryUsageAllowed":False,"rateLimits":{"primary":{"usedPercent":20}}})
        state=runtime.ProviderState("Codex",lambda:blocked)
        state.refresh();self.assertEqual(state.view().category,"blocked")
        self.assertIn("blocked:"," ".join(state.lines()))
        for failure in (RuntimeError("PRIVATE_SENTINEL"),ValueError("PRIVATE_SENTINEL")):
            other=runtime.ProviderState("Claude",Mock(side_effect=failure));other.refresh()
            self.assertEqual(other.view().category,"unexpected_local")
            self.assertNotIn("PRIVATE_SENTINEL"," ".join(other.lines()))
        unsupported=runtime.ProviderState("Codex",lambda:None);unsupported.refresh()
        self.assertEqual(unsupported.category,"unsupported_response")

    def test_shutdown_before_start_and_during_uncooperative_thread_are_bounded(self):
        fetch=Mock()
        engine=runtime.PollingRuntime({"Codex":fetch});self.assertTrue(engine.close(.01));engine.start();fetch.assert_not_called()
        entered,release=threading.Event(),threading.Event()
        def slow(): entered.set();release.wait(2);return core.demo_snapshot("Codex")
        engine=runtime.PollingRuntime({"Codex":slow});engine.start();self.assertTrue(entered.wait(1))
        try:
            self.assertFalse(engine.close(.01));self.assertEqual(engine.states[0].view().phase,"stopped")
        finally: release.set();self.assertTrue(engine.close(3))
        self.assertIsNone(engine.states[0].snapshot)

    def test_runtime_import_needs_no_gui_or_report_modules(self):
        code="import sys;import usage_runtime;assert not any(m in sys.modules for m in ('pystray','PIL','usage_reports','usage_tray'));print('headless')"
        result=subprocess.run([sys.executable,"-c",code],cwd=Path(runtime.__file__).parent,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


class OwnershipTests(unittest.TestCase):
    def test_other_process_rejected_then_crash_releases_lock_for_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);lock=root/"runtime.lock";ready=root/"ready"
            code="""from pathlib import Path
import sys,time
from usage_runtime import RuntimeOwner
with RuntimeOwner(sys.argv[1]):
 Path(sys.argv[2]).write_text('ready');time.sleep(30)
"""
            owner_tree=owned.ChildTree()
            child=owner_tree.start([sys.executable,"-c",code,str(lock),str(ready)],cwd=Path(runtime.__file__).parent)
            try:
                wait_for(ready.exists)
                with self.assertRaises(runtime.AlreadyRunning):
                    with runtime.RuntimeOwner(lock): pass
                env=dict(os.environ,LOCALAPPDATA=folder)
                with runtime.RuntimeOwner(root/"UsageTray/runtime.lock"):
                    duplicate=subprocess.run([sys.executable,str(Path(tray.__file__)),"--demo"],env=env,capture_output=True,text=True,timeout=10)
                    self.assertEqual(duplicate.returncode,3)
                    self.assertIn("already running",duplicate.stderr)
                    # Offline reports and version diagnostics are not polling owners.
                    offline=subprocess.run([sys.executable,str(Path(tray.__file__)),"--report","month","--demo"],env=env,capture_output=True,text=True,timeout=10)
                    self.assertEqual(offline.returncode,0,offline.stderr)
            finally:
                owner_tree.close()
            with runtime.RuntimeOwner(lock): pass
            self.assertTrue(lock.exists())


@unittest.skipUnless(os.name=="nt","Windows child-tree containment")
class ChildCleanupTests(unittest.TestCase):
    def test_cancelled_rpc_kills_child_and_descendant_but_not_unrelated_process(self):
        import ctypes as C
        from ctypes import wintypes as W
        kernel=C.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
        kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD
        kernel.CloseHandle.argtypes=[W.HANDLE]
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/"pids.json";cancel=threading.Event()
            client=core.RpcClient([sys.executable,str(Path(__file__).with_name("fake_codex.py")),"descendant",str(marker)],timeout=30,cancel_event=cancel)
            errors=[]
            def invoke():
                try:
                    with client: pass
                except core.UsageError as exc: errors.append(exc.category)
            unrelated_tree=owned.ChildTree()
            unrelated=unrelated_tree.start([sys.executable,"-c","import time;time.sleep(30)"])
            worker=threading.Thread(target=invoke);worker.start()
            handle=None
            try:
                wait_for(marker.exists)
                child=json.loads(marker.read_text())["child"]
                handle=kernel.OpenProcess(0x100000,False,child);self.assertTrue(handle)
                cancel.set();worker.join(5)
                self.assertFalse(worker.is_alive());self.assertEqual(errors,["cancelled"])
                self.assertIsNotNone(client.process.poll());self.assertFalse(client.reader.is_alive())
                self.assertEqual(kernel.WaitForSingleObject(handle,3000),0)
                self.assertIsNone(unrelated.poll())
            finally:
                cancel.set();worker.join(5);client.tree.close()
                if handle: kernel.CloseHandle(handle)
                unrelated_tree.close()

    def test_parent_crash_closes_rpc_job_and_terminates_descendants(self):
        import ctypes as C
        from ctypes import wintypes as W
        kernel=C.WinDLL("kernel32",use_last_error=True)
        kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
        kernel.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];kernel.WaitForSingleObject.restype=W.DWORD
        kernel.TerminateProcess.argtypes=[W.HANDLE,W.UINT]
        kernel.CloseHandle.argtypes=[W.HANDLE]
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/"pids.json"
            code="import sys;from usage_core import RpcClient;client=RpcClient([sys.executable,sys.argv[1],'descendant',sys.argv[2]],timeout=30);client.__enter__()"
            # Use the real interpreter, not a venv redirector, to kill exactly
            # the parent holding the RPC job handle (no outer fixture job).
            parent=subprocess.Popen([sys._base_executable,"-c",code,str(Path(__file__).with_name("fake_codex.py")),str(marker)],
                cwd=Path(core.__file__).parent,creationflags=subprocess.CREATE_NO_WINDOW)
            handles=[]
            try:
                # Cold interpreter/AV startup is not the process cleanup deadline.
                # Stop early on fixture exit; retain the separate 3s kill assertions.
                wait_for(lambda: marker.exists() or parent.poll() is not None, timeout=10)
                self.assertTrue(marker.exists(), "RPC fixture exited before readiness")
                pids=json.loads(marker.read_text())
                handles=[kernel.OpenProcess(0x100001,False,pid) for pid in pids.values()]
                self.assertTrue(all(handles))
                parent.kill();parent.wait(5)
                self.assertTrue(all(kernel.WaitForSingleObject(handle,3000)==0 for handle in handles))
            finally:
                if parent.poll() is None: parent.kill();parent.wait(5)
                for handle in handles:
                    if handle:
                        kernel.TerminateProcess(handle,1);kernel.CloseHandle(handle)

    def test_failed_job_assignment_never_runs_child_code(self):
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/"must-not-exist"
            tree=owned.ChildTree()
            with patch.object(owned.K,"AssignProcessToJobObject",return_value=0):
                with self.assertRaises(OSError):
                    tree.start([sys.executable,"-c","from pathlib import Path;import sys;Path(sys.argv[1]).write_text('bad')",str(marker)],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE)
            self.assertFalse(marker.exists());self.assertIsNotNone(tree.process.poll());self.assertIsNone(tree.job)


class ArtifactAndFailureTests(unittest.TestCase):
    def test_report_failures_are_categorized_without_raw_exception_contents(self):
        for exc,phase,expected in ((PermissionError("PRIVATE_SENTINEL"),"save","permission_denied"),
            (OSError(errno.ENOSPC,"PRIVATE_SENTINEL"),"save","disk_full"),
            (OSError("PRIVATE_SENTINEL"),"query","io_error"),(ValueError("PRIVATE_SENTINEL"),"query","invalid_data"),
            (RuntimeError("PRIVATE_SENTINEL"),"query","unexpected_local"),(OSError("PRIVATE_SENTINEL"),"open","open_failed")):
            with self.subTest(expected=expected):
                outcome=report_failure(exc,phase);self.assertEqual(outcome.category,expected)
                self.assertNotIn("PRIVATE_SENTINEL",str(outcome))

    def test_cli_viewer_failure_preserves_saved_report_and_reports_open_phase(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/"report.txt"
            args=["usage_tray","--report","month","--demo","--output",str(output),"--open-report"]
            with patch.dict(os.environ,{"LOCALAPPDATA":folder}),patch.object(sys,"argv",args), \
                 patch.object(tray,"open_report",side_effect=OSError("PRIVATE_SENTINEL")),patch.object(sys,"stdout",new_callable=io.StringIO),patch.object(sys,"stderr",new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit) as result: tray.main()
                self.assertEqual(result.exception.code,1)
                self.assertIn("open_failed",stderr.getvalue());self.assertNotIn("PRIVATE_SENTINEL",stderr.getvalue())
            self.assertIn("108,000",output.read_text(encoding="utf-8"))

    def test_retention_bounds_only_generated_matching_regular_files(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{"LOCALAPPDATA":folder}):
            root=artifacts.generated_directory();root.mkdir(parents=True)
            now=time.time()
            for i in range(105):
                path=root/f"usage-20261024-120000-{i:08d}.txt";path.write_text("synthetic")
                os.utime(path,(now-i,now-i))
            old=root/"usage-20200101-000000-oldfile0.html";old.write_text("synthetic");os.utime(old,(now-31*86400,)*2)
            unrelated=root/"user-export.txt";unrelated.write_text("preserve")
            legacy=root.parent/"usage-20200101-000000-oldfile0.txt";legacy.write_text("preserve")
            history=Path(folder)/"source-history.jsonl";history.write_text("preserve")
            outcome=artifacts.prune_reports(now=now)
            self.assertFalse(outcome.failed);self.assertEqual(outcome.removed,6)
            self.assertEqual(len([p for p in root.iterdir() if artifacts.NAME.fullmatch(p.name)]),100)
            self.assertTrue(all(p.exists() for p in (unrelated,legacy,history)))
            saved=reports.save_report(reports.collect_report(demo=True),format="text")
            self.assertEqual(saved.parent,root);self.assertTrue(saved.exists())
            self.assertEqual(len([p for p in root.iterdir() if artifacts.NAME.fullmatch(p.name)]),100)
            with self.assertRaises(ValueError): reports.save_report(reports.collect_report(demo=True),root/"explicit.txt",format="text")

    def test_current_report_is_protected_and_counts_toward_cap_after_clock_change(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{"LOCALAPPDATA":folder}):
            root=artifacts.generated_directory();root.mkdir(parents=True)
            now=time.time()
            for i in range(100):
                path=root/f"usage-20261024-120000-{i:08d}.txt";path.write_text("future")
                os.utime(path,(now+86400,)*2)
            current=root/"usage-20261024-120000-current0.txt";current.write_text("current")
            outcome=artifacts.prune_reports(keep=current,now=now)
            self.assertEqual(outcome.removed,1);self.assertTrue(current.exists())
            self.assertEqual(len(list(root.iterdir())),100)

    def test_linked_generated_directory_refuses_cleanup(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{"LOCALAPPDATA":folder}):
            root=artifacts.generated_directory();root.mkdir(parents=True)
            with patch.object(artifacts,"_reparse",return_value=True):
                self.assertTrue(artifacts.prune_reports().failed)
                with self.assertRaises(OSError): artifacts.generated_directory()

    def test_retention_failure_does_not_delete_source_or_hide_saved_report(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{"LOCALAPPDATA":folder}):
            with patch.object(artifacts.Path,"unlink",side_effect=PermissionError("PRIVATE_SENTINEL")):
                root=artifacts.generated_directory();root.mkdir(parents=True)
                old=root/"usage-20200101-000000-oldfile0.txt";old.write_text("old");os.utime(old,(1,1))
                self.assertTrue(artifacts.prune_reports().failed)
                with self.assertWarnsRegex(RuntimeWarning,"retention"):
                    saved=reports.save_report(reports.collect_report(demo=True),format="text")
                self.assertTrue(saved.exists());self.assertTrue(old.exists())


class TrayLifecycleTests(unittest.TestCase):
    def test_simulated_tray_refresh_quit_restart_and_no_idle_redraw_loop(self):
        icons=[]
        class Item:
            def __init__(self,text,action=None,**kw): self.text,self.action=text,action
        class Menu:
            SEPARATOR=object()
            def __init__(self,items): self.items=items
        class Icon:
            def __init__(self,*args):
                self.menu=args[3];self.updates=0;self.stopped=False;icons.append(self)
            def update_menu(self): self.updates+=1
            def stop(self): self.stopped=True
            def run(self,setup):
                setup(self)
                wait_for(lambda:self.updates>0)
                before=self.updates
                # Let startup state notifications settle before measuring idle.
                time.sleep(.05);before=self.updates;time.sleep(.05)
                self.assert_idle=(self.updates==before)
                items=list(self.menu.items())
                next(item for item in items if isinstance(item,Item) and item.text.startswith("Refresh")).action(self,None)
                next(item for item in items if isinstance(item,Item) and item.text=="Quit").action(self,None)
        fake=types.SimpleNamespace(Icon=Icon,Menu=Menu,MenuItem=Item)
        with patch.dict(sys.modules,{"pystray":fake}):
            for _ in range(2): tray.run_tray(demo=True)
        self.assertTrue(all(icon.stopped and icon.assert_idle for icon in icons))
        self.assertFalse(any(t.name.startswith("usage-") and t.is_alive() for t in threading.enumerate()))


if __name__=="__main__": unittest.main()
