"""Read-only support and admin inspection surfaces."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from lms import APP_NAME, __version__
from lms.audit.models import AuditLog
from lms.auth.models import User
from lms.auth.repository import LOCAL_DEV_USERNAME
from lms.capability.models import CapabilityEstimate, MaintenancePlan
from lms.db.base import Base
from lms.db.session import get_session
from lms.evidence.models import EvidenceRecord
from lms.feedback.models import FeedbackAction
from lms.learners.models import Learner
from lms.scheduling.models import ReviewQueueItem
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["support-admin-ui"])
SessionDep = Annotated[Session, Depends(get_session)]


@dataclass
class SupportSignal:
    """A reasoned support signal for one learner."""

    learner_id: str
    learner_name: str
    reasons: list[str] = field(default_factory=list)
    uncertainty: list[str] = field(default_factory=list)
    sensitivity: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)


@router.get("/app/support", response_class=HTMLResponse)
def support_dashboard_route(session: SessionDep) -> str:
    """Return the read-only support/testing dashboard."""
    signals = _support_signals(session)
    content = (
        _support_signal_list(signals)
        if signals
        else empty_state(
            "No support signals",
            "No learner currently has open feedback, stale review, low-confidence estimate, "
            "or maintenance-plan blocker signals.",
        )
    )
    return render_page(
        "Support",
        f"""
        <main class="surface support-surface">
          <header>
            <p class="eyebrow">Testing support view</p>
            <h1>Support</h1>
            <p>Read-only learner support signals grouped by reason and uncertainty.</p>
          </header>
          {content}
        </main>
        """,
        active_path="/app/support",
    )


@router.get("/app/admin", response_class=HTMLResponse)
def admin_dashboard_route(request: Request, session: SessionDep) -> str:
    """Return the read-only admin inspection dashboard.

    Local user management is surfaced by ``src/lms/auth/api.py`` (the local
    identity routes). When those routes are disabled the Users section and the
    create-user link are hidden so the admin surface never advertises identity
    management that is not actually mounted.
    """
    local_identity = bool(getattr(request.app.state, "enable_local_identity_routes", False))
    audit_events = session.scalars(
        select(AuditLog).order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(25)
    ).all()
    mapped_table_count = len(Base.metadata.tables)
    return render_page(
        "Admin",
        f"""
        <main class="surface admin-surface">
          <header>
            <p class="eyebrow">Local admin inspection</p>
            <h1>Admin</h1>
            <p>User, audit, permission-label, and health state for the local prototype.</p>
          </header>
          {_users_section(session, local_identity)}
          <section aria-labelledby="audit-heading">
            <h2 id="audit-heading">Audit events</h2>
            {_audit_event_list(audit_events)}
          </section>
          <section aria-labelledby="state-heading">
            <h2 id="state-heading">Health and route state</h2>
            <ul>
              <li>Health: ok for {escape(APP_NAME)} {escape(__version__)}</li>
              <li>Auth mode: local identity routes are available when enabled.</li>
              <li>Permission labels: personal-scope defaults; no production role editor here.</li>
              <li>Mapped table count: {mapped_table_count}</li>
            </ul>
          </section>
        </main>
        """,
        active_path="/app/admin",
    )


def _support_signals(session: Session) -> list[SupportSignal]:
    signals: dict[str, SupportSignal] = {}

    def signal_for(learner_id: str) -> SupportSignal:
        if learner_id not in signals:
            learner = session.get(Learner, learner_id)
            signals[learner_id] = SupportSignal(
                learner_id=learner_id,
                learner_name=learner.display_name if learner is not None else learner_id,
            )
        return signals[learner_id]

    feedback_actions = session.scalars(
        select(FeedbackAction)
        .where(FeedbackAction.status == "open")
        .order_by(FeedbackAction.created_at.desc(), FeedbackAction.id.desc())
        .limit(100)
    ).all()
    for action in feedback_actions:
        signal = signal_for(action.learner_id)
        signal.reasons.append(f"Open feedback action: {action.title}")
        signal.uncertainty.append("Action status is open; support need is not a ranking.")
        if action.instructions:
            signal.next_actions.append(action.instructions)

    evidence_records = session.scalars(
        select(EvidenceRecord)
        .order_by(EvidenceRecord.created_at.desc(), EvidenceRecord.id.desc())
        .limit(100)
    ).all()
    for record in evidence_records:
        supported = record.support_level != "none" or record.hint_used or record.reference_accessed
        low_confidence = record.confidence_rating is not None and record.confidence_rating <= 2
        low_score = record.normalized_score is not None and record.normalized_score < 0.5
        if supported or low_confidence or low_score:
            signal = signal_for(record.learner_id)
            signal.reasons.append(
                "Evidence suggests review context: "
                f"support={record.support_level}, confidence={record.confidence_rating or 'unknown'}"
            )
            signal.uncertainty.append(
                "Evidence is directional and should be confirmed with learner-facing context."
            )
            if supported:
                signal.sensitivity.append("Support/hint/reference metadata present.")
            signal.next_actions.append(
                "Review the recent evidence and choose a low-stakes next task."
            )

    estimates = session.scalars(
        select(CapabilityEstimate)
        .order_by(CapabilityEstimate.created_at.desc(), CapabilityEstimate.id.desc())
        .limit(100)
    ).all()
    for estimate in estimates:
        if estimate.confidence < 0.6 or estimate.current_score < 0.5:
            signal = signal_for(estimate.learner_id)
            signal.reasons.append(
                f"Capability estimate needs context: score {estimate.current_score:.2f}, "
                f"confidence {estimate.confidence:.2f}"
            )
            signal.uncertainty.append(
                f"Estimate commentary is {estimate.commentary_redaction_class}; avoid labels."
            )
            signal.next_actions.append("Collect another evidence point before changing the plan.")

    maintenance_plans = session.scalars(
        select(MaintenancePlan)
        .where(MaintenancePlan.status == "active")
        .order_by(MaintenancePlan.created_at.desc(), MaintenancePlan.id.desc())
        .limit(100)
    ).all()
    for plan in maintenance_plans:
        blocked_steps = [
            str(step.get("title") or step.get("description") or "Maintenance step")
            for step in plan.plan_steps
            if str(step.get("status", "")).lower() in {"blocked", "waiting"}
        ]
        if blocked_steps:
            signal = signal_for(plan.learner_id)
            signal.reasons.append("Maintenance-plan blocker: " + "; ".join(blocked_steps))
            signal.uncertainty.append("Plan status is a support cue, not a learner label.")
            signal.next_actions.append("Unblock the smallest maintenance step first.")

    review_items = session.scalars(
        select(ReviewQueueItem)
        .where(ReviewQueueItem.reason_code == "stale")
        .order_by(ReviewQueueItem.created_at.desc(), ReviewQueueItem.id.desc())
        .limit(100)
    ).all()
    for item in review_items:
        signal = signal_for(item.learner_id)
        signal.reasons.append(f"Stale review queue item: {item.reason_explanation}")
        signal.uncertainty.append("Stale review means scheduling needs attention, not ability.")
        signal.next_actions.append("Refresh the review item or mark it intentionally stale.")

    return sorted(signals.values(), key=lambda item: item.learner_name.lower())


def _support_signal_list(signals: list[SupportSignal]) -> str:
    cards: list[str] = []
    for signal in signals:
        cards.append(f"""
            <article class="support-signal">
              <h2>{escape(signal.learner_name)}</h2>
              <p>Learner id: <code>{escape(signal.learner_id)}</code></p>
              <h3>Reasons</h3>
              <ul>{_items(signal.reasons)}</ul>
              <h3>Uncertainty</h3>
              <ul>{_items(signal.uncertainty)}</ul>
              <h3>Sensitivity</h3>
              <ul>{_items(signal.sensitivity or ["No extra sensitivity marker recorded."])}</ul>
              <h3>Recommended next action</h3>
              <ul>{_items(signal.next_actions or ["Review the learner context before acting."])}</ul>
            </article>
            """)
    return '<section aria-label="Support signals">' + "".join(cards) + "</section>"


def _users_section(session: Session, local_identity: bool) -> str:
    if not local_identity:
        return (
            '<section aria-labelledby="users-heading">'
            '<h2 id="users-heading">Users</h2>'
            + empty_state(
                "Local identity routes disabled",
                "User records and the create-user API are only available when "
                "local identity routes are enabled.",
            )
            + "</section>"
        )
    # Exclude the synthetic ``local-dev`` shortcut account. It is auto-provisioned
    # by require_authenticated_user whenever auth is disabled (local dev / tests),
    # never exists on a deployed instance, and is not a manageable identity — so
    # surfacing it in the admin Users list would be misleading noise.
    users = session.scalars(
        select(User)
        .where(User.username != LOCAL_DEV_USERNAME)
        .order_by(User.created_at.desc(), User.username)
        .limit(100)
    ).all()
    return (
        '<section aria-labelledby="users-heading">'
        '<h2 id="users-heading">Users</h2>'
        '<p><a href="/auth/users">Create user API</a></p>'
        f"{_user_list(users)}"
        "</section>"
    )


def _user_list(users: Sequence[User]) -> str:
    if not users:
        return empty_state("No users", "No local users have been created yet.")
    return (
        "<ul>"
        + "".join(
            f"<li>{escape(user.display_name)} "
            f"(<code>{escape(user.username)}</code>) "
            f"{escape(user.email or 'no email')} "
            f"{'local' if user.is_local else 'external'}</li>"
            for user in users
        )
        + "</ul>"
    )


def _audit_event_list(events: Sequence[AuditLog]) -> str:
    if not events:
        return empty_state("No audit events", "No audited authoring events are recorded yet.")
    return (
        "<ol>"
        + "".join(
            f"<li>{escape(event.action)} {escape(event.entity_type)} "
            f"<code>{escape(event.entity_id)}</code> by {escape(event.actor_id)} "
            f"via {escape(event.source_subsystem)}</li>"
            for event in events
        )
        + "</ol>"
    )


def _items(values: list[str]) -> str:
    return "".join(f"<li>{escape(value)}</li>" for value in values)
