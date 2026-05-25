"""Local-first PII redaction for outbound LLM trace payloads.

The wrapper runs this redactor on every payload **before** any external trace
export (LangSmith or otherwise) per the project's privacy posture in
``docs/product/early-design-decisions.md`` Segment 9. If redaction strips too
much of the payload to remain useful, the caller demotes the trace to
``ephemeral`` and skips external export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

REDACTED = "[REDACTED]"

_EMAIL_RE = re.compile(r"\b[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,2}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,16}\d\b")


@dataclass
class RedactionResult:
    """Outcome of redacting a single payload."""

    text: str
    redacted_count: int = 0
    redacted_kinds: list[str] = field(default_factory=list)
    redacted_char_count: int = 0
    original_length: int = 0

    @property
    def applied(self) -> bool:
        return self.redacted_count > 0

    @property
    def signal_loss_ratio(self) -> float:
        """Fraction of the original payload occupied by redacted spans."""
        if self.original_length == 0:
            return 0.0
        return min(1.0, self.redacted_char_count / self.original_length)


def redact_pii(text: str) -> RedactionResult:
    """Redact common PII patterns from ``text``.

    The pattern set is intentionally conservative for v1: emails, phone numbers,
    US SSNs, and obvious credit-card-shaped digit groups. Project segment 9
    treats this as a v1 best-effort layer; the structural decision is that
    redaction runs before external export, not that the regex set is exhaustive.
    """
    if not text:
        return RedactionResult(text=text or "")

    result_text = text
    redacted_count = 0
    redacted_char_count = 0
    redacted_kinds: list[str] = []

    for kind, pattern in (
        ("email", _EMAIL_RE),
        ("phone", _PHONE_RE),
        ("ssn", _SSN_RE),
        ("credit_card", _CREDIT_CARD_RE),
    ):
        matches = list(pattern.finditer(result_text))
        if not matches:
            continue
        redacted_kinds.append(kind)
        redacted_count += len(matches)
        redacted_char_count += sum(len(m.group(0)) for m in matches)
        result_text = pattern.sub(REDACTED, result_text)

    return RedactionResult(
        text=result_text,
        redacted_count=redacted_count,
        redacted_kinds=redacted_kinds,
        redacted_char_count=redacted_char_count,
        original_length=len(text),
    )


def signal_loss_ratio(original: str, redacted: str) -> float:
    """Backwards-compatible helper estimating redaction signal loss.

    Prefer :attr:`RedactionResult.signal_loss_ratio`, which knows the exact
    character count of redacted spans. This fallback walks the original text
    looking for ``[REDACTED]`` markers in the redacted text and approximates
    signal loss as ``redacted_marker_count / max(original_length, 1)``.
    """
    if not original:
        return 0.0
    marker_count = redacted.count(REDACTED) if REDACTED in redacted else 0
    if marker_count == 0:
        # Fall back to the simple length-delta heuristic for non-PII redaction.
        removed = max(0, len(original) - len(redacted))
        return removed / len(original)
    # Each marker stood in for at least one original PII-shaped token; we use a
    # conservative lower bound of len(REDACTED) to avoid over-demoting.
    return min(1.0, (marker_count * len(REDACTED)) / len(original))
