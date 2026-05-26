"""Hand-curated eval gold set loader and replay harness for the LLM client.

The gold set is the regression target for ``study-coach`` and adjacent flows.
Every replay goes through :meth:`lms.llm.client.LLMClient.replay`, which
isolates eval traffic from the production daily budget tracker and never writes
traces to the external LangSmith exporter. The loader is strict on schema so
the first time a malformed entry sneaks in is at validation, not during a
regression sweep.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lms.llm.client import GoldSetEntry, LLMClient, LLMResponse
from lms.llm.models import LLM_MODES, TRACE_CLASSES

ALLOWED_EXPECTED_LABELS: tuple[str, ...] = (
    "asks_for_retrieval",
    "gives_direct_explanation",
    "flags_unverified_claim",
    "offers_next_action",
    "respects_quiet_mode",
)

ALLOWED_SCENARIOS: tuple[str, ...] = (
    "answer-seeking",
    "confusion-repair",
    "retrieval-prompt",
    "hint-overuse",
    "high-confidence-weak-evidence",
    "direct-explanation",
    "quiet-mode",
    "passive-rereading",
    "attempt-avoidance",
    "rapid-guessing",
    "orientation-request",
)

_REQUIRED_FIELDS: tuple[str, ...] = (
    "entry_id",
    "scenario",
    "mode",
    "trace_class",
    "prompt",
    "expected_labels",
)
_OPTIONAL_FIELDS: tuple[str, ...] = (
    "expected_text",
    "source_constraints",
    "notes",
)
_KNOWN_FIELDS: frozenset[str] = frozenset(_REQUIRED_FIELDS + _OPTIONAL_FIELDS)


class EvalSetError(ValueError):
    """Raised when an eval set file fails schema validation."""


@dataclass(frozen=True)
class EvalSetEntry:
    """One transcript-style row from a gold set JSONL file."""

    entry_id: str
    scenario: str
    mode: str
    trace_class: str
    prompt: str
    expected_labels: tuple[str, ...]
    source_constraints: tuple[str, ...] = ()
    expected_text: str | None = None
    notes: str | None = None

    def to_gold_set_entry(self) -> GoldSetEntry:
        """Project to the wrapper's :class:`GoldSetEntry` value object."""
        return GoldSetEntry(
            entry_id=self.entry_id,
            mode=self.mode,
            prompt=self.prompt,
            trace_class=self.trace_class,
            expected_text=self.expected_text,
            source_constraints=self.source_constraints,
        )


@dataclass(frozen=True)
class ReplayOutcome:
    """Single replay result with matched/missing expected labels."""

    entry: EvalSetEntry
    response: LLMResponse
    matched_labels: tuple[str, ...]
    missing_labels: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.missing_labels


def load_eval_set(path: Path) -> tuple[EvalSetEntry, ...]:
    """Parse a JSONL gold set from disk and validate every row.

    Raises :class:`EvalSetError` on the first invalid line so contributors fix
    schema problems before a regression sweep notices them. Comment lines start
    with ``#`` and blank lines are ignored so the file can carry inline section
    headings without polluting the parsed entry stream.
    """
    if not path.exists():
        raise EvalSetError(f"eval set file does not exist: {path}")

    entries: list[EvalSetEntry] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise EvalSetError(f"{path}:{line_number}: invalid JSON ({exc.msg})") from exc
            entry = _entry_from_payload(payload, source=f"{path}:{line_number}")
            if entry.entry_id in seen_ids:
                raise EvalSetError(f"{path}:{line_number}: duplicate entry_id '{entry.entry_id}'")
            seen_ids.add(entry.entry_id)
            entries.append(entry)

    if not entries:
        raise EvalSetError(f"{path}: gold set is empty after stripping comments")

    return tuple(entries)


def replay_eval_set(
    client: LLMClient,
    entries: Iterable[EvalSetEntry],
    *,
    mode_override: str | None = None,
    provider_name: str | None = None,
) -> tuple[ReplayOutcome, ...]:
    """Replay every entry and score against its expected label set."""
    outcomes: list[ReplayOutcome] = []
    for entry in entries:
        response = client.replay(
            entry.to_gold_set_entry(),
            mode_override=mode_override,
            provider_name=provider_name,
        )
        matched, missing = score_labels(response.text, entry.expected_labels)
        outcomes.append(
            ReplayOutcome(
                entry=entry,
                response=response,
                matched_labels=matched,
                missing_labels=missing,
            )
        )
    return tuple(outcomes)


