"""The learner-identity guards along the capability chain.

Target -> estimate -> gap analysis -> maintenance plan. Every link carries a check that the two
records belong to the SAME learner, and every one of those checks was unreached.

They matter more than an ordinary not-found guard. A missing record raises somewhere; a mismatched
learner does not. A gap analysis built from learner A's estimate against learner B's target
produces a perfectly well-formed plan, stored against a real learner, describing gaps that are not
theirs — and it is a scheduled study plan, so the learner acts on it. Nothing about that failure
looks like a failure.

The listing filters are here for the same reason: a filter that silently does not filter hands one
learner another's plan.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from lms.auth.models import User
from lms.capability.repository import (
    create_capability_target,
    create_gap_analysis,
    create_maintenance_plan,
    list_capability_estimates,
    list_capability_targets,
    list_gap_analyses,
    recompute_capability_estimate,
)
from lms.graphs.repository import create_knowledge_node
from lms.learners.repository import create_learner_for_user


def _learner(session: Session, suffix: str) -> str:
    user = User(
        email=f"chain-{suffix}@example.test",
        username=f"chain-{suffix}",
        display_name="Learner",
    )
    session.add(user)
    session.flush()
    return create_learner_for_user(session, user_id=user.id, display_name="Learner").id


def _node(session: Session, title: str) -> str:
    return create_knowledge_node(
        session,
        title=title,
        knowledge_type="judgment",
        scope="personal",
        actor_id="user:alice",
        status="published",
    ).id


def _target(session: Session, learner_id: str, *, title: str = "Handle a case"):
    return create_capability_target(
        session,
        learner_id=learner_id,
        title=title,
        target_node_ids=[_node(session, title)],
        required_evidence_types=["transfer-case"],
        confidence_threshold=0.8,
    )


# ---------------------------------------------------------------------------------------------
# Not-found guards, so the mismatch tests below are not the only thing standing between a typo
# and a traceback.
# ---------------------------------------------------------------------------------------------


def test_an_estimate_for_an_unknown_target_is_refused(db_session: Session):
    with pytest.raises(ValueError, match="capability target was not found"):
        recompute_capability_estimate(db_session, target_id="no-such-target")


def test_a_gap_analysis_for_an_unknown_estimate_is_refused(db_session: Session):
    with pytest.raises(ValueError, match="capability estimate was not found"):
        create_gap_analysis(db_session, estimate_id="no-such-estimate")


def test_a_maintenance_plan_for_an_unknown_gap_analysis_is_refused(db_session: Session):
    with pytest.raises(ValueError, match="gap analysis was not found"):
        create_maintenance_plan(db_session, gap_analysis_id="no-such-analysis")


# ---------------------------------------------------------------------------------------------
# The learner-identity guards.
# ---------------------------------------------------------------------------------------------


def test_a_gap_analysis_refuses_an_estimate_from_another_learner(db_session: Session):
    """The estimate and the target are looked up independently, so nothing but this check keeps
    them describing the same person. Without it the analysis is well-formed, stored, and wrong.
    """
    mine = _learner(db_session, "mine")
    theirs = _learner(db_session, "theirs")
    my_target = _target(db_session, mine, title="My capability")
    their_target = _target(db_session, theirs, title="Their capability")
    their_estimate = recompute_capability_estimate(db_session, target_id=their_target.id)

    their_estimate.target_id = my_target.id
    db_session.flush()

    with pytest.raises(ValueError, match="estimate learner must match target learner"):
        create_gap_analysis(db_session, estimate_id=their_estimate.id)


def test_a_maintenance_plan_refuses_a_gap_analysis_from_another_learner(db_session: Session):
    """The last link, and the one a learner actually sees: a maintenance plan becomes scheduled
    study. Built from the wrong analysis it sends someone to revise a topic they never targeted.
    """
    mine = _learner(db_session, "plan-mine")
    theirs = _learner(db_session, "plan-theirs")
    my_target = _target(db_session, mine, title="My capability")
    their_target = _target(db_session, theirs, title="Their capability")
    their_estimate = recompute_capability_estimate(db_session, target_id=their_target.id)
    their_analysis = create_gap_analysis(db_session, estimate_id=their_estimate.id)

    their_analysis.target_id = my_target.id
    db_session.flush()

    with pytest.raises(ValueError, match="gap analysis learner must match capability target"):
        create_maintenance_plan(db_session, gap_analysis_id=their_analysis.id)


def test_the_matching_case_still_works(db_session: Session):
    """The counterweight. A guard that refused everything would pass both tests above."""
    learner_id = _learner(db_session, "matching")
    target = _target(db_session, learner_id)
    estimate = recompute_capability_estimate(db_session, target_id=target.id)
    analysis = create_gap_analysis(db_session, estimate_id=estimate.id)
    plan = create_maintenance_plan(db_session, gap_analysis_id=analysis.id)

    assert estimate.learner_id == learner_id
    assert analysis.learner_id == learner_id
    assert plan.learner_id == learner_id


# ---------------------------------------------------------------------------------------------
# Listing filters, in both directions.
# ---------------------------------------------------------------------------------------------


def test_listing_targets_by_learner_excludes_other_learners(db_session: Session):
    mine = _learner(db_session, "list-mine")
    theirs = _learner(db_session, "list-theirs")
    my_target = _target(db_session, mine, title="Mine")
    _target(db_session, theirs, title="Theirs")

    listed = list_capability_targets(db_session, learner_id=mine)
    assert [target.id for target in listed] == [my_target.id]


def test_listing_targets_by_status_excludes_other_statuses(db_session: Session):
    """`archived` targets are archived so they stop appearing. A status filter that does not
    filter puts them back in front of the learner."""
    from lms.capability.repository import archive_capability_target

    learner_id = _learner(db_session, "list-status")
    active = _target(db_session, learner_id, title="Active")
    archived = _target(db_session, learner_id, title="Archived")
    archive_capability_target(db_session, archived)

    listed = list_capability_targets(db_session, learner_id=learner_id, status="active")
    assert [target.id for target in listed] == [active.id]


def test_an_unknown_status_filter_is_refused_rather_than_matching_nothing(db_session: Session):
    """An empty result and a bad query look identical to the caller."""
    learner_id = _learner(db_session, "list-bad-status")
    with pytest.raises(ValueError, match="unknown capability target status"):
        list_capability_targets(db_session, learner_id=learner_id, status="activ")


def test_listing_estimates_by_learner_excludes_other_learners(db_session: Session):
    mine = _learner(db_session, "est-mine")
    theirs = _learner(db_session, "est-theirs")
    my_estimate = recompute_capability_estimate(
        db_session, target_id=_target(db_session, mine, title="Mine").id
    )
    recompute_capability_estimate(
        db_session, target_id=_target(db_session, theirs, title="Theirs").id
    )

    listed = list_capability_estimates(db_session, learner_id=mine)
    assert [estimate.id for estimate in listed] == [my_estimate.id]


def test_listing_gap_analyses_by_learner_excludes_other_learners(db_session: Session):
    mine = _learner(db_session, "gap-mine")
    theirs = _learner(db_session, "gap-theirs")
    my_analysis = create_gap_analysis(
        db_session,
        estimate_id=recompute_capability_estimate(
            db_session, target_id=_target(db_session, mine, title="Mine").id
        ).id,
    )
    create_gap_analysis(
        db_session,
        estimate_id=recompute_capability_estimate(
            db_session, target_id=_target(db_session, theirs, title="Theirs").id
        ).id,
    )

    listed = list_gap_analyses(db_session, learner_id=mine)
    assert [analysis.id for analysis in listed] == [my_analysis.id]


def test_listing_gap_analyses_by_estimate_narrows_within_one_learner(db_session: Session):
    """Two estimates for the same learner are the case the learner filter cannot separate."""
    learner_id = _learner(db_session, "gap-by-estimate")
    target = _target(db_session, learner_id)
    first = recompute_capability_estimate(db_session, target_id=target.id)
    first_analysis = create_gap_analysis(db_session, estimate_id=first.id)
    second = recompute_capability_estimate(db_session, target_id=target.id)
    create_gap_analysis(db_session, estimate_id=second.id)

    listed = list_gap_analyses(db_session, estimate_id=first.id)
    assert [analysis.id for analysis in listed] == [first_analysis.id]


def test_listing_without_a_filter_returns_every_learner(db_session: Session):
    """The unfiltered branch, so the filters above are shown to be doing the work rather than the
    fixtures happening to hold one record."""
    mine = _learner(db_session, "unfiltered-mine")
    theirs = _learner(db_session, "unfiltered-theirs")
    _target(db_session, mine, title="Mine")
    _target(db_session, theirs, title="Theirs")

    assert len(list_capability_targets(db_session)) == 2
