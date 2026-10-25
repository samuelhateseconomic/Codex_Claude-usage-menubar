"""System preference, DST boundaries, frozen queries and shared limit display."""
from dataclasses import replace
from datetime import datetime
import json
from unittest.mock import patch
from zoneinfo import ZoneInfo

from test_api import ApiFixture
from usage_config import Settings, load_settings, save_settings, settings_data, settings_from_data
from usage_time import resolve_range
from usage_timezone import resolve_timezone


class TimezoneGates(ApiFixture):
    def test_default_auto_round_trip_and_manual_choice_survive_system_changes(self):
        automatic = replace(self.settings, timezone=Settings().timezone)
        self.assertEqual(automatic.timezone, 'auto')
        save_settings(automatic, self.config)
        with patch('tzlocal.reload_localzone', return_value=ZoneInfo('America/Los_Angeles')):
            self.assertEqual(load_settings(self.config).resolved_timezone, 'America/Los_Angeles')
            self.assertEqual(resolve_timezone('auto').source, 'system')
        with patch('tzlocal.reload_localzone', return_value=ZoneInfo('Asia/Tokyo')):
            self.assertEqual(load_settings(self.config).resolved_timezone, 'Asia/Tokyo')
            self.assertEqual(resolve_timezone('America/Los_Angeles').name, 'America/Los_Angeles')
            self.assertEqual(resolve_timezone('UTC').source, 'manual')
        self.assertEqual(load_settings(self.config).version, automatic.version)
        self.assertEqual(json.loads(self.config.read_text(encoding='utf-8'))['timezone'], 'auto')
        # Existing explicit UTC/LA configurations remain valid manual choices.
        self.assertEqual(settings_from_data(settings_data(self.settings)), self.settings)

    def test_detection_failure_has_labeled_utc_fallback_without_changing_saved_choice(self):
        automatic = replace(self.settings, timezone='auto')
        save_settings(automatic, self.config)
        with patch('tzlocal.reload_localzone', side_effect=LookupError('PRIVATE_OS_PATH')):
            self.assertEqual(resolve_timezone('auto').data(), {'name':'UTC','source':'fallback'})
            editable = self.jobs.editable()
            self.assertEqual(editable['timezone_info']['source'], 'fallback')
            self.assertNotIn('PRIVATE_OS_PATH', json.dumps(editable))
        self.assertEqual(load_settings(self.config), automatic)

    def test_la_local_day_boundaries_follow_both_dst_transitions(self):
        for last, start, hours in [
            ('2026-03-08T23:59:59-07:00', '2026-03-08T08:00:00+00:00', 23),
            ('2026-11-01T23:59:59-08:00', '2026-11-01T07:00:00+00:00', 25),
        ]:
            now = datetime.fromisoformat(last).timestamp()
            result = resolve_range('today', now, timezone='America/Los_Angeles')
            self.assertEqual(result.start, datetime.fromisoformat(start).timestamp())
            self.assertEqual(result.end-result.start, hours*3600-1)
        month = resolve_range('month', datetime.fromisoformat('2026-11-15T12:00:00-08:00').timestamp(),
                              timezone='America/Los_Angeles')
        self.assertEqual(month.start, datetime.fromisoformat('2026-11-01T07:00:00+00:00').timestamp())

    def test_auto_publication_freezes_zone_and_keeps_usage_facts_after_system_change(self):
        before = self.overview()
        saved = self.jobs.patch_settings({'expected_configuration_version':load_settings(self.config).version,
                                          'changes':{'timezone':'auto'}})
        self.assertTrue(saved['pending'])
        self.assertEqual(self.service.read('/limits', {})['data']['timezone_info'], {'name':'UTC','source':'manual'})
        self.assertTrue(self.jobs.run_one())
        with patch('tzlocal.reload_localzone', return_value=ZoneInfo('America/Los_Angeles')):
            first = self.overview()
            limits = self.service.read('/limits', {})
            self.assertEqual(first['range']['timezone'], 'America/Los_Angeles')
            self.assertEqual(limits['data']['timezone_info'], {'name':'America/Los_Angeles','source':'system'})
            self.assertEqual(first['data']['summary'], before['data']['summary'])
            self.assertEqual(first['usage_revision'], before['usage_revision'])
        with patch('tzlocal.reload_localzone', return_value=ZoneInfo('Asia/Tokyo')):
            retained = self.overview(self.frozen(first))
            derived = self.overview({'base_query_context_id':[first['query_context_id']], 'provider':['codex']})
            fresh = self.overview()
            self.assertEqual(retained['range'], first['range'])
            self.assertEqual(derived['range'], first['range'])
            self.assertEqual(fresh['range']['timezone'], 'Asia/Tokyo')
            self.assertEqual(fresh['data']['summary'], before['data']['summary'])
        # Limits need only the committed config, never an event-history scan.
        with patch.object(self.store, 'read_snapshot', side_effect=AssertionError('history read')):
            self.service.read('/limits', {})

    def test_manual_override_is_published_and_retained_after_restart(self):
        save_settings(replace(self.settings, timezone='auto'), self.config)
        self.store.reprice()
        saved = self.jobs.patch_settings({'expected_configuration_version':load_settings(self.config).version,
                                          'changes':{'timezone':'America/Los_Angeles'}})
        self.assertTrue(saved['pending'])
        self.jobs.run_one()
        with patch('tzlocal.reload_localzone', return_value=ZoneInfo('Asia/Tokyo')):
            self.assertEqual(self.store.display_settings().resolved_timezone, 'America/Los_Angeles')
            self.assertEqual(load_settings(self.config).resolved_timezone, 'America/Los_Angeles')
            self.assertEqual(self.overview()['range']['timezone'], 'America/Los_Angeles')
