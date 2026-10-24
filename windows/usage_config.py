"""Validated, content-free per-user settings. No GUI, providers or credential IO."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from usage_time import DEFAULT_TIMEZONE
from usage_valuation import DEFAULT_PLAN_FEES, Price, bounded_decimal

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 1024 * 1024
PROVIDERS = tuple(DEFAULT_PLAN_FEES)
FIELDS = {"schema_version", "plan_fees_usd", "log_roots", "timezone", "rate_catalog", "rate_overrides", "report_format"}
RECOVERY = ("Cannot load settings. Keep the original file and correct its schema/values, "
            "or select a separate valid file with --config. See windows/README.md. "
            "No settings were replaced.")


class SettingsError(ValueError):
    pass


def application_directory():
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "UsageTray"


def default_roots():
    codex = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    return {"Codex": [codex / "sessions", codex / "archived_sessions"], "Claude": [claude / "projects"]}


def settings_path():
    return application_directory() / "settings.json"


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field.")
        result[key] = value
    return result


def _constant(_):
    raise ValueError("Non-finite JSON number.")


def read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("Configuration exceeds one MiB.")
    return json.loads(data.decode("utf-8-sig"), parse_float=Decimal,
                      parse_constant=_constant, object_pairs_hook=_object)


def _text(value, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or 127 <= ord(c) < 160 for c in value):
        raise ValueError("Invalid metadata string.")
    return value


def prices_from_data(data):
    if not isinstance(data, dict) or len(data) > 1000:
        raise ValueError("Prices require an object of at most 1000 exact model names.")
    prices = {}
    for name, values in data.items():
        _text(name)
        if not isinstance(values, dict) or not {"input", "output", "cached"} <= values.keys():
            raise ValueError("Each model needs input, output and cached rates.")
        if values.keys() - {"input", "output", "cached", "write5m", "write1h"}:
            raise ValueError("Unsupported price fields.")
        prices[name] = Price(**{key: bounded_decimal(value) for key, value in values.items()})
    return prices


def load_prices(path):
    return {} if path is None else prices_from_data(read_json(path))


@dataclass(frozen=True)
class Settings:
    plan_fees_usd: tuple = tuple(DEFAULT_PLAN_FEES.items())
    log_roots: tuple = tuple((p, None) for p in PROVIDERS)
    timezone: str = DEFAULT_TIMEZONE
    rate_catalog: str = "bundled"
    rate_overrides: tuple = ()
    report_format: str = "text"

    @property
    def version(self):
        encoded = json.dumps(settings_data(self), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        return "settings-v1:" + hashlib.sha256(encoded).hexdigest()

    def roots(self):
        # Resolve environment defaults at the application boundary, never store
        # credentials or assume the configured folder proves account coverage.
        defaults = default_roots()
        return {p: defaults[p] if roots is None else [Path(root) for root in roots] for p, roots in self.log_roots}


def settings_data(settings):
    if any(not isinstance(price, Price) or price.threshold is not None for _, price in settings.rate_overrides):
        raise ValueError("Settings overrides support flat exact-model rates only.")
    rates = {name: {key: format(getattr(price, key), "f") for key in ("input", "output", "cached", "write5m", "write1h")
                    if getattr(price, key) is not None} for name, price in settings.rate_overrides}
    return {"schema_version": SCHEMA_VERSION,
            "plan_fees_usd": {p: format(fee, "f") if fee is not None else None for p, fee in settings.plan_fees_usd},
            "log_roots": {p: list(roots) if roots is not None else None for p, roots in settings.log_roots},
            "timezone": settings.timezone, "rate_catalog": settings.rate_catalog,
            "rate_overrides": rates, "report_format": settings.report_format}


def settings_from_data(data):
    if not isinstance(data, dict) or set(data) != FIELDS or type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported or incomplete settings schema.")
    fees, roots = data["plan_fees_usd"], data["log_roots"]
    if not isinstance(fees, dict) or set(fees) != set(PROVIDERS) or not isinstance(roots, dict) or set(roots) != set(PROVIDERS):
        raise ValueError("Fees and roots must explicitly cover both providers.")
    fees = tuple((p, None if fees[p] is None else bounded_decimal(fees[p])) for p in PROVIDERS)
    checked_roots = []
    for provider in PROVIDERS:
        values = roots[provider]
        if values is not None:
            if not isinstance(values, list) or len(values) > 64:
                raise ValueError("Roots must be null or an explicit list.")
            for value in values:
                _text(value, 32767)
                if not Path(value).is_absolute():
                    raise ValueError("Log roots must be absolute paths.")
            values = tuple(dict.fromkeys(values))
        checked_roots.append((provider, values))
    _text(data["timezone"])
    ZoneInfo(data["timezone"])
    if data["rate_catalog"] != "bundled" or data["report_format"] not in ("text", "html"):
        raise ValueError("Unsupported catalog or report preference.")
    prices = prices_from_data(data["rate_overrides"])
    return Settings(fees, tuple(checked_roots), data["timezone"], data["rate_catalog"], tuple(sorted(prices.items())), data["report_format"])


def load_settings(path=None):
    path = settings_path() if path is None else Path(path)
    try:
        data = read_json(path)
    except FileNotFoundError:
        return Settings()
    except (OSError, ValueError, RecursionError):
        raise SettingsError(RECOVERY) from None
    try:
        return settings_from_data(data)
    except (ValueError, TypeError, ZoneInfoNotFoundError, RecursionError):
        raise SettingsError(RECOVERY) from None


def effective_settings(settings, *, codex_fee=None, claude_fee=None, timezone=None,
                       report_format=None, codex_roots=None, claude_roots=None, prices=None):
    data = settings_data(settings)
    for provider, value in (("Codex", codex_fee), ("Claude", claude_fee)):
        if value is not None:
            try:
                data["plan_fees_usd"][provider] = format(bounded_decimal(value), "f")
            except ValueError:
                raise SettingsError("Monthly plan prices must be finite, nonnegative USD amounts up to 1000000000 with at most 12 decimal places.") from None
    if timezone is not None:
        try:
            _text(timezone)
            ZoneInfo(timezone)
        except (ValueError, TypeError, ZoneInfoNotFoundError):
            raise SettingsError("Unknown report timezone; use an available IANA name such as America/Los_Angeles or UTC.") from None
        data["timezone"] = timezone
    if report_format is not None:
        data["report_format"] = report_format
    for provider, values in (("Codex", codex_roots), ("Claude", claude_roots)):
        if values is not None:
            data["log_roots"][provider] = [str(p) for p in values]
    if prices is not None:
        data["rate_overrides"] = settings_data(Settings(rate_overrides=tuple(prices.items())))["rate_overrides"]
    try:
        return settings_from_data(data)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        raise SettingsError("Invalid settings override. Use an available IANA timezone, absolute log roots and supported values. See windows/README.md.") from None


def save_settings(settings, path=None):
    """Validate before IO, flush a sibling temporary file, atomically replace.

    A malformed existing file is never overwritten. Concurrent settings writers
    are not supported; runtime ownership is a separate S07 gate.
    """
    path = settings_path() if path is None else Path(path)
    temporary = None
    try:
        validated = settings_from_data(settings_data(settings))
        encoded = (json.dumps(settings_data(validated), indent=2, ensure_ascii=True) + "\n").encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise ValueError("Configuration exceeds one MiB.")
        load_settings(path)  # Fail closed if a prior file needs manual recovery.
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".settings-", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    except SettingsError:
        raise
    except (OSError, ValueError, TypeError, ZoneInfoNotFoundError):
        raise SettingsError("Cannot save settings. Check configuration and folder permissions; the previous settings file was preserved.") from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
