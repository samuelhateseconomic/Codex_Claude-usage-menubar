"""S13 native launch, static boundary and shared tray integration regressions."""
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_api import ApiFixture, HttpFixture
import usage_hub_launch as launch
import usage_tray as tray
from usage_api_runtime import HubOwner, launch_destination
from usage_index_db import IndexUnavailable
from usage_runtime import AlreadyRunning
from usage_core import Snapshot, Window
from usage_config import load_settings, save_settings
from test_index import counter


class ProductionAssets(HttpFixture):
    def test_dashboard_and_service_assets_are_local_but_do_not_grant_a_session(self):
        status, headers, body = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.assertIn(b'data-api-mode="v1"', body)
        self.assertIn(b'/local-app.js', body)
        self.assertNotIn('Set-Cookie', headers)
        csp = headers['Content-Security-Policy']
        for directive in ("script-src 'self'", "style-src 'self'", "font-src 'self'", "connect-src 'self'"):
            self.assertIn(directive, csp)
        self.assertNotIn("unsafe-inline", csp)
        for path in ('/local-app.js', '/local-session.js', '/local-view.js', '/v1-client.js', '/v1-schema.js', '/format.js', '/style.css', '/api-bootstrap.js',
                     '/assets/overview.svg', '/assets/Geist.woff2', '/assets/GeistMono.woff2', '/service'):
            with self.subTest(path=path):
                status, headers, body = self.request('GET', path)
                self.assertEqual(status, 200)
                self.assertGreater(len(body), 100)
                self.assertNotIn('Set-Cookie', headers)
        self.assertEqual(self.request('GET', '/api/v1/overview')[0], 403)
        for path in ('/../usage_api.py', '/%2e%2e/AGENTS.md', '/assets/../usage_api.py',
                     '/api/preview/query', '/index.html', '/app.js?raw=1'):
            self.assertEqual(self.request('GET', path)[0], 404, path)
        self.assertEqual(self.request('GET', '/app.js', headers={'Origin':'https://hostile.example'})[0], 403)

    def test_native_launch_destination_preserves_only_valid_local_handoffs(self):
        url = self.origin + '/#launch=synthetic-grant'
        self.assertEqual(launch_destination(url, 'claude'), url + '&provider=claude')
        self.assertEqual(launch_destination(url, status_page=True), self.origin + '/service#launch=synthetic-grant')
        for value in ('https://evil.example/#launch=a', self.origin + '/#anything=a',
                      self.origin + '/?secret=a#launch=b', self.origin + '/#launch=a&launch=b',
                      self.origin + '/wrong#launch=a', self.origin.replace('127.0.0.1', 'localhost') + '/#launch=a'):
            with self.assertRaises(ValueError):
                launch_destination(value)


