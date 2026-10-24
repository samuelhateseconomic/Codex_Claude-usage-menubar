"""Offline usage queries and immutable summaries, with no GUI/provider dependency.

This module owns selection, ordering, group membership and summary arithmetic.
Renderers format UsageResult; they never infer accounting from display labels.
Database publication and API pagination belong to their adapters. Direct scans
do not imply retained history. Indexed queries may supply committed valuations
and known-project identities without creating another accounting policy.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
import hashlib
import json
import math
import time
from zoneinfo import ZoneInfo

from usage_config import default_roots
from usage_identity import APP_VERSION, BUILD_ID
from usage_ingestion import ScanIssue, scan_observations
from usage_observations import CanonicalEvent, PARSER_VERSION
from usage_reconciliation import AccountingIssue, RECONCILIATION_VERSION, reconcile_observations
from usage_records import Record, Tokens
from usage_time import DEFAULT_TIMEZONE, RangeContext, local_datetime, resolve_range
from usage_valuation import (DEFAULT_PLAN_FEES, POLICY_VERSION, ComparisonScope, EventValuation,
                             PlanComparison, RateCatalog, ValueSummary, aggregate_values,
                             build_catalog, compare_plans, value_event)

QUERY_VERSION = "usage-query-v1"
DIMENSIONS = ("provider", "model_effort", "effort", "model", "project", "conversation", "day")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class UsageFilters:
    projects: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    efforts: tuple[str, ...] = ()
    conversations: tuple[tuple[str, str], ...] = ()  # Full provider/session identities.
    conversation_ids: tuple[str, ...] = ()  # Opaque IDs returned by this service.
    search: str = ""
    selected_day: str | None = None
    project_ids: tuple[str, ...] = ()  # Dataset-scoped normalized identities from the index.

    def __post_init__(self):
        for name in ("projects", "models", "efforts", "conversation_ids", "project_ids"):
            values = getattr(self, name)
            if isinstance(values, str) or any(not isinstance(v, str) for v in values):
                raise ValueError("Metadata filters require strings.")
            object.__setattr__(self, name, tuple(sorted(set(values))))
        pairs = tuple(tuple(pair) for pair in self.conversations)
        if any(len(pair) != 2 or pair[0] not in DEFAULT_PLAN_FEES or not isinstance(pair[1], str) for pair in pairs):
            raise ValueError("Conversation filters require provider and full session identity.")
        object.__setattr__(self, "conversations", tuple(sorted(set(pairs))))
        if not isinstance(self.search, str) or len(self.search.strip()) > 200:
            raise ValueError("Metadata search is limited to 200 characters.")
        object.__setattr__(self, "search", self.search.strip().casefold())
        if self.selected_day is not None:
            if not isinstance(self.selected_day, str) or date.fromisoformat(self.selected_day).isoformat() != self.selected_day:
                raise ValueError("Selected day must use YYYY-MM-DD.")

    @property
    def active(self):
        return bool(self.projects or self.project_ids or self.models or self.efforts or self.conversations or self.conversation_ids or self.search or self.selected_day)

    def matches(self, record, timezone, conversation_id, project_id=None):
        return (not self.projects or record.project in self.projects) and (
            not self.project_ids or project_id in self.project_ids) and (
            not self.models or record.model in self.models) and (
            not self.efforts or record.effort in self.efforts) and (
            not self.conversations or (record.provider, record.session) in self.conversations) and (
            not self.conversation_ids or conversation_id in self.conversation_ids) and (
            not self.search or any(self.search in text.casefold() for text in (record.session, record.project, record.model))) and (
            self.selected_day is None or local_datetime(record.timestamp, timezone).date().isoformat() == self.selected_day)


@dataclass(frozen=True)
class QueryContext:
    ranges: tuple[tuple[str, RangeContext], ...]
    captured_at: float
    period: str = "session"
    timezone: str = DEFAULT_TIMEZONE
    filters: UsageFilters = field(default_factory=UsageFilters)
    demo: bool = False
    filtered: bool = False  # Legacy caller can declare additional filtering.

    def __post_init__(self):
        object.__setattr__(self, "ranges", tuple((p, r) for p, r in self.ranges))
        providers = self.providers
        if not providers or len(set(providers)) != len(providers) or any(p not in DEFAULT_PLAN_FEES for p in providers):
            raise ValueError("Select distinct supported providers.")
        if isinstance(self.captured_at, bool) or not isinstance(self.captured_at, (int, float)) or not math.isfinite(self.captured_at):
            raise ValueError("Captured time must be a finite UTC timestamp.")
        if self.period not in ("session", "today", "week", "month"):
            raise ValueError("Unsupported query period.")
        if not isinstance(self.filters, UsageFilters) or not isinstance(self.demo, bool) or not isinstance(self.filtered, bool):
            raise ValueError("Queries require validated filters and explicit boolean scope flags.")
        ZoneInfo(self.timezone)
        for _, r in self.ranges:
            if (not isinstance(r, RangeContext) or not math.isfinite(r.start) or not math.isfinite(r.end)
                    or r.start > r.end or r.end != self.captured_at or r.timezone != self.timezone
                    or r.boundary_policy != "utc-half-open-v1"):
                raise ValueError("Ranges must share the captured end, timezone and half-open boundary policy.")

    @property
    def providers(self):
        return tuple(p for p, _ in self.ranges)

    @property
    def scope(self):
        return "demo" if self.demo else "local_unmatched_accounts"

    @property
    def is_filtered(self):
        return self.filtered or self.filters.active


@dataclass(frozen=True)
class SourceQuality:
    provider: str
    state: str
    issues: tuple[ScanIssue, ...] = ()
    accounting_issues: tuple[AccountingIssue, ...] = ()
    roots_read: int = 0
    files_discovered: int = 0
    files_read: int = 0

    @property
    def issue_counts(self):
        counts = defaultdict(int)
        for issue in self.issues:
            counts[issue.code] += issue.count
        return dict(sorted(counts.items()))  # Fresh compatibility projection, no mutable stored state.


@dataclass(frozen=True)
class ReasoningSummary:
    known_tokens: int | None
    known_records: int
    unknown_records: int


@dataclass(frozen=True)
class UsageSummary:
    value: ValueSummary
    reasoning: ReasoningSummary
    record_count: int
    conversation_count: int
    project_count: int  # Same exact project string is shared across providers.

    @property
    def tokens(self):
        return self.value.tokens


@dataclass(frozen=True)
class UsageDetail:
    detail_id: str
    conversation_id: str
    event: CanonicalEvent | None
    valuation: EventValuation
    summary: UsageSummary

    @property
    def record(self):
        return self.valuation.record


@dataclass(frozen=True)
class UsageGroup:
    group_id: str
    key: tuple[str, ...]
    summary: UsageSummary
    detail_ids: tuple[str, ...]
    last_activity: float


@dataclass(frozen=True)
class UsageResult:
    context: QueryContext
    generated_at: float
    total: UsageSummary
    details: tuple[UsageDetail, ...]
    groups: tuple[tuple[str, tuple[UsageGroup, ...]], ...]
    sources: tuple[SourceQuality, ...]
    notices: tuple[str, ...]
    catalog: RateCatalog
    comparisons: tuple[PlanComparison, ...]
    combined_comparison: PlanComparison
    models: tuple[str, ...]
    unpriced_models: tuple[str, ...]
    write_models: tuple[str, ...]
    missing_effort_records: int
    missing_effort_tokens: int
    app_version: str = APP_VERSION
    build_id: str = BUILD_ID
    settings_version: str | None = None  # None for explicit programmatic queries without settings.
    parser_version: str = PARSER_VERSION
    reconciliation_version: str = RECONCILIATION_VERSION
    valuation_policy: str = POLICY_VERSION
    query_version: str = QUERY_VERSION

    def groups_for(self, dimension, sort="key"):
        if dimension not in DIMENSIONS:
            raise ValueError("Unsupported usage dimension.")
        rows = dict(self.groups)[dimension]
        if sort == "key":
            return rows
        if sort == "value_desc":
            # copy_negate avoids the caller's Decimal context rounding exact sort keys.
            key = lambda g: (g.summary.value.amount_usd is None,
                             g.summary.value.amount_usd.copy_negate() if g.summary.value.amount_usd is not None else 0,
                             g.group_id)
        elif sort == "tokens_desc":
            key = lambda g: (-g.summary.tokens.total, g.group_id)
        elif sort == "last_activity_desc":
            key = lambda g: (-g.last_activity, g.group_id)
        else:
            raise ValueError("Unsupported usage sort.")
        return tuple(sorted(rows, key=key))


def summarize_values(values, conversation_ids=None):
    """The only summary/group calculation; accepts already valued events."""
    values = tuple(values)
    records = tuple(v.record for v in values)
    known = tuple(r.reasoning_tokens for r in records if r.reasoning_tokens is not None)
    return UsageSummary(aggregate_values(values), ReasoningSummary(sum(known) if known else None,
                        len(known), len(records) - len(known)), len(records),
                        len(set(conversation_ids)) if conversation_ids is not None else len({(r.provider, r.session) for r in records}),
                        len({r.project for r in records}))


def summarize_details(details, project_ids=None):
    details = tuple(details)
    summary = summarize_values((d.valuation for d in details), (d.conversation_id for d in details))
    if project_ids is not None:
        summary = replace(summary, project_count=len({project_ids[d.detail_id] for d in details if project_ids[d.detail_id] is not None}))
    return summary


def _conversation_id(entry):
    if isinstance(entry, CanonicalEvent):
        return "conversation-v1:" + _digest([entry.record.provider, "canonical", entry.conversation_key])
    return "conversation-v1:" + _digest([entry.provider, "legacy", entry.session])


def _group_key(dimension, detail, timezone):
    r = detail.record
    # The conversation's full reconciliation identity owns membership. Its
    # display session label (including a weak source surrogate) cannot merge it.
    if dimension == "conversation":
        return (r.provider, detail.conversation_id)
    if dimension == "day":
        return (local_datetime(r.timestamp, timezone).date().isoformat(),)
    return {"provider": (r.provider,), "model_effort": (r.provider, r.model, r.effort),
            "effort": (r.provider, r.effort), "model": (r.provider, r.model),
            "project": (r.provider, r.project)}[dimension]


def build_usage_result(entries, context, catalog=None, fees=None, sources=(), notices=(),
                       calendar_compatible=True, valuations=None, project_ids=None, filter_project_ids=None):
    """Pure query over accepted events (or explicit legacy Record projections).

    Reconciliation precedes this seam. Duplicate canonical IDs are rejected;
    repeated legacy records remain separate compatibility occurrences. Optional
    persisted valuations are validated against facts/catalog. An optional complete
    canonical-event project map counts normalized known identities; null is unknown.
    Legacy callers retain their exact-label project-count behavior.
    """
    catalog = build_catalog() if catalog is None else catalog
    ranges = dict(context.ranges)
    candidates, canonical_ids = [], set()
    for entry in entries:
        event = entry if isinstance(entry, CanonicalEvent) else None
        record = event.record if event else entry
        if not isinstance(record, Record) or isinstance(record.timestamp, bool) or not math.isfinite(record.timestamp):
            raise ValueError("Usage entries require records with finite timestamps.")
        if event:
            if event.event_id in canonical_ids:
                raise ValueError("Duplicate accepted event identity; reconcile before querying.")
            canonical_ids.add(event.event_id)
        if record.provider not in ranges or not ranges[record.provider].contains(record.timestamp):
            continue
        if not context.filters.matches(record, context.timezone, _conversation_id(entry),
                                       (filter_project_ids if filter_project_ids is not None else project_ids).get(event.event_id)
                                       if (filter_project_ids is not None or project_ids is not None) and event else None):
            continue
        # Compatibility fingerprint is an occurrence ID, never cross-copy event identity.
        identity = event.event_id if event else "legacy:" + _digest([
            record.provider, record.timestamp, record.session, record.project, record.model,
            record.effort, record.effort_source, record.turn_id, record.reasoning_tokens,
            record.tokens.input, record.tokens.output, record.tokens.cached, record.tokens.write5m, record.tokens.write1h])
        candidates.append((record.timestamp, identity, entry))
    occurrences, details = defaultdict(int), []
    for _, identity, entry in sorted(candidates, key=lambda c: (c[0], c[1])):
        occurrence = occurrences[identity]
        occurrences[identity] += 1
        detail_id = identity if isinstance(entry, CanonicalEvent) else identity + ":" + str(occurrence)
        if valuations is None:
            value = value_event(entry, catalog)
        else:
            value = valuations.get(identity)
            record = entry.record if isinstance(entry, CanonicalEvent) else entry
            if (not isinstance(value, EventValuation) or value.record != record
                    or value.event_id != identity or value.pricing_version != catalog.version):
                raise ValueError("Persisted valuations must cover the matching event and pricing version.")
        details.append(UsageDetail(detail_id, _conversation_id(entry), entry if isinstance(entry, CanonicalEvent) else None,
                                   value, summarize_values((value,), (_conversation_id(entry),))))
        if project_ids is not None:
            if identity not in project_ids or (project_ids[identity] is not None and not isinstance(project_ids[identity], str)):
                raise ValueError("Indexed queries require explicit known or unknown project identities.")
            details[-1] = replace(details[-1], summary=replace(details[-1].summary, project_count=int(project_ids[identity] is not None)))
    groups = []
    for dimension in DIMENSIONS:
        buckets = defaultdict(list)
        for detail in details:
            buckets[_group_key(dimension, detail, context.timezone)].append(detail)
        rows = tuple(sorted((UsageGroup("group-v1:" + _digest([dimension, key]),
                               (members[0].record.provider, members[0].record.session) if dimension == "conversation" else key,
                               summarize_details(members, project_ids), tuple(d.detail_id for d in members),
                               max(d.record.timestamp for d in members))
                     for key, members in buckets.items()), key=lambda g: (g.key, g.group_id)))
        groups.append((dimension, rows))
    source_map = {s.provider: s for s in sources}
    sources = tuple(source_map.get(p, SourceQuality(p, "demo" if context.demo else "not_supplied")) for p in context.providers)
    qualifications = {s.provider: (("demo" if context.demo else "ingestion_" + s.state),)
                       + (("accounting_issues_present",) if s.accounting_issues else ()) for s in sources}
    calendar = calendar_compatible and context.period == "month" and all(
        r.start == resolve_range("month", context.captured_at, timezone=context.timezone).start for _, r in context.ranges)
    comparisons, combined = compare_plans((d.valuation for d in details),
        ComparisonScope(context.providers, context.period, calendar, context.is_filtered), fees, qualifications)
    return UsageResult(context, context.captured_at, summarize_details(details, project_ids),
                       tuple(details), tuple(groups), sources, tuple(sorted(set(notices))), catalog, comparisons, combined,
                       tuple(sorted({d.record.model for d in details})),
                       tuple(sorted({d.record.model for d in details if d.valuation.state == "unpriced"})),
                       tuple(sorted({d.record.model for d in details if d.record.tokens.write5m or d.record.tokens.write1h})),
                       sum(d.record.effort == "unknown" for d in details),
                       sum(d.record.tokens.total for d in details if d.record.effort == "unknown"))


@dataclass(frozen=True)
class CollectedUsage:
    entries: tuple[CanonicalEvent | Record, ...]
    context: QueryContext
    sources: tuple[SourceQuality, ...]
    notices: tuple[str, ...]

    def query(self, prices=None, fees=None):
        return build_usage_result(self.entries, self.context, build_catalog(prices), fees, self.sources, self.notices)


def collect_usage(period="session", providers=("Codex", "Claude"), snapshots=None, roots=None,
                  now=None, demo=False, timezone=DEFAULT_TIMEZONE, filters=None):
    now = time.time() if now is None else now
    snapshots = snapshots or {}
    context = QueryContext(tuple((p, resolve_range(period, now, snapshots.get(p), timezone)) for p in providers),
                           now, period, timezone, filters or UsageFilters(), demo)
    entries, sources, notices = [], [], []
    roots = default_roots() if roots is None and not demo else (roots or {})
    for provider in context.providers:
        if demo:
            entries.extend(Record(provider, now - 60 * (3 - i), "demo-conversation", "Demo project",
                                  "gpt-5.4" if provider == "Codex" else "claude-sonnet-4-6",
                                  Tokens(4000, 1000 * (i + 1), 12000), effort, "demo metadata",
                                  f"demo-turn-{i + 1}", 300 * (i + 1) if provider == "Codex" else None)
                           for i, effort in enumerate(("medium", "high", "ultra")))
            sources.append(SourceQuality(provider, "demo"))
            continue
        scan = scan_observations(provider, roots.get(provider, []))
        result = reconcile_observations(scan.observations)
        entries.extend(result.events)
        sources.append(SourceQuality(provider, scan.state, scan.issues, result.issues,
                                     scan.roots_read, scan.files_discovered, scan.files_read))
        notices.extend(issue.message for issue in (*scan.issues, *result.issues))
        notices.append(f"{provider} source scan: {scan.state}. This describes available local files, not account-wide coverage.")
        if scan.issue_counts:
            notices.append(provider + " ingestion issues: " + ", ".join(f"{code}={count}" for code, count in scan.issue_counts.items()))
    selected = tuple(e for e in entries if dict(context.ranges)[(e.record if isinstance(e, CanonicalEvent) else e).provider].contains(
        (e.record if isinstance(e, CanonicalEvent) else e).timestamp))
    if not selected:
        notices.append("No local token records found in this period. This does not establish zero account usage.")
    return CollectedUsage(selected, context, tuple(sources), tuple(sorted(set(notices))))


def query_usage(period="session", providers=("Codex", "Claude"), snapshots=None, roots=None,
                now=None, prices=None, demo=False, plan_costs=None, timezone=DEFAULT_TIMEZONE, filters=None):
    return collect_usage(period, providers, snapshots, roots, now, demo, timezone, filters).query(prices, plan_costs)