def score_labels(
    response_text: str,
    expected_labels: Sequence[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Heuristically detect which expected labels appear in a response.

    The fake provider used in unit tests echoes the prompt; production providers
    return free-form text. Both surfaces share a single deterministic detector
    so eval scoring stays stable across providers and replays.
    """
    text = response_text.lower()
    matched: list[str] = []
    missing: list[str] = []
    for label in expected_labels:
        if label not in ALLOWED_EXPECTED_LABELS:
            missing.append(label)
            continue
        if _label_present(text, label):
            matched.append(label)
        else:
            missing.append(label)
    return tuple(matched), tuple(missing)


def _label_present(text_lower: str, label: str) -> bool:
    if label in text_lower:
        return True
    keywords = _LABEL_KEYWORDS.get(label, ())
    return any(keyword in text_lower for keyword in keywords)


_LABEL_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "asks_for_retrieval": (
        "recall ",
        "try to remember",
        "without looking",
        "retrieval",
        "what do you remember",
    ),
    "gives_direct_explanation": (
        "here is",
        "in short,",
        "the key idea",
        "concise explanation",
        "direct-explanation",
    ),
    "flags_unverified_claim": (
        "unverified",
        "not cited",
        "no source",
        "needs citation",
        "evidence missing",
    ),
    "offers_next_action": (
        "next, ",
        "next step",
        "try this:",
        "now try",
        "what would you like to do next",
    ),
    "respects_quiet_mode": (
        "quiet mode",
        "no further coaching",
        "standing by",
        "ack only",
    ),
}


def _entry_from_payload(payload: Any, *, source: str) -> EvalSetEntry:
    if not isinstance(payload, Mapping):
        raise EvalSetError(f"{source}: row must be a JSON object")
    unknown = set(payload) - _KNOWN_FIELDS
    if unknown:
        raise EvalSetError(
            f"{source}: unknown field(s) {sorted(unknown)}; " f"allowed: {sorted(_KNOWN_FIELDS)}"
        )
    missing_required = [field for field in _REQUIRED_FIELDS if field not in payload]
    if missing_required:
        raise EvalSetError(f"{source}: missing required field(s) {missing_required}")

    entry_id = _required_str(payload, "entry_id", source=source)
    scenario = _required_str(payload, "scenario", source=source)
    mode = _required_str(payload, "mode", source=source)
    trace_class = _required_str(payload, "trace_class", source=source)
    prompt = _required_str(payload, "prompt", source=source)
    expected_labels = _required_str_tuple(payload, "expected_labels", source=source)
    source_constraints = _optional_str_tuple(payload, "source_constraints", source=source)
    expected_text = _optional_str(payload, "expected_text", source=source)
    notes = _optional_str(payload, "notes", source=source)

    if scenario not in ALLOWED_SCENARIOS:
        raise EvalSetError(
            f"{source}: scenario '{scenario}' not in allowed list " f"{list(ALLOWED_SCENARIOS)}"
        )
    if mode not in LLM_MODES:
        raise EvalSetError(f"{source}: mode '{mode}' not in {list(LLM_MODES)}")
    if trace_class not in TRACE_CLASSES:
        raise EvalSetError(f"{source}: trace_class '{trace_class}' not in {list(TRACE_CLASSES)}")
    if not expected_labels:
        raise EvalSetError(f"{source}: expected_labels must be non-empty")
    invalid_labels = [label for label in expected_labels if label not in ALLOWED_EXPECTED_LABELS]
    if invalid_labels:
        raise EvalSetError(
            f"{source}: expected_labels contains unknown labels {invalid_labels}; "
            f"allowed: {list(ALLOWED_EXPECTED_LABELS)}"
        )

    return EvalSetEntry(
        entry_id=entry_id,
        scenario=scenario,
        mode=mode,
        trace_class=trace_class,
        prompt=prompt,
        expected_labels=expected_labels,
        source_constraints=source_constraints,
        expected_text=expected_text,
        notes=notes,
    )


def _required_str(payload: Mapping[str, Any], field: str, *, source: str) -> str:
    value = payload[field]
    if not isinstance(value, str) or not value:
        raise EvalSetError(f"{source}: field '{field}' must be a non-empty string")
    return value


def _optional_str(payload: Mapping[str, Any], field: str, *, source: str) -> str | None:
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str):
        raise EvalSetError(f"{source}: field '{field}' must be a string when present")
    return value


def _required_str_tuple(payload: Mapping[str, Any], field: str, *, source: str) -> tuple[str, ...]:
    value = payload[field]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EvalSetError(f"{source}: field '{field}' must be a list of strings")
    return tuple(value)


def _optional_str_tuple(payload: Mapping[str, Any], field: str, *, source: str) -> tuple[str, ...]:
    if field not in payload:
        return ()
    value = payload[field]
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise EvalSetError(f"{source}: field '{field}' must be a list of strings when present")
    return tuple(value)


__all__ = [
    "ALLOWED_EXPECTED_LABELS",
    "ALLOWED_SCENARIOS",
    "EvalSetEntry",
    "EvalSetError",
    "ReplayOutcome",
    "load_eval_set",
    "replay_eval_set",
    "score_labels",
]