class NativeLaunch(ApiFixture):
    def invoke(self, *args):
        with patch.dict(os.environ, {'LOCALAPPDATA':str(self.base/'appdata')}), \
             patch.object(sys, 'argv', ['usage_tray', '--config', str(self.config), *args]), \
             patch.object(sys, 'stdout', new_callable=io.StringIO), \
             patch.object(sys, 'stderr', new_callable=io.StringIO):
            return tray.main()

    def test_real_dashboard_is_explicit_offline_and_does_not_load_gui_or_temporary_prices(self):
        with patch.object(launch, 'run_host', return_value=0) as run, \
             patch.object(tray, 'run_tray', side_effect=AssertionError('No legacy tray')), \
             patch.object(tray, 'load_prices', side_effect=AssertionError('Use persisted API settings')):
            self.assertEqual(self.invoke('--dashboard', '--no-browser', '--dashboard-port', '0', '--provider', 'claude'), 0)
        self.assertEqual(run.call_args.kwargs, dict(config_path=self.config, port=0, open_browser=False, selected='claude', tray=False))
        for args in (('--timezone','UTC'), ('--codex-plan-usd','25'), ('--prices',str(self.base/'missing'))):
            with patch.object(launch, 'run_host', side_effect=AssertionError('Reject temporary settings')):
                with self.assertRaises(SystemExit) as result:
                    self.invoke('--dashboard', *args)
                self.assertEqual(result.exception.code, 2)

    def test_default_real_tray_has_shared_live_owner_and_never_automatically_opens_browser(self):
        with patch.object(launch, 'run_host', return_value=0) as run:
            self.assertEqual(self.invoke('--provider', 'codex'), 0)
        self.assertEqual(run.call_args.kwargs, dict(config_path=self.config, port=0, tray=True, live_limits=True, selected='codex', report_format='text'))
        self.assertNotIn('open_browser', run.call_args.kwargs)

    def test_temporary_tray_overrides_and_hub_failure_preserve_legacy_terminal_access(self):
        before = self.config.read_bytes()
        with patch.object(launch, 'run_host', side_effect=AssertionError('Temporary settings stay legacy')), \
             patch.object(tray, 'run_tray') as run:
            self.assertEqual(self.invoke('--codex-plan-usd', '99'), 0)
        self.assertEqual(str(run.call_args.args[4]['Codex']), '99')
        self.assertTrue(run.call_args.kwargs['dashboard_unavailable'])
        self.assertEqual(self.config.read_bytes(), before)
        with patch.object(launch, 'run_host', side_effect=PermissionError('PRIVATE_SENTINEL')), \
             patch.object(tray, 'run_tray') as run:
            self.assertEqual(self.invoke(), 0)
        self.assertTrue(run.call_args.kwargs['dashboard_unavailable'])

    def test_windowed_dashboard_has_an_offline_tray_owner_and_explicit_open(self):
        with patch.dict(os.environ, {'LOCALAPPDATA':str(self.base/'windowed')}), \
             patch.object(sys, 'argv', ['usage_tray','--dashboard','--config',str(self.config)]), \
             patch.object(sys, 'stdout', None), patch.object(launch, 'run_host', return_value=0) as run:
            self.assertEqual(tray.main(), 0)
        self.assertTrue(run.call_args.kwargs['tray'])
        self.assertTrue(run.call_args.kwargs['open_browser'])
        self.assertNotIn('live_limits', run.call_args.kwargs)

    def test_shared_owner_tray_action_uses_fresh_grants_and_quit_releases_everything(self):
        owners = []
        def owner_factory(**kwargs):
            owner = HubOwner(**kwargs)
            owners.append(owner)
            return owner
        def controlled_tray(**kwargs):
            owner = owners[0]
            self.assertIs(kwargs['shared_runtime'], owner.runtime)
            self.assertEqual(owner.runtime.states, ())
            grants = [kwargs['dashboard_opener']() for _ in range(2)]
            self.assertNotEqual(grants[0], grants[1])
            self.assertTrue(all(url.startswith(owner.origin+'/#launch=') and url.endswith('&provider=codex') for url in grants))
            deadline = time.monotonic()+5
            while time.monotonic()<deadline:
                try:
                    result = kwargs['report_query']('month', {})
                    break
                except IndexUnavailable:
                    time.sleep(.025)
            else:
                self.fail('Committed tray query did not become available.')
            self.assertEqual(result.total.tokens.total, 200)
            self.assertEqual(tuple(p for p, _ in result.context.ranges), ('Codex',))
            self.assertTrue(owner.owner.stream)
        with patch.object(launch, 'HubOwner', side_effect=owner_factory), \
             patch.object(tray, 'run_tray', side_effect=controlled_tray), \
             patch.object(launch.webbrowser, 'open', side_effect=AssertionError('Only explicit menu opens')):
            self.assertEqual(launch.run_host(config_path=self.config, index_path=self.path,
                owner_path=self.base/'host.lock', port=0, tray=True, selected='codex'), 0)
        owner = owners[0]
        self.assertIsNone(owner.owner)
        self.assertIsNone(owner.server)
        self.assertFalse(owner.discovery.exists())
        self.assertFalse(owner.jobs.thread.is_alive())

    def test_quit_retains_owner_until_an_inflight_settings_mutation_finishes(self):
        owner_path = self.base/'inflight.lock'
        owner = HubOwner(config_path=self.config, index_path=self.path, owner_path=owner_path, port=0)
        owner.start(start_jobs=False)
        entered, release = threading.Event(), threading.Event()
        outcomes = []
        grant = owner.server.sessions.issue()
        cookie, csrf = owner.server.sessions.exchange(grant)
        origin = owner.origin
        port = owner.server.server_port
        def delayed(settings, path):
            # Pause inside the already admitted mutation, after its writer
            # transaction/queue checks and immediately before JSON replacement.
            entered.set()
            if not release.wait(5):
                raise AssertionError('Controlled mutation was not released.')
            return save_settings(settings, path)
        def client():
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=8)
            try:
                body = {'expected_configuration_version':load_settings(self.config).version,
                        'changes':{'plan_fees_usd':{'Codex':'21','Claude':'20'}}}
                connection.request('PATCH','/api/v1/settings',body=json.dumps(body),headers={
                    'Origin':origin,'Cookie':'usage_hub_v1='+cookie,'X-Usage-CSRF':csrf,'Content-Type':'application/json'})
                response=connection.getresponse()
                outcomes.append((response.status,json.loads(response.read())))
            finally:
                connection.close()
        worker=threading.Thread(target=client)
        try:
            with patch('usage_jobs.save_settings', side_effect=delayed):
                worker.start()
                self.assertTrue(entered.wait(5))
                self.assertFalse(owner.close(timeout=.05))
                self.assertIsNotNone(owner.owner.stream)
                contender=HubOwner(config_path=self.config,index_path=self.path,owner_path=owner_path,port=0)
                with self.assertRaises(AlreadyRunning):contender.start(start_jobs=False)
                release.set();worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(outcomes[0][0],200,outcomes[0][1])
                self.assertEqual(str(dict(load_settings(self.config).plan_fees_usd)['Codex']),'21')
                self.assertTrue(owner.close(timeout=3))
        finally:
            release.set();worker.join(timeout=6);owner.close()
        with HubOwner(config_path=self.config,index_path=self.path,owner_path=owner_path,port=0) as restarted:
            self.assertTrue(restarted.owner.stream)

    def test_clean_quit_cancels_before_publication_and_retains_owner_until_job_stops(self):
        self.write(events=[counter(300,30)])
        owner_path=self.base/'job-quit.lock'
        owner=HubOwner(config_path=self.config,index_path=self.path,owner_path=owner_path,port=0)
        owner.start(start_jobs=False)
        entered,release=threading.Event(),threading.Event()
        def before_commit(fault,stage):
            if stage=='before_commit':
                entered.set()
                if not release.wait(8):raise AssertionError('Controlled publication was not released.')
            if fault is not None:fault(stage)
        try:
            job,_=owner.jobs.submit()
            with patch.object(owner.index,'_fault',side_effect=before_commit):
                owner.jobs.start()
                self.assertTrue(entered.wait(5))
                self.assertEqual(owner.service.read('/overview',{})['data']['summary']['tokens']['total_tokens'],'200')
                self.assertFalse(owner.close(timeout=.05))
                contender=HubOwner(config_path=self.config,index_path=self.path,owner_path=owner_path,port=0)
                with self.assertRaises(AlreadyRunning):contender.start(start_jobs=False)
                release.set()
                self.assertTrue(owner.close(timeout=5))
            self.assertEqual(owner.jobs.get(job['id'])['code'],'interrupted')
            self.assertEqual(owner.jobs.get(job['id'])['status'],'failed')
        finally:
            release.set();owner.close()
        restarted=HubOwner(config_path=self.config,index_path=self.path,owner_path=owner_path,port=0)
        try:
            restarted.start(start_jobs=False)
            self.assertEqual(restarted.service.read('/overview',{})['data']['summary']['tokens']['total_tokens'],'200')
            self.assertEqual(restarted.service.read('/overview',{})['data']['freshness'],'stale')
            restarted.jobs.start()
            deadline=time.monotonic()+6
            while restarted.jobs.active() and time.monotonic()<deadline:time.sleep(.025)
            self.assertEqual(restarted.service.read('/overview',{})['data']['summary']['tokens']['total_tokens'],'300')
        finally:restarted.close()

    def test_explicit_tray_host_honors_saved_report_preference(self):
        from usage_config import effective_settings
        save_settings(effective_settings(load_settings(self.config),report_format='html'),self.config)
        with patch.object(tray,'run_tray') as run:
            self.assertEqual(launch.run_host(config_path=self.config,index_path=self.path,
                owner_path=self.base/'preference.lock',port=0,tray=True),0)
        self.assertEqual(run.call_args.kwargs['report_format'],'html')

    def test_live_tray_and_http_share_one_selected_provider_scheduler(self):
        calls = []
        checked = threading.Event()
        owners = []
        def fetch_codex(**kwargs):
            calls.append(kwargs['cancel_event'])
            checked.set()
            return Snapshot('Codex', [Window('primary', 25, time.time()+300, 300)], checked_at=time.time())
        def owner_factory(**kwargs):
            owner = HubOwner(**kwargs)
            owners.append(owner)
            return owner
        def controlled_tray(**kwargs):
            self.assertTrue(checked.wait(5))
            owner = owners[0]
            deadline = time.monotonic()+5
            while owner.runtime.states[0].view().snapshot is None and time.monotonic()<deadline:
                time.sleep(.01)
            limits = owner.service.read('/limits', {})['data']['providers']
            codex = next(row for row in limits if row['provider']=='codex')
            self.assertEqual(codex['snapshot']['windows'][0]['remaining_percent'], 75)
            self.assertEqual(len(calls), 1)
            self.assertIs(calls[0], kwargs['shared_runtime'].stop)
            # A second native launch neither changes profile nor polls again.
            self.assertEqual(launch.run_host(config_path=self.config, index_path=self.path,
                owner_path=self.base/'live.lock', port=0, live_limits=True), 0)
            self.assertEqual(len(calls), 1)
            result = owner.service.mutate('POST', '/limits/refresh', {'providers':['codex']})
            self.assertEqual(result[0], 429)
        with patch.object(launch, 'HubOwner', side_effect=owner_factory), \
             patch('usage_core.fetch_codex', side_effect=fetch_codex), \
             patch('usage_core.fetch_claude', side_effect=AssertionError('Only selected Codex is polled')), \
             patch.object(tray, 'run_tray', side_effect=controlled_tray):
            self.assertEqual(launch.run_host(config_path=self.config, index_path=self.path,
                owner_path=self.base/'live.lock', port=0, tray=True, live_limits=True, selected='codex'), 0)
        self.assertFalse(owners[0].runtime.threads[0].is_alive())

    def test_repeated_explicit_launch_reuses_owner_and_keeps_its_profile(self):
        owner_path = self.base/'reuse.lock'
        owner = HubOwner(config_path=self.config, index_path=self.path, owner_path=owner_path, port=0)
        owner.start(start_jobs=False)
        try:
            with patch.object(launch.webbrowser, 'open', return_value=True) as opened:
                self.assertEqual(launch.run_host(config_path=self.config, index_path=self.path,
                    owner_path=owner_path, port=0, open_browser=True, selected='claude'), 0)
            url = opened.call_args.args[0]
            self.assertTrue(url.startswith(owner.origin+'/#launch='))
            self.assertTrue(url.endswith('&provider=claude'))
            grant = parse_qs(urlsplit(url).fragment)['launch'][0]
            cookie, csrf = owner.server.sessions.exchange(grant)
            self.assertTrue(cookie and csrf)
            self.assertEqual(owner.runtime.states, ())
            self.assertIsNotNone(owner.owner.stream)
        finally:
            owner.close()

    def test_real_tray_menu_only_opens_on_action_and_quit_stops_shared_host(self):
        opened = threading.Event()
        destinations = []
        class Item:
            def __init__(self, text, action=None, **kwargs):
                self.text, self.action = text, action
        class Menu:
            SEPARATOR = object()
            def __init__(self, items): self.items = items
        class Icon:
            def __init__(self, *args): self.menu = args[3]
            def update_menu(self): pass
            def stop(self): pass
            def run(icon, setup):
                setup(icon)
                self.assertFalse(opened.is_set())
                items = [item for item in icon.menu.items() if isinstance(item, Item)]
                self.assertTrue(any('Live limits disabled' in item.text for item in items))
                next(item for item in items if item.text=='Open usage dashboard...').action(icon, None)
                self.assertTrue(opened.wait(5), 'Explicit tray dashboard action did not open.')
                # The browser is only a client; closing/discarding its handle
                # does not cancel the runtime. Quit remains the native action.
                origin = urlsplit(destinations[0])
                connection = http.client.HTTPConnection(origin.hostname, origin.port, timeout=5)
                connection.request('GET', '/service')
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                response.read(); connection.close()
                next(item for item in items if item.text=='Quit').action(icon, None)
        fake = types.SimpleNamespace(Icon=Icon, Menu=Menu, MenuItem=Item)
        def open_browser(url):
            destinations.append(url)
            opened.set()
            return True
        with patch.dict(sys.modules, {'pystray':fake}), patch.object(launch.webbrowser, 'open', side_effect=open_browser):
            self.assertEqual(launch.run_host(config_path=self.config, index_path=self.path,
                owner_path=self.base/'menu.lock', port=0, tray=True), 0)
        self.assertEqual(len(destinations), 1)
        self.assertFalse((self.base/'menu.api.json').exists())

    def test_actual_real_dashboard_cli_uses_v1_and_reuses_owner_without_polling(self):
        env = dict(os.environ, LOCALAPPDATA=str(self.base/'process-appdata'))
        command = [sys.executable, '-u', str(Path(tray.__file__)), '--dashboard', '--no-browser',
                   '--config', str(self.config), '--dashboard-port', '0']
        child = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            discovery = Path(env['LOCALAPPDATA'])/'UsageTray'/'runtime.api.json'
            deadline = time.monotonic()+10
            while not discovery.exists() and child.poll() is None and time.monotonic()<deadline:
                time.sleep(.025)
            self.assertTrue(discovery.exists(), 'Real dashboard launch failed to start.')
            native = json.loads(discovery.read_text(encoding='utf-8'))
            parsed = urlsplit(native['origin'])
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            connection.request('GET','/')
            response=connection.getresponse()
            self.assertEqual(response.status,200)
            self.assertIn(b'data-api-mode="v1"',response.read())
            connection.close()
            repeated = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10,
                                      creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.assertEqual(repeated.returncode,0,repeated.stderr)
            self.assertIn('Reusing the existing local API owner',repeated.stdout)
            self.assertNotIn('launch=',repeated.stdout)
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
            connection.request('POST','/api/v1/local/launch',body='{}',
                headers={'Content-Type':'application/json','X-Usage-Owner':native['control']})
            response=connection.getresponse();handoff=json.loads(response.read())
            self.assertEqual(response.status,200)
            connection.close()
            self.assertTrue(handoff['data']['url'].startswith(native['origin']+'/#launch='))
        finally:
            child.terminate()
            try:child.communicate(timeout=10)
            except subprocess.TimeoutExpired:child.kill();child.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
