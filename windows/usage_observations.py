"""Metadata-only extraction contracts. No filesystem, provider, pricing, or GUI I/O.

Observations are evidence, not accepted billable events. In particular, an absent
counter is never normalized to zero here. The pure reconciliation module owns acceptance.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import math
from typing import Iterable, Literal

from usage_records import Record


PARSER_VERSION = "observations-v1"
PARSER_CACHE_VERSION = PARSER_VERSION + ":fork-origin-3"
FieldState = Literal["valid", "missing", "invalid"]


def _identity(*parts: str | int | None) -> str:
    encoded = json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    line: int
    generation: str | None = None  # S03 establishes verified file generations.

    def __post_init__(self):
        if (not isinstance(self.source_id, str) or not self.source_id
                or not isinstance(self.line, int) or isinstance(self.line, bool) or self.line < 1):
            raise ValueError("Source references need an identity and positive physical line.")

    @property
    def observation_id(self) -> str:
        # Source-local evidence identity, deliberately not a global event identity.
        return _identity(PARSER_VERSION, self.source_id, self.generation, self.line)


@dataclass(frozen=True)
class Counter:
    value: int | None = None
    state: FieldState = "missing"

    def __post_init__(self):
        valid = isinstance(self.value, int) and not isinstance(self.value, bool) and self.value >= 0
        if self.state not in ("valid", "missing", "invalid") or (self.state == "valid") != valid:
            raise ValueError("Counter state and value disagree.")
        if self.state != "valid" and self.value is not None:
            raise ValueError("Unknown counters cannot retain raw invalid values.")


@dataclass(frozen=True)
class Counters:
    state: FieldState
    input: Counter = field(default_factory=Counter)
    output: Counter = field(default_factory=Counter)
    cached: Counter = field(default_factory=Counter)
    write5m: Counter = field(default_factory=Counter)
    write1h: Counter = field(default_factory=Counter)
    legacy_write: Counter = field(default_factory=Counter)
    reasoning: Counter = field(default_factory=Counter)
    cache_details_state: FieldState = "missing"


@dataclass(frozen=True)
class Observation:
    provider: Literal["Codex", "Claude"]
    source: SourceRef
    conversation_id: str | None
    timestamp: float | None
    timestamp_state: FieldState
    kind: Literal["codex_token_count", "claude_message"]
    project: str
    project_kind: Literal["path", "source_label", "unknown"]
    model: str
    effort: str
    effort_source: str
    effort_is_explicit: bool = False
    turn_id: str | None = None
    message_id: str | None = None
    request_id: str | None = None
    cumulative: Counters = field(default_factory=lambda: Counters("missing"))
    last_usage: Counters = field(default_factory=lambda: Counters("missing"))
    message_usage: Counters = field(default_factory=lambda: Counters("missing"))
    session_created_at: float | None = None
    fork_parent_id: str | None = None
    context_source: SourceRef | None = None
    session_source: SourceRef | None = None
    context_window: Counter = field(default_factory=Counter)  # Capacity, not request size.
    issues: tuple[str, ...] = ()
    parser_version: str = PARSER_VERSION

    @property
    def identity_kind(self) -> str:
        return "provider" if self.conversation_id is not None else "source_local"

    @property
    def conversation_key(self) -> str:
        return _identity(self.provider, self.identity_kind, self.conversation_id or self.source.source_id)


@dataclass(frozen=True)
class ConversationObservations:
    provider: str
    conversation_key: str
    observations: tuple[Observation, ...]


def group_observations(observations: Iterable[Observation]) -> tuple[ConversationObservations, ...]:
    """Deterministic reconciliation input; tuple order is not causal evidence.

    Tied timestamps still require source sequence/IDs/context in S02. Separate
    files with missing conversation IDs must never merge by their basenames.
    """
    groups = defaultdict(list)
    for observation in observations:
        groups[(observation.provider, observation.conversation_key)].append(observation)
    return tuple(ConversationObservations(provider, key, tuple(sorted(values, key=lambda o: (
        o.timestamp is None, o.timestamp if o.timestamp is not None else 0,
        o.source.source_id, o.source.generation or "", o.source.line,
    )))) for (provider, key), values in sorted(groups.items()))


@dataclass(frozen=True)
class CanonicalEvent:
    """Accepted-event contract emitted by observation-first reconciliation.

    Anchors must come from reconciled evidence, including the reset epoch, never
    just a file position or cumulative numeric tuple. Provenance is not identity.
    """
    conversation_key: str
    epoch_anchor: str
    event_anchor: str
    source_kind: Literal["codex_cumulative_delta", "codex_last_usage", "claude_message"]
    record: Record
    sources: tuple[SourceRef, ...]
    quality: tuple[str, ...] = ()
    request_context_tokens: int | None = None
    request_context_source: str = "not recorded"
    reconciliation_version: str = "reconciliation-v1"

    def __post_init__(self):
        if not all((self.conversation_key, self.epoch_anchor, self.event_anchor, self.sources)):
            raise ValueError("Accepted events require reconciled identity and provenance.")
        if self.source_kind not in ("codex_cumulative_delta", "codex_last_usage", "claude_message"):
            raise ValueError("Unsupported accepted-event source kind.")
        expected_provider = "Claude" if self.source_kind == "claude_message" else "Codex"
        if self.record.provider != expected_provider:
            raise ValueError("Accepted source kind and provider disagree.")
        tokens = self.record.tokens
        for value in (tokens.input, tokens.output, tokens.cached, tokens.write5m, tokens.write1h):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("Accepted token categories must be nonnegative integers.")
        reasoning = self.record.reasoning_tokens
        if reasoning is not None and (not isinstance(reasoning, int) or isinstance(reasoning, bool)
                                      or not 0 <= reasoning <= tokens.output):
            raise ValueError("Reasoning must be a nullable subset of output.")
        context = self.request_context_tokens
        if context is not None and (not isinstance(context, int) or isinstance(context, bool) or context < 0
                                    or self.request_context_source == "not recorded"):
            raise ValueError("Request context requires a nonnegative count and evidence source.")
        if not math.isfinite(self.record.timestamp):
            raise ValueError("Accepted events require a finite timestamp.")

    @property
    def event_id(self) -> str:
        return _identity(self.reconciliation_version, self.record.provider, self.conversation_key,
                         self.epoch_anchor, self.event_anchor, self.source_kind)


def object_value(value) -> dict:
    return value if isinstance(value, dict) else {}


def timestamp(value) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


def recorded_effort(*sources: tuple[str, dict]) -> tuple[str, str] | None:
    """Preserve explicit wire labels; budgets and content are not effort evidence."""
    for name, data in sources:
        for key in ("effort", "reasoning_effort", "reasoningEffort", "effortValue", "effortLevel"):
            if key not in data:
                continue
            value = data[key]
            if isinstance(value, str) and value.strip() and len(value) <= 80 and not any(ord(c) < 32 for c in value):
                return value.strip(), f"{name}.{key}"
            return "unknown", f"{name}.{key} (unavailable)"
    return None


def _text(value) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _text_issue(data: dict, key: str, label: str, required: bool = False) -> tuple[str, ...]:
    if key not in data:
        return (f"missing_{label}",) if required else ()
    return (f"invalid_{label}",) if _text(data[key]) is None else ()


def _counter(data: dict, key: str, container_state: FieldState = "valid") -> Counter:
    if container_state != "valid":
        return Counter(state=container_state)
    if key not in data:
        return Counter()
    value = data[key]
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return Counter(value, "valid")
    return Counter(state="invalid")


def _container(data: dict, key: str) -> tuple[dict, FieldState]:
    if key not in data:
        return {}, "missing"
    return (data[key], "valid") if isinstance(data[key], dict) else ({}, "invalid")


def _counters(data: dict, key: str, provider: str, parent_state: FieldState = "valid") -> Counters:
    values, state = _container(data, key) if parent_state == "valid" else ({}, parent_state)
    creation, creation_state = _container(values, "cache_creation") if state == "valid" else ({}, state)
    reasoning_key = "reasoning_output_tokens"
    if reasoning_key in values:
        reasoning = _counter(values, reasoning_key, state)
    else:
        details, details_state = _container(values, "output_tokens_details") if state == "valid" else ({}, state)
        reasoning = _counter(details, "reasoning_tokens", details_state)
    return Counters(
        state=state,
        input=_counter(values, "input_tokens", state),
        output=_counter(values, "output_tokens", state),
        cached=_counter(values, "cached_input_tokens" if provider == "Codex" else "cache_read_input_tokens", state),
        write5m=_counter(creation, "ephemeral_5m_input_tokens", creation_state),
        write1h=_counter(creation, "ephemeral_1h_input_tokens", creation_state),
        legacy_write=_counter(values, "cache_creation_input_tokens", state),
        reasoning=reasoning, cache_details_state=creation_state,
    )


def _time_state(entry: dict) -> tuple[float | None, FieldState]:
    value = timestamp(entry.get("timestamp"))
    return value, "valid" if value is not None else ("missing" if "timestamp" not in entry else "invalid")


def _issues(conversation_id: str | None, time_state: FieldState) -> tuple[str, ...]:
    result = []
    if conversation_id is None:
        result.append("weak_conversation_identity")
    if time_state != "valid":
        result.append(f"{time_state}_timestamp")
    return tuple(result)


def extract_codex(entries: Iterable[tuple[int, dict]], source_id: str,
                  generation: str | None = None) -> tuple[Observation, ...]:
    conversation = created = fork_parent = context_source = session_source = None
    project, project_kind, model = "Unknown project", "unknown", "unknown"
    effort, effort_source, turn_id = "unknown", "not recorded", None
    session_issues = turn_issues = ()
    result = []
    for line, entry in entries:
        source = SourceRef(source_id, line, generation)
        payload = object_value(entry.get("payload"))
        kind = entry.get("type")
        if kind == "session_meta":
            # Desktop child rollouts start with their own fork header, then
            # replay ancestor session headers as inherited context. The outer
            # fork owns this file's identity, creation boundary and provenance;
            # replay must not merge independent counters into the parent.
            if session_source is not None and fork_parent is not None:
                continue
            session_source = source
            conversation = _text(payload.get("id"))
            project = _text(payload.get("cwd")) or "Unknown project"
            project_kind = "path" if _text(payload.get("cwd")) else "unknown"
            created = timestamp(entry.get("timestamp"))
            fork_parent = _text(payload.get("forked_from_id")) or _text(payload.get("forked_from_thread_id"))
            session_issues = _text_issue(payload, "id", "conversation_id", required=True)
            session_issues += _text_issue(payload, "cwd", "project")
            session_issues += _text_issue(payload, "forked_from_id", "fork_parent_id")
            session_issues += _text_issue(payload, "forked_from_thread_id", "fork_parent_thread_id")
            if fork_parent is not None and created is None:
                session_issues += ("unknown_fork_boundary",)
        elif kind == "turn_context":
            context_source = source
            model = _text(payload.get("model")) or "unknown"
            effort, effort_source = recorded_effort(
                ("Codex turn_context", payload),
                ("Codex collaboration settings", object_value(object_value(payload.get("collaboration_mode")).get("settings"))),
            ) or ("unknown", "not recorded")
            turn_id = _text(payload.get("turn_id"))
            turn_issues = _text_issue(payload, "model", "model", required=True)
            turn_issues += _text_issue(payload, "turn_id", "turn_id")
        elif kind == "event_msg" and payload.get("type") == "token_count":
            when, state = _time_state(entry)
            info, info_state = _container(payload, "info")
            cumulative = _counters(info, "total_token_usage", "Codex", info_state)
            last = _counters(info, "last_token_usage", "Codex", info_state)
            result.append(Observation(
                provider="Codex", source=source, conversation_id=conversation,
                timestamp=when, timestamp_state=state, kind="codex_token_count",
                project=project, project_kind=project_kind, model=model,
                effort=effort, effort_source=effort_source, effort_is_explicit=effort_source != "not recorded", turn_id=turn_id,
                message_id=_text(payload.get("message_id")), request_id=_text(payload.get("request_id")),
                cumulative=cumulative, last_usage=last, session_created_at=created,
                fork_parent_id=fork_parent, context_source=context_source, session_source=session_source,
                context_window=_counter(info, "model_context_window", info_state),
                issues=session_issues + turn_issues + _issues(conversation, state)
                + _text_issue(payload, "message_id", "message_id")
                + _text_issue(payload, "request_id", "request_id"),
            ))
    return tuple(result)


def extract_claude(entries: Iterable[tuple[int, dict]], source_id: str,
                   source_label: str = "Unknown project", generation: str | None = None) -> tuple[Observation, ...]:
    project = None
    turn_effort = None
    turn_id = context_source = None
    result = []
    for line, entry in entries:
        source = SourceRef(source_id, line, generation)
        recorded_project = _text(entry.get("cwd"))
        if recorded_project is not None:
            project = recorded_project
        message = object_value(entry.get("message"))
        if entry.get("type") == "user":
            # Inspect only block types to distinguish tool results; retain no content.
            content = message.get("content")
            tool_result = isinstance(content, list) and bool(content) and all(
                isinstance(block, dict) and block.get("type") == "tool_result" for block in content)
            if not tool_result:
                turn_effort = recorded_effort(("Claude user", entry), ("Claude user message", message),
                                              ("Claude user output_config", object_value(message.get("output_config"))))
                turn_id = _text(entry.get("uuid"))
                context_source = source
            continue
        if entry.get("type") != "assistant" or message.get("model") == "<synthetic>":
            continue
        when, state = _time_state(entry)
        conversation = _text(entry.get("sessionId"))
        message_id = _text(message.get("id"))
        explicit_effort = recorded_effort(
            ("Claude assistant", entry), ("Claude assistant message", message),
            ("Claude output_config", object_value(message.get("output_config"))),
            ("Claude request output_config", object_value(object_value(entry.get("request")).get("output_config"))),
        )
        effort, effort_source = explicit_effort or turn_effort or ("unknown", "not recorded")
        issues = _issues(conversation, state) + _text_issue(entry, "sessionId", "conversation_id", required=True)
        issues += _text_issue(entry, "requestId", "request_id")
        issues += _text_issue(entry, "cwd", "project")
        issues += _text_issue(message, "id", "message_id", required=True)
        issues += _text_issue(message, "model", "model", required=True)
        result.append(Observation(
            provider="Claude", source=source, conversation_id=conversation,
            timestamp=when, timestamp_state=state, kind="claude_message",
            project=project or source_label, project_kind="path" if project else "source_label",
            model=_text(message.get("model")) or "unknown", effort=effort, effort_source=effort_source,
            effort_is_explicit=explicit_effort is not None,
            turn_id=turn_id, message_id=message_id, request_id=_text(entry.get("requestId")),
            message_usage=_counters(message, "usage", "Claude"), context_source=context_source,
            issues=issues,
        ))
    return tuple(result)
