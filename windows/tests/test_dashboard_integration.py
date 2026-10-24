"""Compatibility regressions for the combined demo dashboard and refined core."""
from dataclasses import replace
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from usage_hub import HubService
from usage_records import Record, Tokens
from usage_observations import CanonicalEvent, SourceRef
from usage_value import estimate_exact, summarize_records
from usage_valuation import Price
import usage_tray as tray

class IntegrationTests(unittest.TestCase):
    def record(self, **changes):
        return replace(Record("Codex", 1, "fixture", "project", "custom", Tokens(1)), **changes)

    def test_missing_unused_write_rates_and_used_unconfigured_rates(self):
        price = {"custom": Price(1, 2, 0)}
        record = self.record()
        self.assertEqual(estimate_exact(record, price), Decimal("0.000001"))
        self.assertIsNone(estimate_exact(replace(record, tokens=Tokens(1, write5m=1)), price))
        zero = {"custom": Price(0, 0, 0, 0, 0)}
        self.assertEqual(estimate_exact(replace(record, tokens=Tokens(write5m=1)), zero), Decimal(0))

    def test_event_rounding_precedes_shared_summary_and_ignores_caller_context(self):
        price = {"custom": Price("0.0000005", 0, 0)}
        record = self.record(reasoning_tokens=0)
        with localcontext() as context:
            context.prec = 2
            result = summarize_records([record, record], price)
        self.assertEqual(result.amount, Decimal(0))
        self.assertEqual(result.reasoning_tokens, 0)
        self.assertEqual(result.reasoning_records, 2)
        self.assertEqual(result.tokens.total, 2)

    def test_canonical_request_context_survives_the_compatibility_adapter(self):
        record = self.record(tokens=Tokens(10))
        event = CanonicalEvent("conversation", "epoch", "event", "codex_last_usage", record,
                               (SourceRef("fixture", 1),), request_context_tokens=1,
                               request_context_source="synthetic request context")
        prices = {"custom": Price(1, 2, 0, threshold=5, high=(2, 4, 0))}
        self.assertEqual(estimate_exact(record, prices), Decimal("0.00002"))
        self.assertEqual(estimate_exact(event, prices), Decimal("0.00001"))
        self.assertEqual(summarize_records([event], prices).amount, Decimal("0.00001"))

    def test_saved_null_fee_is_unavailable_while_zero_fee_is_known(self):
        service = HubService(demo=True, fees={"Codex": None, "Claude": Decimal(0)})
        self.assertEqual(service.refresh()["state"], "complete")
        result = service.query({})
        self.assertIsNone(result["settings"]["fees_usd"]["Codex"])
        comparisons = {c["provider"]: c for c in result["comparisons"]}
        self.assertIsNone(comparisons["Codex"]["difference_usd"])
        self.assertEqual(Decimal(comparisons["Claude"]["difference_usd"]), Decimal("20.766"))

    def test_dashboard_rejects_export_and_mutating_or_unrelated_modes_before_loading_settings(self):
        for flags in (("--diagnostics",), ("--version",), ("--show-settings",),
                      ("--save-settings",), ("--include-metadata",),
                      ("--diagnostic-output", "unused.json"), ("--report-format", "html"),
                      ("--codex-root", "C:/synthetic")):
            with self.subTest(flags=flags), patch.object(sys, "argv", ["usage_tray", "--dashboard", "--demo", *flags]), \
                 patch.object(tray, "load_settings", side_effect=AssertionError("must reject before IO")), \
                 patch("sys.stderr"):
                with self.assertRaises(SystemExit) as caught:
                    tray.main()
                self.assertEqual(caught.exception.code, 2)

    def test_simulated_packaged_dashboard_tray_owns_and_closes_its_server(self):
        import dashboard_main
        opened = threading.Event()
        servers = []
        original = dashboard_main.start_preview
        def start(**kwargs):
            result = original(**kwargs)
            servers.append(result)
            return result
        class Item:
            def __init__(self, text, action=None, **kwargs): self.text, self.action = text, action
        class Menu:
            SEPARATOR = object()
            def __init__(self, items): self.items = items
        class Icon:
            def __init__(self, *args): self.menu = args[3]
            def update_menu(self): pass
            def stop(self): pass
            def run(self, setup):
                setup(self)
                if not opened.wait(5): raise AssertionError("dashboard opener did not complete")
                next(item for item in self.menu.items() if isinstance(item, Item) and item.text == "Quit").action(self, None)
        fake = types.SimpleNamespace(Icon=Icon, Menu=Menu, MenuItem=Item)
        with patch.dict(sys.modules, {"pystray": fake}), \
             patch.object(dashboard_main, "start_preview", side_effect=start), \
             patch.object(tray.webbrowser, "open", side_effect=lambda url: opened.set()):
            tray.run_tray(demo=True, dashboard=True, dashboard_port=0, timezone="UTC")
        self.assertEqual(len(servers), 1)
        self.assertFalse(servers[0][1].is_alive())
        self.assertEqual(servers[0][0].socket.fileno(), -1)
        self.assertFalse(any(t.name.startswith("usage-dashboard") and t.is_alive() for t in threading.enumerate()))

    def test_preview_uses_effective_settings_without_polling_or_owning_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/"settings.json"
            with patch.object(sys, "argv", ["usage_tray", "--dashboard", "--demo", "--no-browser",
                    "--config", str(config), "--timezone", "UTC", "--codex-plan-usd", "30.000000000001"]), \
                 patch("dashboard_main.run_preview", return_value=0) as launch, \
                 patch.object(tray, "RuntimeOwner", side_effect=AssertionError("no polling owner")), \
                 patch.object(tray, "fetch_codex", side_effect=AssertionError("no polling")):
                self.assertEqual(tray.main(), 0)
            self.assertEqual(launch.call_args.kwargs["timezone"], "UTC")
            self.assertEqual(launch.call_args.kwargs["fees"]["Codex"], Decimal("30.000000000001"))
            self.assertFalse(config.exists())

if __name__ == "__main__":
    unittest.main()
