"""The validators and score guards in the transfer-case repository.

Two kinds of check, both unreached, and they protect different things.

The **vocabulary** validators refuse an unrecognised status, scope or submission type. Without
them the value reaches a filter and matches nothing — which the caller sees as an empty result,
not a bad query. That is the failure mode worth naming: a typo and a genuinely empty case list are
the same page.

The **score** guards refuse arithmetic that would corrupt a learner's record. `max_score = 0` is a
ZeroDivisionError inside a scoring transaction; a negative raw score or a normalised score outside
[0, 1] is a mastery estimate that no downstream consumer can interpret, stored permanently.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.cases.repository import (
    CASE_STATUSES,
    OWNERSHIP_SCOPES,
    WORK_PRODUCT_STATUSES,
    WORK_PRODUCT_SUBMISSION_TYPES,
    _require_scope,
    _require_source_reference,
    _require_status,
    _require_submission_type,
    _require_unique_orders,
    _require_work_product_status,
    _validate_case_links,
    create_case,
    create_work_product,
    list_cases,
    list_work_products,
)
from lms.graphs.repository import create_knowledge_node


def _case(session: Session, *, title: str = "Case", scope: str = "personal", **kwargs):
    return create_case(session, title=title, ownership_scope=scope, **kwargs)


# ---------------------------------------------------------------------------------------------
# Vocabulary validators.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", WORK_PRODUCT_SUBMISSION_TYPES)
def test_every_declared_submission_type_is_accepted(value):
    _require_submission_type(value)


@pytest.mark.parametrize("value", WORK_PRODUCT_STATUSES)
def test_every_declared_work_product_status_is_accepted(value):
    _require_work_product_status(value)


@pytest.mark.parametrize("value", OWNERSHIP_SCOPES)
def test_every_declared_scope_is_accepted(value):
    _require_scope(value)


@pytest.mark.parametrize("value", CASE_STATUSES)
def test_every_declared_case_status_is_accepted(value):
    _require_status(value)


@pytest.mark.parametrize(
    "check,bad,noun",
    [
        (_require_submission_type, "essay", "submission type"),
        (_require_work_product_status, "pending", "status"),
        (_require_scope, "shared", "ownership scope"),
        (_require_status, "live", "case status"),
    ],
)
def test_an_unrecognised_value_is_refused_and_quoted_back(check, bad, noun):
    """The rejected value is in the message. Without it the author has to guess which of several
    string fields they mistyped."""
    with pytest.raises(ValueError) as excinfo:
        check(bad)
    assert bad in str(excinfo.value)


def test_the_four_vocabularies_are_not_interchangeable():
    """`draft` is both a case status and a work-product status; `published` is only a case one.
    A single shared check would accept either everywhere, and the mismatch would surface only as
    a filter returning nothing.
    """
    _require_status("published")
    with pytest.raises(ValueError):
        _require_work_product_status("published")

    _require_work_product_status("withdrawn")
    with pytest.raises(ValueError):
        _require_status("withdrawn")


# ---------------------------------------------------------------------------------------------
# Case links must match the case's own scope.
# ---------------------------------------------------------------------------------------------


def test_a_rubric_from_another_scope_is_refused(db_session: Session):
    """A personal case scored against an institutional rubric would publish personal work under
    institutional criteria — the scope boundary exists to stop exactly that."""
    from lms.feedback.repository import create_rubric

    rubric = create_rubric(
        db_session,
        title="Institutional rubric",
        ownership_scope="institutional",
        authoring_actor="user:alice",
    )

    with pytest.raises(ValueError, match="rubric must exist and match"):
        _validate_case_links(
            db_session,
            ownership_scope="personal",
            rubric_id=rubric.id,
            knowledge_node_id=None,
        )


def test_a_missing_rubric_is_refused(db_session: Session):
    with pytest.raises(ValueError, match="rubric must exist"):
        _validate_case_links(
            db_session,
            ownership_scope="personal",
            rubric_id="no-such-rubric",
            knowledge_node_id=None,
        )


def test_a_node_from_another_scope_is_refused(db_session: Session):
    node = create_knowledge_node(
        db_session,
        title="Institutional node",
        knowledge_type="conceptual",
        scope="institutional",
        actor_id="user:alice",
        status="published",
    )

    with pytest.raises(ValueError, match="knowledge node must exist and match"):
        _validate_case_links(
            db_session,
            ownership_scope="personal",
            rubric_id=None,
            knowledge_node_id=node.id,
        )


def test_absent_links_are_allowed(db_session: Session):
    """Both are optional. Requiring them would make a case unable to exist before its rubric."""
    _validate_case_links(
        db_session, ownership_scope="personal", rubric_id=None, knowledge_node_id=None
    )


def test_a_missing_source_reference_is_refused(db_session: Session):
    with pytest.raises(ValueError, match="source reference was not found"):
        _require_source_reference(db_session, "no-such-reference")


def test_no_source_reference_is_allowed(db_session: Session):
    _require_source_reference(db_session, None)


# ---------------------------------------------------------------------------------------------
# Step ordering.
# ---------------------------------------------------------------------------------------------


def test_step_orders_must_be_positive():
    """Step 0 sorts before step 1 and reads as a step the author did not write."""
    with pytest.raises(ValueError, match="must be positive"):
        _require_unique_orders([{"step_order": 0}])
    with pytest.raises(ValueError, match="must be positive"):
        _require_unique_orders([{"step_order": -1}])


def test_step_orders_must_be_unique():
    """Two steps at order 2 render in an arbitrary order, which changes between runs."""
    with pytest.raises(ValueError, match="must be unique"):
        _require_unique_orders([{"step_order": 1}, {"step_order": 2}, {"step_order": 2}])


def test_valid_orders_need_not_be_contiguous():
    """Gaps are fine — an author who deletes step 2 should not have to renumber."""
    _require_unique_orders([{"step_order": 1}, {"step_order": 5}, {"step_order": 9}])


def test_no_steps_is_allowed():
    _require_unique_orders([])


# ---------------------------------------------------------------------------------------------
# Work product creation guards.
# ---------------------------------------------------------------------------------------------


def test_a_work_product_with_neither_body_nor_artifact_is_refused(db_session: Session):
    """An empty work product cannot be scored and cannot be revised; it is a row that exists only
    to look like progress."""
    case = _case(db_session)

    with pytest.raises(ValueError, match="body or an artifact_ref"):
        create_work_product(
            db_session,
            case_id=case.id,
            learner_id="learner-1",
            submission_type="memo",
        )


@pytest.mark.parametrize("status", ["scored", "accepted", "revision-requested", "withdrawn"])
def test_a_work_product_cannot_be_created_already_resolved(db_session: Session, status):
    """`scored` on create would fabricate an assessment nobody made. Only `draft` and `submitted`
    are states a learner can start in."""
    case = _case(db_session)

    with pytest.raises(ValueError, match="must be draft or submitted"):
        create_work_product(
            db_session,
            case_id=case.id,
            learner_id="learner-1",
            submission_type="memo",
            body="an answer",
            status=status,
        )


def test_a_work_product_for_an_unknown_case_is_refused(db_session: Session):
    with pytest.raises(ValueError, match="case was not found"):
        create_work_product(
            db_session,
            case_id="no-such-case",
            learner_id="learner-1",
            submission_type="memo",
            body="an answer",
        )


def test_a_step_from_another_case_is_refused(db_session: Session):
    """A work product filed against another case's step would credit the wrong case, and the
    learner's transfer evidence would point at work they did elsewhere."""
    case = _case(
        db_session,
        title="Mine",
        steps=[{"step_order": 1, "title": "Step one", "prompt": "Do the thing"}],
    )
    other = _case(
        db_session,
        title="Theirs",
        steps=[{"step_order": 1, "title": "Step one", "prompt": "Other"}],
    )

    with pytest.raises(ValueError, match="case step must belong"):
        create_work_product(
            db_session,
            case_id=case.id,
            learner_id="learner-1",
            submission_type="memo",
            body="an answer",
            case_step_id=other.steps[0].id,
        )


