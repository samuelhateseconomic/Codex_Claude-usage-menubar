"""Bounded offline acceptance of the actual windowed executable. No real histories."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_identity import APP_VERSION
from usage_process import ChildTree
from usage_runtime import RuntimeOwner


class SmokeFailure(Exception):
    pass


def require(condition, message):
    if not condition:
        raise SmokeFailure(message)


def check_executable(executable):
    executable = Path(executable).resolve(strict=True)
    require(os.name == 'nt', 'Windows executable checks require Windows.')
    fingerprint = 'exe-sha256:' + hashlib.sha256(executable.read_bytes()).hexdigest()
    passed = []
    with tempfile.TemporaryDirectory(prefix='usage-release-') as temporary:
        root = Path(temporary)
        for name in ('codex/sessions', 'codex/archived_sessions', 'claude/projects', 'appdata', 'zoneinfo'):
            (root/name).mkdir(parents=True)
        env = dict(os.environ, CODEX_HOME=str(root/'codex'), CLAUDE_CONFIG_DIR=str(root/'claude'),
                   LOCALAPPDATA=str(root/'appdata'), PYTHONTZPATH=str(root/'zoneinfo'), TEMP=str(root), TMP=str(root))
        # No --once live, --open-report or tray invocation: every command stays offline.
        def command(name, args, expected=0):
            owner = ChildTree()
            try:
                process = owner.start([str(executable), *args], env=env, cwd=root,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                code = process.wait(timeout=30)
                require(code == expected, name + ': unexpected exit status.')
            finally:
                owner.close()
            passed.append(name)
            print(json.dumps(dict(case=name, exit=code)), flush=True)

        def read(name):
            return (root/name).read_text(encoding='utf-8')

        def data(name):
            return json.loads(read(name))

        command('version', ['--version', '--output', str(root/'version.json')])
        require(data('version.json')['app_version'] == APP_VERSION and data('version.json')['build_id'] == fingerprint,
                'Executable version or hash does not match source/artifact.')
        require(data('version.json')['python_version'].split('.')[:2] == [str(v) for v in sys.version_info[:2]],
                'Frozen Python does not match the project build interpreter.')
        command('bundled-named-timezone', ['--diagnostics', '--timezone', 'America/Los_Angeles', '--output', str(root/'info.json')])
        require(data('info.json')['timezone'] == 'America/Los_Angeles', 'Named timezone unavailable with host search path disabled.')
        command('demo-text', ['--report', 'week', '--demo', '--output', str(root/'demo.txt')])
        require(all(s in read('demo.txt') for s in ('DEMO', '108,000', '$0.2658')), 'Demo accounting differs.')
        command('demo-html', ['--report', 'week', '--demo', '--report-format', 'html', '--output', str(root/'demo.html')])
        require('<html' in read('demo.html') and '108,000' in read('demo.html'), 'Saved HTML unavailable.')

        # Pick a timestamp inside this calendar month; never use wall-clock fixture dates.
        now = time.time()
        month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        stamp = datetime.fromtimestamp(max(month_start, now-1), timezone.utc).isoformat()
        sentinel = 'RELEASE-PRIVATE-CONTENT-SENTINEL'
        codex = root/'codex/sessions/fixture.jsonl'
        entries = [dict(type='session_meta', payload=dict(id='private-fixture-session', cwd='C:/private-parent/project', secret=sentinel)),
                   dict(type='turn_context', payload=dict(model='release-codex', effort='high')),
                   dict(type='event_msg', timestamp=stamp, payload=dict(type='token_count', info=dict(total_token_usage=dict(
                       input_tokens=1010000, output_tokens=1830000, cached_input_tokens=1000000, reasoning_output_tokens=1260000))))]
        codex.write_text('\n'.join(json.dumps(e) for e in entries)+'\n', encoding='utf-8')
        claude = dict(type='assistant', timestamp=stamp, sessionId='private-claude', cwd='C:/private-parent/project',
                      message=dict(id='private-message', model='release-claude', content=[dict(text=sentinel)], usage=dict(
                          input_tokens=10000, output_tokens=20000, cache_read_input_tokens=30000,
                          cache_creation_input_tokens=5000, cache_creation=dict(ephemeral_5m_input_tokens=5000, ephemeral_1h_input_tokens=0))))
        (root/'claude/projects/fixture.jsonl').write_text(json.dumps(claude)+'\n', encoding='utf-8')
        prices = {'release-codex': dict(input='2', output='10', cached='0.1'),
                  'release-claude': dict(input='4', output='20', cached='0.2', write5m='5', write1h='8')}
        (root/'prices.json').write_text(json.dumps(prices), encoding='utf-8')
        command('persist-settings', ['--save-settings', '--timezone', 'UTC', '--codex-plan-usd', '30.000000000001',
                '--claude-plan-usd', '0', '--prices', str(root/'prices.json'), '--codex-root', str(codex.parent),
                '--claude-root', str(root/'claude/projects')])
        config = root/'appdata/UsageTray/settings.json'
        original = config.read_bytes()
        env.update(CODEX_HOME=str(root/'unused'), CLAUDE_CONFIG_DIR=str(root/'unused'))
        command('restart-exact-accounting', ['--report', 'month', '--output', str(root/'local.txt'),
                                            '--diagnostic-output', str(root/'operation.json')])
        text = read('local.txt')
        require(all(s in text for s in ('2,905,000', '$18.8910', '-$11.11', 'Pricing coverage: complete')), 'Persisted accounting differs.')
        require(all(s not in text for s in (sentinel, 'private-parent', 'private-fixture-session')), 'Default report leaked protected fixture metadata.')
        operation = data('operation.json')
        require(operation['build_id'] == fingerprint and operation['counts']['records'] == 2 and operation['status'] == 'success', 'Operation identity/counts differ.')
        command('ephemeral-override', ['--report', 'month', '--codex-plan-usd', '0', '--report-format', 'html', '--output', str(root/'override.html')])
        require('+$18.89' in read('override.html') and config.read_bytes() == original, 'Temporary settings were persisted or fee comparison differs.')
        with RuntimeOwner(root/'appdata/UsageTray/runtime.lock'):
            command('offline-with-runtime-owner', ['--report', 'month', '--output', str(root/'owned.txt')])
        command('empty-is-not-zero', ['--report', 'month', '--codex-root', str(root/'zoneinfo'), '--claude-root', str(root/'zoneinfo'), '--output', str(root/'empty.txt')])
        require('Pricing coverage: empty' in read('empty.txt') and 'does not establish zero account usage' in read('empty.txt'), 'Empty coverage is ambiguous.')
        settings = json.loads(original)
        settings['rate_overrides'] = {}
        config.write_text(json.dumps(settings), encoding='utf-8')
        command('all-unpriced-is-not-zero', ['--report', 'month', '--output', str(root/'unpriced.txt')])
        require('Unavailable (all usage unpriced)' in read('unpriced.txt') and '$0.0000' not in read('unpriced.txt'), 'Unknown models were priced as zero.')
        settings['rate_overrides'] = {name: {field:'0' for field in rate} for name,rate in prices.items()}
        config.write_text(json.dumps(settings), encoding='utf-8')
        command('explicit-zero-rates', ['--report', 'month', '--output', str(root/'zero.txt')])
        require('Pricing coverage: complete' in read('zero.txt') and '$0.0000' in read('zero.txt'), 'Legitimate zero rates unavailable.')
        config.write_bytes(original)
        with codex.open('a', encoding='utf-8') as stream:
            stream.write(sentinel+'\n')
        command('partial-source-diagnostics', ['--report', 'month', '--output', str(root/'partial.txt'), '--diagnostic-output', str(root/'partial.json')])
        require(data('partial.json')['status'] == 'partial' and sentinel not in read('partial.json'), 'Partial source diagnostics differ.')
        config.write_text(sentinel, encoding='utf-8')
        command('corrupt-settings-recovery', ['--diagnostics', '--output', str(root/'invalid.json')], 2)
        require(data('invalid.json')['operation']['category'] == 'settings_invalid' and config.read_text() == sentinel, 'Invalid settings were overwritten or misclassified.')
        command('version-with-invalid-settings', ['--version', '--output', str(root/'invalid-version.json')])
        require(data('invalid-version.json')['build_id'] == fingerprint, 'Version unavailable during recovery.')
        require(all(sentinel not in read(name) for name in ('demo.txt','demo.html','local.txt','operation.json','override.html','owned.txt','empty.txt','unpriced.txt','zero.txt','partial.txt','partial.json','invalid.json','invalid-version.json')),
                'Protected content entered a release export.')
    return dict(schema=1, app_version=APP_VERSION, build_id=fingerprint, cases=passed, count=len(passed), passed=True,
                scope='offline synthetic executable; no native GUI, real providers or real histories')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, default=Path(__file__).resolve().parents[1]/'dist/UsageTray.exe')
    args = parser.parse_args()
    try:
        result = check_executable(args.exe)
    except SmokeFailure as exc:
        print('Packaged release check failed: ' + str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        # Keep child output, filesystem paths and arbitrary exception text out of CI logs.
        print('Packaged release check failed; inspect this script and rerun with the matching built executable.', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
