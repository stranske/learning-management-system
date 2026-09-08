"""Coercing values into the numbers a capability gap is computed from.

`ui/capability_gap.py` sits at 74.5% and its unexercised statements are the coercions. They
deliberately return 0 rather than None — a rendered card needs a number — which means every way
of being wrong here shows a learner a real-looking score rather than an error.

The repository and UI helpers retain different boolean and non-finite contracts. Issue #626
makes repository numeric conversion defensive so malformed values cannot hide weak mastery.
"""

from __future__ import annotations

import math

import pytest

from lms.capability.repository import _as_float as repository_as_float
from lms.ui.capability_gap import _as_float, _as_int

# ---------------------------------------------------------------------------------------------
# The UI coercions.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected", [(3, 3.0), (3.7, 3.7), (-3.7, -3.7), ("2.5", 2.5), (0, 0.0)]
)
def test_numbers_and_numeric_strings_are_read(value, expected):
    assert _as_float(value) == expected


@pytest.mark.parametrize("value", ["abc", "", None, [1], {}, object()])
def test_unreadable_values_become_zero_rather_than_raising(value):
    """A DELIBERATE choice, not an oversight: this feeds a rendered card, and a card that raises
    takes the whole surface down where a zero shows a visibly wrong number instead.

    The cost is that an unreadable score is indistinguishable from a genuine zero once rendered,
    which is why the repository layer — not this one — is where a real measurement belongs.
    """
    assert _as_float(value) == 0.0


def test_a_boolean_is_zero_not_one():
    """`isinstance(True, int)` is True in Python, so without the explicit guard a flag column
    would render as a score of 1.0 — a perfect mastery estimate conjured from a checkbox."""
    assert _as_float(True) == 0.0
    assert _as_float(False) == 0.0
    assert _as_int(True) == 0


@pytest.mark.parametrize(
    "value, expected", [(3, 3), (3.7, 3), (-3.7, -3), ("2.9", 2), ("-2.9", -2)]
)
def test_integers_truncate_toward_zero(value, expected):
    """Truncation, not rounding. An evidence count of 2.9 is two pieces of evidence; rounding it
    up would report a piece of evidence that does not exist."""
    assert _as_int(value) == expected


@pytest.mark.parametrize("value", ["inf", "-inf", "nan", "abc", "", None, [1]])
def test_non_finite_and_unreadable_integers_become_zero(value):
    """The OverflowError guard is what catches "inf" here — `int(float("inf"))` raises it, while
    NaN raises ValueError. Both are counts nobody can act on."""
    assert _as_int(value) == 0


def test_a_non_finite_float_passes_through_and_that_matters():
    """RECORDED HAZARD, pinned rather than fixed.

    `_as_float` guards bools and unreadable strings but NOT non-finite values, so "nan" survives
    as NaN. Every comparison against NaN is False — including `weighted_score < threshold` — so a
    NaN score is never classified as weak mastery and the learner reads as competent.

    Asserted here so the behaviour is visible and a future change to it is deliberate. Fixing it
    means deciding whether a NaN estimate should read as zero mastery or as absent evidence, and
    that is a product decision about how a learner is assessed, not a coercion detail.
    """
    assert math.isnan(_as_float("nan"))
    assert (_as_float("nan") < 0.7) is False
    assert math.isinf(_as_float("inf"))


# ---------------------------------------------------------------------------------------------
# The divergence.
# ---------------------------------------------------------------------------------------------


def test_the_two_as_float_helpers_do_not_agree():
    """Both helpers accept numeric strings and fall back for malformed strings.

    The repository additionally rejects non-finite numbers; its existing boolean conversion
    remains unchanged by the finite-value fix.
    """
    assert _as_float(True) == 0.0
    assert repository_as_float(True) == 1.0

    assert _as_float("abc") == 0.0
    assert repository_as_float("abc") == 0.0
    assert repository_as_float("nan") == 0.0
    assert repository_as_float("inf") == 0.0

    # They agree on the ordinary cases, which is why the divergence is easy to miss.
    assert _as_float("2.5") == repository_as_float("2.5") == 2.5
    assert _as_float(None) == repository_as_float(None) == 0.0
