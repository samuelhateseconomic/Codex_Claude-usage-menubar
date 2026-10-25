"""S06 persistence/recovery and cross-process entry-point acceptance."""
from dataclasses import replace
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import usage_config as config
import usage_identity as identity
import usage_reports as reports
import usage_service as service
import usage_tray as tray
from usage_valuation import DEFAULT_PLAN_FEES, Price, build_catalog

D = Decimal
SCRIPT = Path(tray.__file__).resolve()


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.path = self.base / "appdata" / "UsageTray" / "settings.json"
        self.env = dict(os.environ, LOCALAPPDATA=str(self.base / "appdata"),
                        CODEX_HOME=str(self.base / "codex"), CLAUDE_CONFIG_DIR=str(self.base / "claude"))

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0 if success else 2, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_first_run_defaults_are_one_source_and_have_no_incidental_writes(self):
        self.assertEqual(config.load_settings(self.path).plan_fees_usd, tuple(DEFAULT_PLAN_FEES.items()))
        result = self.cli("--show-settings")
        data = json.loads(result.stdout)
        self.assertEqual(data["plan_fees_usd"], {"Codex": "20.00", "Claude": "20.00"})
        self.assertEqual(data["report_format"], "text")
        self.assertEqual(data["log_roots"], {"Codex": None, "Claude": None})
        self.assertFalse(self.path.parent.exists())

    def test_round_trip_exact_fees_rates_roots_and_preference(self):
        settings = config.effective_settings(config.Settings(), codex_fee="20.000000000001", claude_fee="0", timezone="UTC",
            report_format="html", codex_roots=[self.base / "logs with spaces"], claude_roots=[],
            prices={"exact-model": Price("0.123456789012", "0.000000000001", 0, 0)})
        config.save_settings(settings, self.path)
        loaded = config.load_settings(self.path)
        self.assertEqual(loaded, settings)
        self.assertEqual(loaded.version, settings.version)
        self.assertEqual(loaded.roots()["Claude"], [])
        self.assertEqual(dict(loaded.rate_overrides)["exact-model"].write5m, D(0))
        self.assertIsNone(dict(loaded.rate_overrides)["exact-model"].write1h)
        self.assertEqual(list(self.path.parent.glob(".settings-*.tmp")), [])
        self.assertEqual(json.loads(self.path.read_text())["rate_overrides"]["exact-model"]["input"], "0.123456789012")

    def test_null_fee_is_unknown_zero_is_known_and_reaches_service(self):
        data = config.settings_data(config.Settings())
        data["plan_fees_usd"] = {"Codex": None, "Claude": "0"}
        settings = config.settings_from_data(data)
        config.save_settings(settings, self.path)
        result = service.query_usage("month", demo=True, timezone="UTC", plan_costs=dict(config.load_settings(self.path).plan_fees_usd))
        self.assertFalse(result.comparisons[0].available)
        self.assertTrue(result.comparisons[1].available)
        self.assertEqual(result.comparisons[1].fee_usd, D(0))
        self.assertFalse(result.combined_comparison.available)

    def test_schema_rejects_partial_future_unknown_duplicate_and_bool_version(self):
        good = config.settings_data(config.Settings())
        invalid = [{}, [], dict(good, unexpected="PRIVATE_SENTINEL"), dict(good, schema_version=True), dict(good, schema_version=2)]
        invalid.extend({k: v for k, v in good.items() if k != field} for field in good)
        for data in invalid:
            with self.subTest(data=data):
                self.write(data)
                original = self.path.read_bytes()
                with self.assertRaisesRegex(config.SettingsError, "No settings were replaced"):
                    config.load_settings(self.path)
                with self.assertRaises(config.SettingsError):
                    config.save_settings(config.Settings(), self.path)
                self.assertEqual(self.path.read_bytes(), original)
        self.path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaises(config.SettingsError):
            config.load_settings(self.path)

    def test_finite_bounds_scale_and_required_provider_fields(self):
        invalid = [True, "NaN", "Infinity", "-1", "1000000001", "0.0000000000001"]
        for value in invalid:
            data = config.settings_data(config.Settings())
            data["plan_fees_usd"]["Codex"] = value
            with self.subTest(fee=value), self.assertRaises(ValueError):
                config.settings_from_data(data)
            data = config.settings_data(config.Settings())
            data["rate_overrides"] = {"x": {"input": value, "output": 0, "cached": 0}}
            with self.subTest(rate=value), self.assertRaises(ValueError):
                config.settings_from_data(data)
        for value in ({"Codex": "20"}, {"Codex": "20", "Claude": "20", "Other": "0"}):
            data = config.settings_data(config.Settings()); data["plan_fees_usd"] = value
            with self.assertRaises(ValueError):
                config.settings_from_data(data)

    def test_roots_replace_defaults_and_empty_disables_without_existence_claim(self):
        settings = config.effective_settings(config.Settings(), codex_roots=[self.base / "missing", self.base / "missing"], claude_roots=[])
        self.assertEqual(settings.roots(), {"Codex": [self.base / "missing"], "Claude": []})
        with patch.dict(os.environ, self.env):
            roots = config.Settings().roots()
            self.assertEqual(roots["Codex"], [self.base / "codex" / "sessions", self.base / "codex" / "archived_sessions"])
            self.assertEqual(roots["Claude"], [self.base / "claude" / "projects"])
        for value in (["relative"], "absolute", ["~"], ["C:\u001b[2J"], [True]):
            data = config.settings_data(config.Settings()); data["log_roots"]["Codex"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.settings_from_data(data)
        result = service.query_usage(roots=settings.roots())
        self.assertEqual([s.state for s in result.sources], ["failed", "failed"])
        self.assertEqual(result.total.value.state, "empty")

    def test_timezone_catalog_preference_and_model_metadata_validation(self):
        good = config.settings_data(config.Settings())
        for field, value in (("timezone", "PRIVATE_SENTINEL"), ("timezone", None), ("rate_catalog", "remote"),
                             ("report_format", "website"), ("rate_overrides", {"x": {"input": 0}}),
                             ("rate_overrides", {"bad\u001b[2J": {"input":0,"output":0,"cached":0}})):
            with self.subTest(field=field), self.assertRaises((ValueError, TypeError, KeyError)):
                config.settings_from_data(dict(good, **{field: value}))
        self.assertEqual(config.effective_settings(config.Settings(), timezone="UTC").timezone, "UTC")

    def test_failed_atomic_replace_preserves_previous_config_and_cleans_temporary(self):
        config.save_settings(config.Settings(), self.path)
        original = self.path.read_bytes()
        updated = config.effective_settings(config.Settings(), codex_fee="35")
        with patch.object(config.os, "replace", side_effect=PermissionError("PRIVATE_SENTINEL")):
            with self.assertRaisesRegex(config.SettingsError, "previous settings file was preserved") as error:
                config.save_settings(updated, self.path)
        self.assertNotIn("PRIVATE_SENTINEL", str(error.exception))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(config.load_settings(self.path), config.Settings())
        self.assertEqual(list(self.path.parent.glob(".settings-*.tmp")), [])

    def test_failed_flush_preserves_previous_config(self):
        config.save_settings(config.Settings(), self.path)
        original = self.path.read_bytes()
        with patch.object(config.os, "fsync", side_effect=OSError("PRIVATE_SENTINEL")):
            with self.assertRaises(config.SettingsError):
                config.save_settings(config.effective_settings(config.Settings(), codex_fee="45"), self.path)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.path.parent.glob(".settings-*.tmp")), [])

    def test_unreadable_existing_file_fails_closed_without_exposing_os_error(self):
        config.save_settings(config.Settings(), self.path)
        original = self.path.read_bytes()
        with patch.object(config, "read_json", side_effect=PermissionError("PRIVATE_SENTINEL")):
            for operation in (lambda: config.load_settings(self.path), lambda: config.save_settings(config.Settings(), self.path)):
                with self.assertRaises(config.SettingsError) as error:
                    operation()
                self.assertNotIn("PRIVATE_SENTINEL", str(error.exception))
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_in_memory_candidate_fails_before_destination_creation(self):
        for settings in (replace(config.Settings(), timezone="not-a-zone"), replace(config.Settings(), plan_fees_usd=(("Codex",D(-1)),)),
                         replace(config.Settings(), rate_overrides=(("tiered", Price(1,2,0,threshold=10,high=(2,4,0))),))):
            with self.assertRaises(config.SettingsError):
                config.save_settings(settings, self.path)
            self.assertFalse(self.path.parent.exists())

    def test_malformed_encoding_nonfinite_json_and_size_fail_safely(self):
        self.path.parent.mkdir(parents=True)
        for data in (b"{unfinished PRIVATE_SENTINEL", b"\xff", b'{"amount":NaN}', b" " * (config.MAX_FILE_BYTES + 1)):
            self.path.write_bytes(data)
            result = self.cli("--show-settings", success=False)
            self.assertIn("--config", result.stderr)
            self.assertNotIn("PRIVATE_SENTINEL", result.stderr)
            self.assertEqual(self.path.read_bytes(), data)

    def test_save_and_restart_persist_then_cli_overrides_do_not_rewrite(self):
        self.cli("--save-settings", "--codex-plan-usd", "33.000000000001", "--timezone", "UTC", "--report-format", "html",
                 "--codex-root", str(self.base / "approved"))
        original = self.path.read_bytes()
        data = json.loads(self.cli("--show-settings").stdout)
        self.assertEqual(data["plan_fees_usd"]["Codex"], "33.000000000001")
        self.assertEqual(data["report_format"], "html")
        self.assertEqual(data["timezone"], "UTC")
        overridden = json.loads(self.cli("--show-settings", "--codex-plan-usd", "0", "--timezone", "America/Los_Angeles", "--report-format", "text").stdout)
        self.assertEqual(overridden["plan_fees_usd"]["Codex"], "0")
        self.assertEqual(overridden["plan_fees_usd"]["Claude"], "20.00")
        self.assertEqual(self.path.read_bytes(), original)
        output = self.base / "persisted.html"
        self.cli("--report", "month", "--demo", "--output", str(output))
        html = output.read_text(encoding="utf-8")
        self.assertIn("<html", html)
        self.assertIn("$33.00", html)
        self.assertIn(config.load_settings(self.path).version, html)
        text = self.cli("--report", "month", "--demo", "--report-format", "text").stdout
        self.assertIn("Monthly plan $33.00", text)
        self.assertIn("108,000", text)
        self.assertEqual(self.path.read_bytes(), original)

    def test_legacy_price_migration_and_explicit_replacement_are_non_destructive(self):
        self.path.parent.mkdir(parents=True)
        legacy = self.path.with_name("prices.json")
        legacy.write_text('{"gpt-5.4":{"input":0,"output":0,"cached":0}}', encoding="utf-8")
        original = legacy.read_bytes()
        self.assertIn("gpt-5.4", json.loads(self.cli("--show-settings").stdout)["rate_overrides"])
        self.assertFalse(self.path.exists())
        self.cli("--save-settings")
        self.assertEqual(legacy.read_bytes(), original)
        legacy.write_text("broken PRIVATE_SENTINEL", encoding="utf-8")
        self.assertIn("gpt-5.4", json.loads(self.cli("--show-settings").stdout)["rate_overrides"])
        override = self.base / "override.json"
        override.write_text('{"another":{"input":1,"output":2,"cached":0}}', encoding="utf-8")
        data = json.loads(self.cli("--show-settings", "--prices", str(override)).stdout)
        self.assertEqual(list(data["rate_overrides"]), ["another"])
        self.assertEqual(list(dict(config.load_settings(self.path).rate_overrides)), ["gpt-5.4"])
        # Explicit alternate config is isolated from legacy/default locations.
        alternate = self.base / "isolated.json"
        self.assertEqual(json.loads(self.cli("--config", str(alternate), "--show-settings").stdout)["rate_overrides"], {})

    def test_corrupt_existing_settings_cannot_be_overridden_or_saved_and_version_still_works(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("PRIVATE_SENTINEL {partial", encoding="utf-8")
        original = self.path.read_bytes()
        self.cli("--save-settings", "--codex-plan-usd", "20", success=False)
        self.cli("--report", "month", "--demo", success=False)
        self.assertEqual(self.path.read_bytes(), original)
        info = json.loads(self.cli("--version").stdout)
        self.assertEqual(info["app_version"], identity.APP_VERSION)
        self.assertTrue(info["build_id"].startswith("source-sha256:"))
        self.assertEqual(info["pricing_version"], build_catalog().version)
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(info))

    def test_diagnostics_use_effective_catalog_without_scanning_or_polling(self):
        prices = self.base / "prices.json"
        prices.write_text('{"custom":{"input":1,"output":2,"cached":0}}', encoding="utf-8")
        with patch.dict(os.environ, self.env), patch.object(sys, "argv", ["usage_tray", "--diagnostics", "--prices", str(prices)]), \
             patch.object(tray, "query_usage", side_effect=AssertionError), patch.object(tray, "run_tray", side_effect=AssertionError), \
             patch.object(tray, "PROVIDERS", {}), patch.object(sys, "stdout", new_callable=io.StringIO) as out:
            self.assertEqual(tray.main(), 0)
        info = json.loads(out.getvalue())
        self.assertEqual(info["pricing_version"], build_catalog({"custom":Price(1,2,0)}).version)
        self.assertEqual(info["settings_schema_version"], 1)
        self.assertNotIn(str(self.base), out.getvalue())
        for field in ("app_version", "build_id", "parser_version", "reconciliation_version", "query_version", "valuation_policy", "settings_version"):
            self.assertTrue(info[field])

    def test_diagnostic_persistence_status_and_explicit_json_destination(self):
        output = self.base / "diagnostic" / "version.json"
        self.cli("--version", "--output", str(output))
        self.assertEqual(json.loads(output.read_text())["app_version"], identity.APP_VERSION)
        initial = json.loads(self.cli("--diagnostics").stdout)
        self.assertEqual(initial["settings_file_state"], "absent")
        self.assertFalse(initial["effective_settings_saved"])
        self.cli("--save-settings")
        saved = json.loads(self.cli("--diagnostics").stdout)
        self.assertTrue(saved["effective_settings_saved"])
        changed = json.loads(self.cli("--diagnostics", "--codex-plan-usd", "42").stdout)
        self.assertEqual(changed["settings_file_state"], "present")
        self.assertFalse(changed["effective_settings_saved"])

    def test_tray_legacy_entrypoint_receives_persisted_settings_and_source_roots(self):
        settings = config.effective_settings(config.Settings(), timezone="UTC", report_format="text", codex_fee="41", codex_roots=[self.base / "approved"])
        config.save_settings(settings, self.path)
        with patch.dict(os.environ, self.env), patch.object(sys, "argv", ["usage_tray", "--demo"]), patch.object(tray, "run_tray") as run:
            self.assertEqual(tray.main(), 0)
        self.assertEqual(run.call_args.args[4], {"Codex":D(41),"Claude":D(20)})
        self.assertEqual(run.call_args.args[5], "UTC")
        self.assertEqual(run.call_args.kwargs["roots"]["Codex"], [self.base / "approved"])
        self.assertEqual(run.call_args.kwargs["settings_version"], settings.version)

    def test_settings_import_is_headless_and_network_free(self):
        code = "import sys,socket;socket.socket=lambda *a,**k:(_ for _ in ()).throw(AssertionError());import usage_config;assert not any(m in sys.modules for m in ('usage_core','usage_tray','usage_reports','pystray','PIL'));print(usage_config.Settings().timezone)"
        result = subprocess.run([sys.executable,"-c",code],cwd=SCRIPT.parent, env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(), "auto")

    def test_structured_result_and_both_reports_expose_versions_without_changing_facts(self):
        result = service.query_usage(demo=True)
        self.assertEqual(result.app_version, identity.APP_VERSION)
        self.assertEqual(result.build_id, identity.build_identity())
        self.assertIsNone(result.settings_version)
        for rendered in (reports.render_text_report(result), reports.render_report(result)):
            self.assertIn(result.build_id, rendered)
            self.assertIn(result.parser_version, rendered)
            self.assertIn(result.reconciliation_version, rendered)
        self.assertEqual(result.total.tokens.total,108000)


if __name__ == "__main__":
    unittest.main()
