"""Real maintenance items from a real research piece.

Source: Goldman Sachs Research, *Top of Mind* — "IPO Surge: A Red Flag for
Markets?", 22 July 2026. Interviews with Ben Snider (GS), Jay Ritter (The IPO
Initiative, U. Florida) and Owen Lamont (Acadian).

This exists as a worked example, not decoration. It is the first real content
the maintenance strand was designed against, and it demonstrates the split
the owner asked for: the *ideas* are the point, while the numbers matter only
as reference classes for judging whether an environment is typical.

NOTE ON PROVENANCE: the source PDF is a scanned document and its OCR is
imperfect (it renders "1Q26" as "1026", and the issue number inconsistently).
Every figure below was read in context and cross-checked for internal
consistency, but this is exactly why drafted numeric items must be
owner-verified against the source snippet before they start being scheduled —
an OCR slip would otherwise be memorised as fact and reinforced for years.
"""

from __future__ import annotations

from typing import Any

from lms.maintenance.anchors import AnchorSpec, Extreme

SOURCE_TITLE = "GS Top of Mind — IPO Surge: A Red Flag for Markets? (22 Jul 2026)"
SUBJECT = "US IPO market 2026"


def _idea(
    *,
    title: str,
    prompt: str,
    key_points: list[tuple[str, bool]],
    tier: str,
    locator: str,
) -> dict[str, Any]:
    return {
        "item_type": "idea",
        "title": title,
        "prompt": prompt,
        "retention_tier": tier,
        "precision_mode": "band",
        "subject_label": SUBJECT,
        "source_locator_hint": locator,
        "payload": {
            "key_points": [{"label": label, "required": required} for label, required in key_points]
        },
    }


def _anchor(
    *, title: str, prompt: str, spec: AnchorSpec, tier: str, locator: str
) -> dict[str, Any]:
    return {
        "item_type": "reference_anchor",
        "title": title,
        "prompt": prompt,
        "retention_tier": tier,
        "precision_mode": "band",
        "subject_label": SUBJECT,
        "source_locator_hint": locator,
        "payload": spec.to_payload(),
    }


# --- Ideas: the argument, which is the primary thing to retain ------------

IDEA_ITEMS: list[dict[str, Any]] = [
    _idea(
        title="Why 2026 IPO activity reads as normalization, not a wave",
        prompt=(
            "2026 US IPO issuance hit a dollar record. Why did GS nonetheless argue this "
            "looks like a normalization rather than an IPO wave?"
        ),
        key_points=[
            ("Dollar volume is at a record but the NUMBER of IPOs is near its long-run norm", True),
            ("The record dollar figure is amplified by a few very large deals", True),
            (
                "IPO valuations are only modestly above their long-run median, far below prior booms",
                True,
            ),
            ("New supply is small relative to total equity market capitalisation", False),
        ],
        tier="warm",
        locator="p.4 — Snider interview, 'How does this year's reopening compare'",
    ),
    _idea(
        title="The three-way disagreement on the IPO surge",
        prompt=(
            "Snider, Ritter and Lamont all agree 2026 is not (yet) an IPO wave, but they "
            "differ on how much of a warning it is. Summarise each position."
        ),
        key_points=[
            (
                "Snider (GS): least worried — late-cycle warning signs absent, digestion fears overdone",
                True,
            ),
            (
                "Ritter: heavy issuance has historically predicted weaker forward returns, but the signal is WEAK",
                True,
            ),
            (
                "Lamont (Acadian): most cautious — an issuance wave is one of the 'four horsemen' of a bubble",
                True,
            ),
            (
                "Lamont's caveat: waves can run for years, so one may mark a bubble's beginning, not its end",
                True,
            ),
            ("Lamont takes some comfort from the absence of extreme first-day pops", False),
        ],
        tier="warm",
        locator="p.3-4 — overview and interviews",
    ),
    _idea(
        title="What to watch next on the IPO signal",
        prompt="Per this piece, which indicators would actually change the read on IPO froth?",
        key_points=[
            ("First-day IPO returns/pops as the speculative-euphoria gauge", True),
            ("The AI outlook, as the theme driving issuance", True),
            ("2027 supply-demand math worsens as investor lockups expire", False),
        ],
        tier="hot",
        locator="p.1 and p.4 — 'Key to watch'",
    ),
]


# --- Reference anchors: distributions for judging typicality --------------

ANCHOR_ITEMS: list[dict[str, Any]] = [
    _anchor(
        title="US IPO count per year — reference class",
        prompt=(
            "Roughly how many US IPOs occur in a typical year, and what did the boom "
            "extremes look like?"
        ),
        spec=AnchorSpec(
            metric="US IPO count per year",
            unit="IPOs",
            central_value=100,
            statistic_type="median",
            central_as_of="25-year median, as of 2026",
            typical_low=75,
            typical_high=150,
            extremes=(
                Extreme("2021 boom", 250, "2021"),
                Extreme("Dot-Com peak", 400, "1999"),
            ),
        ),
        tier="cold",
        locator="p.4 — '25-year median of IPOs per year is around 100'",
    ),
    _anchor(
        title="IPO valuation (EV/sales) — reference class",
        prompt="What EV/sales multiple do newly public US companies typically price at?",
        spec=AnchorSpec(
            metric="Median IPO EV/sales multiple",
            unit="x EV/sales",
            central_value=4,
            statistic_type="median",
            central_as_of="30-year median, as of 2026",
            typical_low=3,
            typical_high=5.5,
            extremes=(
                Extreme("2021", 7, "2021"),
                Extreme("Dot-Com peak", 9, "1999"),
            ),
        ),
        tier="cold",
        locator="p.5 — '5x EV/sales versus the 30-year median of roughly 4x'",
    ),
    _anchor(
        title="US equity issuance as a share of market cap — reference class",
        prompt=(
            "Annual US corporate equity issuance is what share of Russell 3000 market "
            "capitalisation in a normal year?"
        ),
        spec=AnchorSpec(
            metric="US equity issuance / Russell 3000 market cap",
            unit="% of market cap",
            central_value=1.0,
            statistic_type="mean",
            central_as_of="2015-2019 average",
            typical_low=0.8,
            typical_high=1.2,
            extremes=(
                Extreme("2021", 1.5, "2021"),
                Extreme("Dot-Com peak", 2.0, "1999-2000"),
            ),
            approximate_tolerance=0.25,
        ),
        tier="cold",
        locator="p.5 — 'only around 1% of Russell 3000 market capitalization'",
    ),
]


def all_items() -> list[dict[str, Any]]:
    """Return every drafted item from this source."""
    return [*IDEA_ITEMS, *ANCHOR_ITEMS]


__all__ = ["ANCHOR_ITEMS", "IDEA_ITEMS", "SOURCE_TITLE", "SUBJECT", "all_items"]