# ---------------------------------------------------------------------------------------------
# Listing filters.
# ---------------------------------------------------------------------------------------------


def test_listing_cases_filters_by_knowledge_node(db_session: Session):
    node = create_knowledge_node(
        db_session,
        title="Node",
        knowledge_type="conceptual",
        scope="personal",
        actor_id="user:alice",
        status="published",
    )
    linked = _case(db_session, title="Linked", knowledge_node_id=node.id)
    _case(db_session, title="Unlinked")

    listed = list_cases(db_session, knowledge_node_id=node.id)

    assert [case.id for case in listed] == [linked.id]


def test_listing_cases_without_a_filter_returns_all(db_session: Session):
    _case(db_session, title="One")
    _case(db_session, title="Two")

    assert len(list_cases(db_session)) == 2


def test_listing_work_products_filters_by_status(db_session: Session):
    """A learner's queue shows drafts. A status filter that does not filter puts submitted work
    back in the editing list."""
    case = _case(db_session)
    draft = create_work_product(
        db_session,
        case_id=case.id,
        learner_id="learner-1",
        submission_type="memo",
        body="draft answer",
        status="draft",
    )
    create_work_product(
        db_session,
        case_id=case.id,
        learner_id="learner-1",
        submission_type="memo",
        body="submitted answer",
        status="submitted",
    )

    listed = list_work_products(db_session, case_id=case.id, status="draft")

    assert [product.id for product in listed] == [draft.id]


def test_an_unknown_work_product_status_filter_is_refused(db_session: Session):
    """An empty result and a bad query look identical to the caller."""
    case = _case(db_session)
    with pytest.raises(ValueError, match="unknown work product status"):
        list_work_products(db_session, case_id=case.id, status="pending")


def test_listing_work_products_filters_by_step(db_session: Session):
    """Two work products on the same case differ only by step, which the case filter cannot
    separate."""
    case = _case(
        db_session,
        steps=[
            {"step_order": 1, "title": "First", "prompt": "First"},
            {"step_order": 2, "title": "Second", "prompt": "Second"},
        ],
    )
    first_step, second_step = case.steps[0], case.steps[1]
    on_first = create_work_product(
        db_session,
        case_id=case.id,
        learner_id="learner-1",
        submission_type="memo",
        body="first",
        case_step_id=first_step.id,
    )
    create_work_product(
        db_session,
        case_id=case.id,
        learner_id="learner-1",
        submission_type="memo",
        body="second",
        case_step_id=second_step.id,
    )

    listed = list_work_products(db_session, case_id=case.id, case_step_id=first_step.id)

    assert [product.id for product in listed] == [on_first.id]
