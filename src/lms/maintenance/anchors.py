"""Reference-class anchors: distributions, not point values.

An allocator reading "the 25-year median is about 100 IPOs a year, 2021 had
over 250, and 1999 had nearly 400" can judge whether this year is typical.
Recalling the median to the decimal adds nothing to that judgment. So an
anchor stores the *distribution* and grades on **band membership**.

Three precision modes, because the owner should choose how strictly to be
held:

``band``        the answer must land in the right part of the distribution
``approximate`` the answer must fall within a tolerance of the true value
``exact``       the answer must match after rounding

Grading here is fully deterministic — no model call, no provider, no
confidentiality question. That is a happy accident of the design: the most
quantitative items are also the most reliably gradable.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

# Ordered from lowest to highest so comparisons are meaningful.
BANDS: tuple[str, ...] = ("far-below", "below", "typical", "above", "far-above")

StatisticType = Literal["median", "mean", "mode"]


@dataclass(frozen=True)
class Extreme:
    """A notable historical reading, e.g. the Dot-Com peak."""

    label: str
    value: float
    period: str


@dataclass(frozen=True)
class AnchorSpec:
    """The distribution a reference anchor teaches."""

    metric: str
    unit: str
    central_value: float
    statistic_type: StatisticType
    # Inclusive bounds of the "typical" band. Readings outside these are
    # above/below; readings beyond the extreme_factor multiple are far-.
    typical_low: float
    typical_high: float
    extremes: tuple[Extreme, ...] = ()
    # Vintage of the central tendency. A 25-year median is a moving fact.
    central_as_of: str | None = None
    # Tolerance for ``approximate`` mode, as a fraction of the true value.
    approximate_tolerance: float = 0.20

    def __post_init__(self) -> None:
        for name, value in (
            ("central_value", self.central_value),
            ("typical_low", self.typical_low),
            ("typical_high", self.typical_high),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite; got {value!r}")
        if self.typical_low > self.typical_high:
            raise ValueError("typical_low must not exceed typical_high")
        if not math.isfinite(self.approximate_tolerance) or self.approximate_tolerance <= 0:
            raise ValueError("approximate_tolerance must be a positive, finite fraction")

    def classify(self, reading: float) -> str:
        """Return the band a reading falls into."""
        if not math.isfinite(reading):
            raise ValueError(f"reading must be finite; got {reading!r}")
        span = self.typical_high - self.typical_low
        # A degenerate band (single point) still needs a sane far- threshold.
        margin = span if span > 0 else abs(self.central_value) * 0.5
        if reading < self.typical_low:
            return "far-below" if reading < self.typical_low - margin else "below"
        if reading > self.typical_high:
            return "far-above" if reading > self.typical_high + margin else "above"
        return "typical"

    def to_payload(self) -> dict[str, Any]:
        """Serialize for the item's JSON payload column."""
        return {
            "metric": self.metric,
            "unit": self.unit,
            "central_value": self.central_value,
            "statistic_type": self.statistic_type,
            "typical_low": self.typical_low,
            "typical_high": self.typical_high,
            "central_as_of": self.central_as_of,
            "approximate_tolerance": self.approximate_tolerance,
            "extremes": [
                {"label": e.label, "value": e.value, "period": e.period} for e in self.extremes
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> AnchorSpec:
        """Rebuild a spec from a stored payload."""
        return cls(
            metric=str(payload["metric"]),
            unit=str(payload["unit"]),
            central_value=float(payload["central_value"]),
            statistic_type=payload.get("statistic_type", "median"),
            typical_low=float(payload["typical_low"]),
            typical_high=float(payload["typical_high"]),
            central_as_of=payload.get("central_as_of"),
            approximate_tolerance=float(payload.get("approximate_tolerance", 0.20)),
            extremes=tuple(
                Extreme(label=str(e["label"]), value=float(e["value"]), period=str(e["period"]))
                for e in payload.get("extremes", [])
            ),
        )


@dataclass(frozen=True)
class GradeResult:
    """The outcome of grading one answer."""

    score: float  # 0.0 - 1.0
    passed: bool
    explanation: str
    detail: dict[str, Any]


_NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")


def parse_reading(answer: str) -> float | None:
    """Pull the first number out of a free-text answer.

    Accepts the shorthand people actually type: ``~100``, ``about 4x``,
    ``$125bn``, ``1.5%``. Returns None when there is no number to grade.
    """
    if not answer:
        return None
    match = _NUMBER.search(answer.replace(",", ""))
    if match is None:
        return None
    try:
        value = float(match.group())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def grade_anchor_recall(
    spec: AnchorSpec, answer: str, *, precision_mode: str = "band"
) -> GradeResult:
    """Grade a recalled central value against the anchor's distribution."""
    reading = parse_reading(answer)
    if reading is None:
        return GradeResult(
            score=0.0,
            passed=False,
            explanation=f"No number found in the answer. The {spec.statistic_type} is "
            f"{_fmt(spec.central_value)} {spec.unit}.",
            detail={"parsed": None},
        )

    truth = spec.central_value
    if precision_mode == "exact":
        passed = round(reading, 2) == round(truth, 2)
        score = 1.0 if passed else 0.0
    elif precision_mode == "approximate":
        tolerance = abs(truth) * spec.approximate_tolerance
        passed = abs(reading - truth) <= tolerance
        score = 1.0 if passed else 0.0
    else:  # band
        passed = spec.classify(reading) == spec.classify(truth)
        score = 1.0 if passed else 0.0

    explanation = (
        f"You said {_fmt(reading)}; the {spec.statistic_type} is "
        f"{_fmt(truth)} {spec.unit}"
        + (f" (as of {spec.central_as_of})" if spec.central_as_of else "")
        + "."
    )
    if spec.extremes:
        extremes = "; ".join(f"{e.label} {_fmt(e.value)} ({e.period})" for e in spec.extremes)
        explanation += f" For scale — {extremes}."
    return GradeResult(
        score=score,
        passed=passed,
        explanation=explanation,
        detail={"parsed": reading, "truth": truth, "precision_mode": precision_mode},
    )


def grade_typicality_judgment(spec: AnchorSpec, answer: str, *, reading: float) -> GradeResult:
    """Grade the comparative question: is this reading typical or not?

    This is the form that exercises the actual skill — deciding whether the
    current environment is unusual — rather than testing number recall.
    """
    expected = spec.classify(reading)
    stated = _stated_band(answer)
    if stated is None:
        return GradeResult(
            score=0.0,
            passed=False,
            explanation=f"Could not read a judgment from the answer. {_fmt(reading)} "
            f"{spec.unit} is {expected} for this metric.",
            detail={"expected": expected, "stated": None},
        )
    # Adjacent bands earn partial credit: calling a far-above reading merely
    # "above" is a smaller error than calling it typical.
    distance = abs(BANDS.index(stated) - BANDS.index(expected))
    score = {0: 1.0, 1: 0.5}.get(distance, 0.0)
    return GradeResult(
        score=score,
        passed=distance == 0,
        explanation=(
            f"You judged '{stated}'; {_fmt(reading)} {spec.unit} is '{expected}' against a "
            f"typical band of {_fmt(spec.typical_low)}-{_fmt(spec.typical_high)}."
        ),
        detail={"expected": expected, "stated": stated, "band_distance": distance},
    )


_BAND_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("far-above", ("far above", "far-above", "way above", "extreme high", "record")),
    ("far-below", ("far below", "far-below", "way below", "extreme low")),
    ("above", ("above", "high", "elevated", "rich", "hot")),
    ("below", ("below", "low", "depressed", "cold", "muted")),
    ("typical", ("typical", "normal", "in line", "average", "unremarkable", "middling")),
)


def _stated_band(answer: str) -> str | None:
    """Map free-text judgment language onto a band."""
    text = (answer or "").lower()
    for band, needles in _BAND_PATTERNS:
        if any(needle in text for needle in needles):
            return band
    return None


def _fmt(value: float) -> str:
    """Render a number the way a person would say it."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


__all__ = [
    "BANDS",
    "AnchorSpec",
    "Extreme",
    "GradeResult",
    "grade_anchor_recall",
    "grade_typicality_judgment",
    "parse_reading",
]
