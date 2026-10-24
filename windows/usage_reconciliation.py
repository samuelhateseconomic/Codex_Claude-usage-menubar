"""Pure observation-first accounting. No I/O, price lookup, or presentation.

Timestamps establish order between clock buckets. Equal-clock cumulative points
need an unambiguous order supported by source sequences; counter magnitude and
filenames cannot supply missing causal evidence.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
import hashlib
import json
from typing import Iterable

from usage_observations import CanonicalEvent, Counters, Observation, SourceRef, group_observations
from usage_records import Record, Tokens


RECONCILIATION_VERSION = "reconciliation-v2"


@dataclass(frozen=True)
class AccountingIssue:
    code: str
    message: str
    sources: tuple[SourceRef, ...]
    excluded_tokens: int | None = None  # Unknown excluded work is never invented.


@dataclass(frozen=True)
class ReconciliationResult:
    events: tuple[CanonicalEvent, ...]
    issues: tuple[AccountingIssue, ...]


def _digest(*values) -> str:
    return hashlib.sha256(json.dumps(values, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _refs(observations):
    return tuple(sorted({o.source for o in observations}, key=lambda r: (r.source_id, r.generation or "", r.line)))


def _issue(issues, code, message, observations):
    issues.append(AccountingIssue(code, message, _refs(observations)))


def _core(counters: Counters):
    fields = (counters.input, counters.output, counters.cached)
    return tuple(f.value for f in fields) if all(f.state == "valid" for f in fields) else None


def _has_cumulative(o):
    c = o.cumulative
    return c.state == "invalid" or any(f.state != "missing" for f in (c.input, c.output, c.cached))


def _reasoning(counters):
    r = counters.reasoning
    return r.value if r.state == "valid" and counters.output.state == "valid" and r.value <= counters.output.value else None


def _metadata(observations, issues):
    """Enrich missing copy context; qualify contradictory labels without guessing."""
    base = observations[0]
    quality = set(code for o in observations for code in o.issues)
    models = {o.model for o in observations if o.model != "unknown"}
    model = next(iter(models)) if len(models) == 1 else "unknown"
    paths = {o.project for o in observations if o.project_kind == "path"}
    project = next(iter(paths)) if len(paths) == 1 else "Unknown project"
    if not paths:
        labels = {o.project for o in observations if o.project_kind == "source_label"}
        project = next(iter(labels)) if len(labels) == 1 else "Unknown project"
    explicit = [o for o in observations if o.effort_is_explicit]
    efforts = explicit or [o for o in observations if o.effort_source != "not recorded"]
    values = {o.effort for o in efforts}
    effort = next(iter(values)) if len(values) == 1 else "unknown"
    effort_source = min((o.effort_source for o in efforts), default="not recorded")
    turns = {o.turn_id for o in observations if o.turn_id is not None}
    messages = {o.message_id for o in observations if o.message_id is not None}
    requests = {o.request_id for o in observations if o.request_id is not None}
    if any(len(v) > 1 for v in (models, paths, values, turns, messages, requests)):
        quality.add("metadata_conflict")
        _issue(issues, "metadata_conflict", "Conflicting usage metadata was retained with unknown attribution; pricing or effort may be unavailable.", observations)
        if len(values) > 1:
            effort_source = "conflicting explicit metadata"
    return replace(base, model=model, project=project, effort=effort, effort_source=effort_source,
                   turn_id=next(iter(turns)) if len(turns) == 1 else None), quality


def _event(observations, key, epoch, anchor, kind, tokens, reasoning, issues, quality=(), extra_sources=()):
    o, flags = _metadata(observations, issues)
    flags.update(quality)
    refs = tuple(sorted(set(_refs(observations) + tuple(extra_sources)), key=lambda r: (r.source_id, r.generation or "", r.line)))
    record = Record(o.provider, o.timestamp, o.conversation_id or "source-" + key[:16],
                    o.project, o.model, tokens, o.effort, o.effort_source, o.turn_id, reasoning)
    return CanonicalEvent(key, epoch, anchor, kind, record, refs, tuple(sorted(flags)),
                          reconciliation_version=RECONCILIATION_VERSION)


def _point_key(o):
    # Reasoning and missing context may be enriched across matching copies.
    return _digest(o.timestamp, *((f.state, f.value) for f in (o.cumulative.input, o.cumulative.output, o.cumulative.cached)))


def _clock_order(observations):
    """Return unique source-supported order for a single timestamp, or None."""
    nodes, by_source = defaultdict(list), defaultdict(list)
    for o in observations:
        nodes[_point_key(o)].append(o)
        by_source[(o.source.source_id, o.source.generation)].append(o)
    edges = {key: set() for key in nodes}
    incoming = {key: 0 for key in nodes}
    for sequence in by_source.values():
        previous = None
        for o in sorted(sequence, key=lambda o: o.source.line):
            key = _point_key(o)
            if previous is not None and key != previous and key not in edges[previous]:
                edges[previous].add(key)
                incoming[key] += 1
            previous = key
    ordered = []
    ready = [key for key, count in incoming.items() if count == 0]
    while len(ready) == 1:
        key = ready.pop()
        ordered.append(nodes[key])
        for following in edges[key]:
            incoming[following] -= 1
            if incoming[following] == 0:
                ready.append(following)
    return ordered if len(ordered) == len(nodes) else None


def _fork(observations, issues):
    parents = {o.fork_parent_id for o in observations if o.fork_parent_id is not None}
    dates = {o.session_created_at for o in observations if o.session_created_at is not None}
    invalid = any("invalid_fork_parent_id" in o.issues or "invalid_fork_parent_thread_id" in o.issues for o in observations)
    if invalid or len(parents) > 1 or (parents and len(dates) != 1):
        _issue(issues, "fork_boundary_conflict", "Codex fork boundary was unavailable or conflicting; the conversation was excluded.", observations)
        return None
    return bool(parents), next(iter(dates)) if parents else None


def _codex_cumulative(observations, key, issues):
    fork = _fork(observations, issues)
    if fork is None:
        return []
    forked, created = fork
    by_source = defaultdict(list)
    for o in observations:
        by_source[(o.source.source_id, o.source.generation)].append(o)
    if any(any(a.timestamp > b.timestamp for a, b in zip(sequence, sequence[1:]))
           for values in by_source.values() for sequence in [sorted(values, key=lambda o: o.source.line)]):
        _issue(issues, "source_order_conflict", "Codex timestamp and source order disagree; the conversation was excluded.", observations)
        return []
    buckets = defaultdict(list)
    for o in observations:
        buckets[o.timestamp].append(o)
    previous = None if forked else (0, 0, 0)
    previous_reasoning = None if forked else 0
    previous_refs = ()
    epoch, prior_anchor = "origin", "origin"
    events = []
    for when, bucket in sorted(buckets.items()):
        ordered = _clock_order(bucket)
        if ordered is None:
            _issue(issues, "ambiguous_sequence", "Codex observations at one timestamp have ambiguous or conflicting source order; the interval was excluded.", bucket)
            previous = previous_reasoning = None
            epoch = _digest("ambiguous", epoch, when)
            continue
        for point in ordered:
            o = point[0]
            current = _core(o.cumulative)
            anchor = _point_key(o)
            refs = _refs(point)
            if current is None or current[2] > current[0]:
                _issue(issues, "partial_counter_metadata", "Unknown or inconsistent Codex counters were excluded; a later valid observation must re-establish the baseline.", point)
                previous = previous_reasoning = None
                epoch = _digest("counter-gap", epoch, anchor)
                continue
            reasons = {_reasoning(p.cumulative) for p in point if _reasoning(p.cumulative) is not None}
            reason = next(iter(reasons)) if len(reasons) == 1 else None
            inherited = forked and when < created
            if previous is None:
                previous, previous_reasoning, previous_refs = current, reason, refs
                prior_anchor = anchor
                if not inherited:
                    _issue(issues, "baseline_reestablished", "A Codex interval without a reliable baseline was excluded; counting resumes after this observation.", point)
                continue
            if any(a < b for a, b in zip(current, previous)):
                _issue(issues, "counter_reset", "A Codex cumulative counter reset; an ambiguous interval was excluded.", point)
                epoch = _digest("reset", epoch, prior_anchor, anchor)
                previous, previous_reasoning, previous_refs, prior_anchor = current, reason, refs, anchor
                continue
            delta = tuple(a - b for a, b in zip(current, previous))
            reasoning = None
            if reason is not None and previous_reasoning is not None:
                change = reason - previous_reasoning
                if 0 <= change <= delta[1]:
                    reasoning = change
            flags = []
            if previous == (0, 0, 0) and prior_anchor == "origin" and any(delta):
                flags.append("initial_zero_baseline_assumed")
                _issue(issues, "initial_zero_baseline_assumed", "Initial Codex cumulative usage assumes a zero origin; unavailable earlier reset history cannot be reconstructed.", point)
            baseline_refs = previous_refs
            if current != previous or reason is not None:
                previous_reasoning = reason
            if current != previous:
                previous_refs, prior_anchor = refs, anchor
            previous = current
            if inherited or not any(delta):
                continue
            if delta[2] > delta[0]:
                _issue(issues, "cache_exceeds_input", "A Codex cached-input increment exceeded total input; that interval was excluded.", point)
                continue
            events.append(_event(point, key, epoch, anchor, "codex_cumulative_delta",
                                 Tokens(delta[0] - delta[2], delta[1], delta[2]), reasoning, issues,
                                 flags, baseline_refs))
    return events


def _codex_last(observations, key, issues):
    fork = _fork(observations, issues)
    if fork is None:
        return []
    forked, created = fork
    groups, weak_times = defaultdict(list), defaultdict(set)
    for o in observations:
        current = _core(o.last_usage)
        if current is None or current[2] > current[0]:
            _issue(issues, "partial_counter_metadata", "Codex last-usage counters were missing or invalid; the observation was excluded.", [o])
            continue
        if forked and o.timestamp < created:
            continue
        strong = bool(o.request_id or o.message_id)
        identity = ("ids", o.message_id or "", o.request_id or "") if strong else ("time", o.timestamp, current)
        groups[identity].append(o)
        if not strong:
            weak_times[o.timestamp].add(identity)
    events = []
    for identity, points in sorted(groups.items(), key=lambda item: str(item[0])):
        weak = identity[0] == "time"
        if weak and len(weak_times[points[0].timestamp]) > 1:
            _issue(issues, "ambiguous_last_usage", "Codex last-usage observations at one timestamp cannot be distinguished; they were excluded.", points)
            continue
        counts = tuple(max(_core(o.last_usage)[i] for o in points) for i in range(3))
        reasons = [_reasoning(o.last_usage) for o in points if _reasoning(o.last_usage) is not None]
        # Message/request identity supports updates; weaker fallback retains its label.
        _issue(issues, "last_usage_fallback", "Codex records without cumulative counters use request/message identity or weaker timestamp deduplication.", points)
        latest = max(o.timestamp for o in points)
        points = [replace(o, timestamp=latest) for o in points]
        events.append(_event(points, key, "last-usage", _digest(identity), "codex_last_usage",
                             Tokens(counts[0] - counts[2], counts[1], counts[2]), max(reasons) if reasons else None,
                             issues, ("last_usage_fallback",)))
    return events


def _codex(observations, key, issues):
    if any(o.timestamp is None for o in observations):
        _issue(issues, "unplaced_observation", "Codex usage with an unavailable timestamp prevents reliable reconciliation; the conversation was excluded.", observations)
        return []
    cumulative = [o for o in observations if _has_cumulative(o)]
    if cumulative:
        last_only = [o for o in observations if not _has_cumulative(o)]
        if last_only:
            _issue(issues, "mixed_last_usage_excluded", "Codex last-only observations alongside cumulative history were excluded to avoid charging the same usage twice.", last_only)
        return _codex_cumulative(cumulative, key, issues)
    return _codex_last(observations, key, issues)


def _claude_tokens(o, issues):
    c = o.message_usage
    core = _core(c)
    if core is None:
        _issue(issues, "partial_counter_metadata", "Unknown Claude token categories were excluded rather than treated as zero.", [o])
        return None
    if c.cache_details_state == "valid" and c.write5m.state == c.write1h.state == "valid":
        return Tokens(*core, c.write5m.value, c.write1h.value)
    if c.cache_details_state == "missing" or (c.cache_details_state == "valid" and c.write5m.state == c.write1h.state == "missing"):
        if c.legacy_write.state == "valid":
            return Tokens(*core, c.legacy_write.value, 0)
    _issue(issues, "partial_cache_metadata", "Unknown Claude cache-write categories were excluded rather than treated as zero.", [o])
    return None


def _claude(observations, key, issues):
    by_message = defaultdict(list)
    for o in observations:
        if o.timestamp is None or o.message_id is None:
            _issue(issues, "invalid_message_identity", "Claude usage records without usable timestamps or message IDs were skipped.", [o])
            continue
        by_message[o.message_id].append(o)
    events = []
    for message, values in sorted(by_message.items()):
        request_ids = {o.request_id for o in values if o.request_id is not None}
        groups = defaultdict(list)
        for o in values:
            if o.request_id is None and len(request_ids) > 1:
                _issue(issues, "ambiguous_request_identity", "Claude observations with ambiguous request identity were excluded.", [o])
                continue
            request = o.request_id or (next(iter(request_ids)) if request_ids else "")
            groups[request].append(o)
        for request, points in sorted(groups.items()):
            accepted = [(o, _claude_tokens(o, issues)) for o in points]
            accepted = [(o, tokens) for o, tokens in accepted if tokens is not None]
            if not accepted:
                continue
            points = [o for o, _ in accepted]
            detailed = [(o, t) for o, t in accepted if o.message_usage.cache_details_state == "valid"
                        and o.message_usage.write5m.state == o.message_usage.write1h.state == "valid"]
            write_sources = detailed or accepted
            write5m = max(t.write5m for _, t in write_sources)
            write1h = max(t.write1h for _, t in write_sources)
            legacy = [o.message_usage.legacy_write.value for o, _ in accepted
                      if o.message_usage.legacy_write.state == "valid"]
            if detailed and legacy and max(legacy) > write5m + write1h:
                _issue(issues, "cache_representation_conflict", "Claude legacy and detailed cache-write evidence could not be reconciled; the message was excluded.", points)
                continue
            tokens = Tokens(*(max(getattr(t, field) for _, t in accepted)
                              for field in ("input", "output", "cached")), write5m, write1h)
            reasons = [_reasoning(o.message_usage) for o in points if _reasoning(o.message_usage) is not None]
            when = max(o.timestamp for o in points)
            points = [replace(o, timestamp=when) for o in points]
            flags = []
            if not detailed and legacy and max(legacy) > 0:
                flags.append("legacy_cache_ttl_assumed")
                _issue(issues, "legacy_cache_ttl_assumed", "Legacy Claude cache writes without TTL details are estimated at the 5-minute write price.", points)
            events.append(_event(points, key, "message", "message:" + json.dumps([message, request]),
                                 "claude_message", tokens, max(reasons) if reasons else None, issues, flags))
    return events


def reconcile_observations(observations: Iterable[Observation]) -> ReconciliationResult:
    issues, events = [], []
    for group in group_observations(observations):
        unique = {}
        conflict = False
        for o in group.observations:
            identity = o.source.observation_id
            if identity in unique and unique[identity] != o:
                conflict = True
            unique[identity] = o
        points = list(unique.values())
        if conflict:
            _issue(issues, "source_observation_conflict", "A source position changed during reconciliation; the conversation was excluded.", group.observations)
            continue
        if any(o.identity_kind == "source_local" for o in points):
            _issue(issues, "weak_conversation_identity", "Usage without provider conversation identity remains source-local; cross-copy coverage is unknown.", points)
        events.extend((_codex if group.provider == "Codex" else _claude)(points, group.conversation_key, issues))
    events.sort(key=lambda event: event.record.timestamp)
    return ReconciliationResult(tuple(events), tuple(issues))
