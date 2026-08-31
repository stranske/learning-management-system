"""Status lines and labels the learner UI renders, and the escaping around them.

These are small functions with a large blast radius: each turns a database value into text on a
page, and each has a fallback for the value being absent. The fallbacks are the untested half, and
they are the half that runs when something upstream is missing — which is exactly when a page
should stay legible rather than render a blank or a raw id.

Escaping is checked on every one that interpolates a value. Titles, ids and statuses are all
authored somewhere, so "this field is always safe today" is a property with an expiry date.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.cases.models import WorkProduct
from lms.graphs.repository import create_knowledge_node
from lms.ui.capability_gap import (
    _gap_action_link,
    _gap_target_label,
    _resolve_competency_titles,
    _resolve_node_titles,
)
from lms.ui.cases import (
    _error_notice,
    _form_error,
    _node_label,
    _notice_block,
    _score_line,
    _work_product_status_line,
)

# ---------------------------------------------------------------------------------------------
# Work-product status.
# ---------------------------------------------------------------------------------------------


def test_no_work_product_says_so_plainly(db_session: Session):
    """The state a learner is in before they start, and the one an empty string would leave
    looking like a broken page."""
    assert _work_product_status_line(db_session, None) == "No work product submitted yet."


@pytest.mark.parametrize(
    "status,expected",
    [
        ("submitted", "Submitted; awaiting scoring for transfer evidence."),
        ("revision-requested", "Revision requested; submit an updated work product when ready."),
    ],
)
def test_each_known_status_has_its_own_sentence(db_session: Session, status, expected):
    """These say what happens NEXT, which is the only reason a status line is on the page."""
    assert _work_product_status_line(db_session, WorkProduct(status=status)) == expected


def test_an_unrecognised_status_is_shown_rather_than_hidden(db_session: Session):
    """A status added later must not render as a blank line. Naming it is how the gap is
    noticed."""
    line = _work_product_status_line(db_session, WorkProduct(status="withdrawn"))
    assert "withdrawn" in line


def test_an_unrecognised_status_is_escaped(db_session: Session):
    product = WorkProduct(status="<script>alert(1)</script>")
    line = _work_product_status_line(db_session, product)

    assert "<script>" not in line
    assert "&lt;script&gt;" in line


def _rubric_score(session: Session, normalized: float) -> str:
    from lms.feedback.models import RubricScore

    score = RubricScore(
        rubric_id="rubric-1",
        attempt_id="attempt-1",
        learner_id="learner-1",
        scorer_type="human",
        raw_score=normalized * 10,
        normalized_score=normalized,
        max_score=10.0,
        criterion_scores=[],
    )
    session.add(score)
    session.flush()
    return score.id


def test_a_scored_product_reports_the_score(db_session: Session):
    score_id = _rubric_score(db_session, 0.82)

    line = _work_product_status_line(
        db_session, WorkProduct(status="scored", rubric_score_id=score_id)
    )

    assert "Transfer evidence recorded." in line
    assert "82%" in line


def test_a_scored_product_with_a_missing_score_still_reports_the_evidence(db_session: Session):
    """The score row is a separate lookup and can be absent. The transfer evidence still exists,
    so the sentence about it must survive a missing score."""
    line = _work_product_status_line(
        db_session, WorkProduct(status="scored", rubric_score_id="no-such-score")
    )

    assert "Transfer evidence recorded." in line


def test_a_scored_product_with_no_score_id_omits_the_score(db_session: Session):
    assert _score_line(db_session, None) == ""
    assert _score_line(db_session, "") == ""


def test_a_score_is_shown_as_a_whole_percentage(db_session: Session):
    """`:.0%` — 0.825 is "82%" not "0.825". A raw ratio on the page reads as a broken number."""
    score_id = _rubric_score(db_session, 0.825)
    assert _score_line(db_session, score_id) == "Current score 82%."


# ---------------------------------------------------------------------------------------------
# Node labels.
# ---------------------------------------------------------------------------------------------


def test_an_unlinked_node_says_so_rather_than_rendering_nothing(db_session: Session):
    assert _node_label(db_session, None) == "not linked yet"
    assert _node_label(db_session, "") == "not linked yet"


def test_a_missing_node_falls_back_to_its_id(db_session: Session):
    """A dangling reference should show the id — which is what someone would need to chase it —
    rather than an empty label that hides the dangling reference entirely."""
    assert _node_label(db_session, "node-that-was-deleted") == "node-that-was-deleted"


def test_a_missing_node_id_is_escaped(db_session: Session):
    assert "<b>" not in _node_label(db_session, "<b>node</b>")


def test_a_known_node_shows_its_title(db_session: Session):
    node = create_knowledge_node(
        db_session,
        title="Equivalent fractions",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    assert _node_label(db_session, node.id) == "Equivalent fractions"


def test_a_node_title_is_escaped(db_session: Session):
    """Titles are authored. An author who types markup must not get script execution."""
    node = create_knowledge_node(
        db_session,
        title="<img src=x onerror=alert(1)>",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    label = _node_label(db_session, node.id)

    assert "<img" not in label
    assert "&lt;img" in label


# ---------------------------------------------------------------------------------------------
# Notices.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, ""])
def test_an_absent_notice_renders_nothing(value):
    """An empty `<p>` would still take vertical space and read as a missing message."""
    assert _notice_block(value) == ""
    assert _error_notice(value) == ""


def test_a_notice_is_escaped_and_carries_its_role():
    """`role=status` and `role=alert` are what a screen reader announces; the distinction between
    them is the difference between "here is an update" and "something went wrong"."""
    notice = _notice_block("Saved <b>ok</b>")
    error = _error_notice("Failed <b>badly</b>")

    assert "role='status'" in notice
    assert "role='alert'" in error
    assert "<b>" not in notice
    assert "<b>" not in error


def _validation_error():
    from pydantic import BaseModel, ValidationError

    class _Model(BaseModel):
        body: str

    try:
        _Model(body=None)  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError("the model accepted an invalid body")


def test_our_own_message_is_shown_to_the_user():
    """A `ValueError` we raise says something the learner can act on."""
    assert _form_error(ValueError("Pick a due date in the future.")) == (
        "Pick a due date in the future."
    )


def test_a_pydantic_error_is_replaced_rather_than_shown():
    """`ValidationError` derives from `ValueError`, so an `isinstance(exc, ValueError)` test
    matched BOTH — and the friendly sentence below it was unreachable while raw pydantic output
    went to the page: field names, types, the offending input, and a pydantic.dev URL.

    Checking the more specific type first is the fix, and this test is what holds it.
    """
    rendered = _form_error(_validation_error())

    assert rendered == "Enter a work product body or artifact reference before submitting."
    for pydantic_marker in ("validation error", "pydantic", "input_value", "type="):
        assert pydantic_marker not in rendered.lower()


def test_the_capability_form_makes_the_same_distinction(db_session: Session):
    """The identical pattern, in the identical shape, one module over — and it had the identical
    defect."""
    from lms.auth.models import User
    from lms.capability.repository import create_capability_target
    from lms.learners.repository import create_learner_for_user
    from lms.ui.capability_gap import _action_error

    user = User(email="gap-ui@example.test", username="gap-ui", display_name="L")
    db_session.add(user)
    db_session.flush()
    learner_id = create_learner_for_user(db_session, user_id=user.id, display_name="L").id
    node = create_knowledge_node(
        db_session,
        title="Node",
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    target = create_capability_target(
        db_session,
        learner_id=learner_id,
        title="Target",
        target_node_ids=[node.id],
        required_evidence_types=["transfer-case"],
        confidence_threshold=0.8,
    )

    ours = _action_error(
        session=db_session,
        target_id=target.id,
        exc=ValueError("Pick a threshold between 0 and 1."),
    )
    theirs = _action_error(session=db_session, target_id=target.id, exc=_validation_error())

    assert "Pick a threshold between 0 and 1." in ours
    assert "Check the form and try again." in theirs
    assert "input_value" not in theirs


def test_an_action_error_on_a_missing_target_renders_the_not_found_page(db_session: Session):
    """The target is re-read to rebuild the page around the error. If it vanished meanwhile the
    surface has nothing to render, and must say so rather than raise inside an error handler."""
    from lms.ui.capability_gap import _action_error

    page = _action_error(session=db_session, target_id="gone", exc=ValueError("x"))
    assert "not" in page.lower()


# ---------------------------------------------------------------------------------------------
# Gap item labels.
# ---------------------------------------------------------------------------------------------


def test_a_node_gap_is_labelled_as_a_node():
    assert _gap_target_label({"knowledge_node_id": "node-1"}) == "Node node-1"


def test_a_competency_gap_is_labelled_as_a_competency():
    """The two ids look alike on a page; without the prefix a reader cannot tell which registry
    to look the gap up in."""
    assert _gap_target_label({"competency_id": "comp-1"}) == "Competency comp-1"


def test_a_node_id_wins_when_both_are_present():
    assert _gap_target_label({"knowledge_node_id": "node-1", "competency_id": "comp-1"}) == (
        "Node node-1"
    )


@pytest.mark.parametrize(
    "item",
    [{}, {"knowledge_node_id": None}, {"knowledge_node_id": ""}, {"competency_id": 42}],
)
def test_a_gap_with_no_usable_id_still_gets_a_label(item):
    """Blank, absent and non-string all fall through to the same generic label rather than
    rendering "Node None"."""
    assert _gap_target_label(item) == "Target"


def test_gap_ids_are_escaped():
    assert "<b>" not in _gap_target_label({"knowledge_node_id": "<b>x</b>"})


def test_only_a_transfer_case_recommendation_gets_an_action_link():
    """Every other action type has no page to send the learner to, and a link to nowhere is worse
    than no link."""
    assert _gap_action_link({"recommended_action_type": "review"}, learner_id="l1") == ""
    assert "transfer" in _gap_action_link(
        {"recommended_action_type": "transfer-case"}, learner_id="l1"
    )


def test_the_learner_id_in_an_action_link_is_url_quoted():
    """It goes in a query string. An unquoted id containing `&` truncates the parameter, and one
    containing a quote escapes the attribute."""
    link = _gap_action_link({"recommended_action_type": "transfer-case"}, learner_id="a b&c=d")

    assert "a b&c=d" not in link
    assert "a+b" in link or "a%20b" in link


# ---------------------------------------------------------------------------------------------
# Title resolution.
# ---------------------------------------------------------------------------------------------


def test_no_linked_nodes_says_so(db_session: Session):
    assert _resolve_node_titles(db_session, []) == "none linked yet"
    assert _resolve_competency_titles(db_session, []) == "none linked yet"


def test_unknown_ids_fall_back_to_the_id(db_session: Session):
    """Same reasoning as the node label: a dangling id is a fact worth showing."""
    assert _resolve_node_titles(db_session, ["gone-1"]) == "gone-1"
    assert _resolve_competency_titles(db_session, ["gone-2"]) == "gone-2"


def test_known_and_unknown_ids_are_listed_together_in_order(db_session: Session):
    """Dropping the unresolvable one would silently shorten the list, and a target would appear to
    have fewer linked nodes than it has."""
    node = create_knowledge_node(
        db_session,
        title="Fractions",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    assert _resolve_node_titles(db_session, [node.id, "gone"]) == "Fractions, gone"


def test_resolved_titles_are_escaped(db_session: Session):
    node = create_knowledge_node(
        db_session,
        title="<script>alert(1)</script>",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    assert "<script>" not in _resolve_node_titles(db_session, [node.id])
