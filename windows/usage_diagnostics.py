"""Allowlisted local operation exports; no payload/exception/metadata serialization."""
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import tempfile
import uuid

from usage_identity import APP_VERSION, BUILD_ID

SCHEMA_VERSION = 1
OPERATIONS = {"settings", "report", "provider_check"}
PHASES = {"settings", "ownership", "query", "render", "save", "open", "poll", "complete"}
CATEGORIES = {"success", "source_incomplete", "settings_invalid", "already_running", "permission_denied",
              "disk_full", "io_error", "invalid_data", "open_failed", "unexpected_local", "provider_error",
              "login_required", "network_error", "cooldown", "unsupported_response", "cancelled", "blocked"}
ACTIONS = {
    "success": "No recovery action required.",
    "source_incomplete": "Check configured log roots and local source metadata, then retry the report.",
    "settings_invalid": "Preserve the settings file; correct its values or select a separate valid file with --config.",
    "already_running": "Use the running tray, or quit it before starting another polling instance.",
    "permission_denied": "Check access to the selected destination or application-data folder.",
    "disk_full": "Free disk space and retry the explicit export.",
    "io_error": "Check local file access and retry.",
    "invalid_data": "Check configuration and supported local calculation bounds.",
    "open_failed": "Open the saved report directly or check the configured viewer.",
    "login_required": "Sign in with the provider CLI, then retry after its cooldown.",
    "network_error": "Check the network and retry after the provider cooldown.",
    "cooldown": "Wait for the provider retry deadline; repeated refreshes do not bypass it.",
    "unsupported_response": "Check the installed CLI and application versions.",
    "cancelled": "Retry the operation if it is still needed.",
    "blocked": "Check the active account's usage page and next reset time.",
}


def next_action(category):
    return ACTIONS.get(category, "Check the application and CLI installation; use the operation/build IDs when reporting the failure.")


COUNT_KEYS = {"records", "conversations", "projects", "roots_read", "files_discovered", "files_read",
              "ingestion_issues", "accounting_issues", "unpriced_records", "assumed_records"}


def _choice(value, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ValueError("Unsupported diagnostic category.")
    return value


class Operation:
    def __init__(self, operation):
        self.operation = _choice(operation, OPERATIONS)
        self.operation_id = uuid.uuid4().hex
        self.started_at = datetime.now(timezone.utc).isoformat()

    def finish(self, status, phase, category, *, counts=None, providers=(), scope="local"):
        counts = {} if counts is None else counts
        if not isinstance(counts, dict) or set(counts) - COUNT_KEYS or any(type(v) is not int or v < 0 for v in counts.values()):
            raise ValueError("Unsupported diagnostic counts.")
        results = []
        for provider, provider_category in providers:
            results.append({"provider": _choice(provider, {"Codex", "Claude"}),
                            "category": _choice(provider_category, CATEGORIES)})
        # Deliberately enumerate fields. Never asdict(), repr(), exception text,
        # arbitrary keyword data, raw paths, record labels or source issue messages.
        return {"diagnostic_schema_version": SCHEMA_VERSION, "operation_id": self.operation_id,
                "operation": self.operation, "scope": _choice(scope, {"local", "demo", "configuration"}),
                "started_at": self.started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "app_version": APP_VERSION, "build_id": BUILD_ID,
                "status": _choice(status, {"success", "partial", "failed"}),
                "phase": _choice(phase, PHASES), "category": _choice(category, CATEGORIES),
                "next_action": next_action(category),
                "counts": dict(counts), "providers": results}


def report_counts(result):
    return {"records": result.total.record_count, "conversations": result.total.conversation_count,
            "projects": result.total.project_count, "roots_read": sum(s.roots_read for s in result.sources),
            "files_discovered": sum(s.files_discovered for s in result.sources),
            "files_read": sum(s.files_read for s in result.sources),
            "ingestion_issues": sum(i.count for s in result.sources for i in s.issues),
            "accounting_issues": sum(len(s.accounting_issues) for s in result.sources),
            "unpriced_records": result.total.value.unpriced_records,
            "assumed_records": result.total.value.assumed_records}


def write_diagnostic(path, data):
    """Atomic explicit export; no automatic logs, directory scan or retention."""
    fields = {"diagnostic_schema_version", "operation_id", "operation", "scope", "started_at", "finished_at",
              "app_version", "build_id", "status", "phase", "category", "next_action", "counts", "providers"}
    if (not isinstance(data, dict) or set(data) != fields or (type(data["diagnostic_schema_version"]) is not int or data["diagnostic_schema_version"] != SCHEMA_VERSION)
            or data["app_version"] != APP_VERSION or data["build_id"] != BUILD_ID
            or not isinstance(data["operation_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", data["operation_id"])):
        raise ValueError("Unsupported diagnostic export fields.")
    for key in ("started_at", "finished_at"):
        value = data[key]
        if (not isinstance(value, str) or len(value) > 40 or not value.endswith("+00:00")
                or datetime.fromisoformat(value).utcoffset().total_seconds() != 0):
            raise ValueError("Diagnostic timestamps require UTC.")
    if not isinstance(data["category"], str) or data["next_action"] != next_action(data["category"]):
        raise ValueError("Unsupported diagnostic recovery guidance.")
    if not isinstance(data["counts"], dict):
        raise ValueError("Diagnostic counts require an object.")
    if not isinstance(data["providers"], list) or any(not isinstance(p, dict) or set(p) != {"provider", "category"} for p in data["providers"]):
        raise ValueError("Unsupported diagnostic provider fields.")
    # Revalidate enum/count fields at the serialization boundary, even if the
    # caller mutated an Operation projection. Extra nested payloads fail closed.
    Operation(data["operation"]).finish(data["status"], data["phase"], data["category"],
        counts=data["counts"], providers=((p["provider"], p["category"]) for p in data["providers"]), scope=data["scope"])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".usage-diagnostic-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(data, indent=2, ensure_ascii=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
