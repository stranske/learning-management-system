"""Learner transfer-case surface.

This surface closes the learner side of the transfer-evidence loop: published
case shells become learner tasks, submitted work products can be scored into
transfer evidence, and the capability surface can point learners here when a
target needs independent transfer evidence.
"""

from __future__ import annotations

from html import escape
from typing import Annotated, cast
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from lms.auth.login import require_authenticated_user
from lms.auth.models import User
from lms.cases.models import (
    WORK_PRODUCT_SUBMISSION_TYPES,
    Case,
    CaseStep,
    EvidencePacket,
    WorkProduct,
)
from lms.cases.repository import create_work_product, get_case, list_cases, list_work_products
from lms.cases.schemas import WorkProductCreate, WorkProductSubmissionType
from lms.db.session import get_session
from lms.feedback.models import RubricScore
from lms.graphs.models import KnowledgeNode
from lms.learners.repository import list_learners_for_user
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["learner-ui"])
SessionDep = Annotated[Session, Depends(get_session)]
CurrentUserDep = Annotated[User, Depends(require_authenticated_user)]

CASES_PATH = "/app/learner/cases"
DEFAULT_LOCAL_LEARNER_ID = "learner-1"


@router.get(CASES_PATH, response_class=HTMLResponse)
def learner_cases_route(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> str:
    """Return published transfer cases available to the learner."""
    learner_id = _learner_id_for_user(session=session, current_user=current_user)
    return _case_list_surface(session=session, learner_id=learner_id)


@router.get(f"{CASES_PATH}/{{case_id}}", response_class=HTMLResponse)
def learner_case_detail_route(
    case_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> str:
    """Return one published transfer case with the work-product form."""
    learner_id = _learner_id_for_user(session=session, current_user=current_user)
    return _case_detail_surface(
        session=session,
        learner_id=learner_id,
        case_id=case_id,
        notice=None,
        error=None,
    )


@router.post(f"{CASES_PATH}/{{case_id}}/work-products", response_class=HTMLResponse)
async def submit_work_product_route(
    case_id: str,
    request: Request,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> str:
    """Record a learner work product for a published transfer case."""
    form = _read_form((await request.body()).decode())
    learner_id = _learner_id_for_user(session=session, current_user=current_user)
    case = get_case(session, case_id)
    if case is None or case.status != "published":
        return _case_not_found_page()

    try:
        payload = WorkProductCreate(
            learner_id=learner_id,
            submission_type=_submission_type(form.get("submission_type")),
            case_step_id=_optional_text(form.get("case_step_id")),
            rubric_id=_optional_text(form.get("rubric_id")),
            prompt_id=_optional_text(form.get("prompt_id")),
            body=_optional_text(form.get("body")),
            artifact_ref=_optional_text(form.get("artifact_ref")),
        )
        work_product = create_work_product(
            session,
            case_id=case_id,
            learner_id=payload.learner_id,
            submission_type=payload.submission_type,
            case_step_id=payload.case_step_id,
            rubric_id=payload.rubric_id,
            prompt_id=payload.prompt_id,
            body=payload.body,
            artifact_ref=payload.artifact_ref,
        )
        session.commit()
        session.refresh(work_product)
    except (ValidationError, ValueError) as exc:
        session.rollback()
        return _case_detail_surface(
            session=session,
            learner_id=learner_id,
            case_id=case_id,
            notice=None,
            error=_form_error(exc),
        )

    return _case_detail_surface(
        session=session,
        learner_id=learner_id,
        case_id=case_id,
        notice="Work product submitted. It can now be scored for transfer evidence.",
        error=None,
    )


def _case_list_surface(*, session: Session, learner_id: str) -> str:
    cases = list_cases(session, ownership_scope="personal", status="published", limit=100)
    if cases:
        body = (
            "<ul class='case-list'>"
            + "".join(_case_card(session, case=case, learner_id=learner_id) for case in cases)
            + "</ul>"
        )
    else:
        body = empty_state(
            "No transfer cases available",
            "Published personal transfer cases will appear here when an author adds them.",
        )
    return _page(
        title="Transfer Cases",
        eyebrow="Transfer evidence",
        heading="Transfer cases",
        body=f"""
        <p class="scope-note">Personal scope only. These cases create current transfer evidence after scoring.</p>
        <section aria-labelledby="case-list-heading">
          <h2 id="case-list-heading">Available cases</h2>
          {body}
        </section>
        """,
    )


def _case_detail_surface(
    *,
    session: Session,
    learner_id: str,
    case_id: str,
    notice: str | None,
    error: str | None,
) -> str:
    case = get_case(session, case_id)
    if case is None or case.status != "published":
        return _case_not_found_page()
    latest = _latest_work_product(session, case_id=case.id, learner_id=learner_id)
    return _page(
        title="Transfer Case",
        eyebrow="Transfer evidence",
        heading=case.title,
        body=f"""
        {_notice_block(notice)}
        {_error_notice(error)}
        <p class="scope-note">Personal scope only. A scored work product adds current transfer evidence for this case.</p>
        {_case_summary_block(session, case)}
        {_steps_block(case.steps)}
        {_evidence_packets_block(case.evidence_packets)}
        {_submission_status_block(session, latest)}
        {_work_product_form(case=case, latest=latest)}
        <p class="back-link"><a href="{CASES_PATH}">Back to transfer cases</a></p>
        """,
    )


def _case_card(session: Session, *, case: Case, learner_id: str) -> str:
    latest = _latest_work_product(session, case_id=case.id, learner_id=learner_id)
    status = _work_product_status_line(session, latest)
    href = _case_url(case_id=case.id)
    node_label = _node_label(session, case.knowledge_node_id)
    return (
        "<li class='case-item'>"
        f"<a href='{href}'><strong>{escape(case.title)}</strong></a>"
        f"<span>{escape(case.description or 'No description provided.')}</span>"
        f"<small>Node: {node_label}; steps {len(case.steps)}; evidence packets {len(case.evidence_packets)}</small>"
        f"<small>{status}</small>"
        "</li>"
    )


def _case_summary_block(session: Session, case: Case) -> str:
    rubric_line = case.rubric_id or "not linked yet"
    return f"""
        <section aria-labelledby="case-summary-heading" class="case-summary">
          <h2 id="case-summary-heading">Case context</h2>
          <p>{escape(case.description or "No description provided.")}</p>
          <p>Knowledge node: {_node_label(session, case.knowledge_node_id)}</p>
          <p>Rubric: <strong>{escape(rubric_line)}</strong></p>
        </section>
    """


def _steps_block(steps: list[CaseStep]) -> str:
    if not steps:
        return empty_state(
            "No case steps yet",
            "This case is published but does not have a step attached yet.",
        )
    items = "".join(_step_item(step) for step in steps)
    return f"""
        <section aria-labelledby="case-steps-heading">
          <h2 id="case-steps-heading">Case steps</h2>
          <ol class="case-steps">{items}</ol>
        </section>
    """


def _step_item(step: CaseStep) -> str:
    expected = (
        f"<p>Expected work product: {escape(step.expected_work_product)}</p>"
        if step.expected_work_product
        else ""
    )
    decisions = "".join(
        "<li>"
        f"<strong>{escape(point.title)}</strong>"
        f"<span>{escape(point.prompt)}</span>"
        f"<small>Decision type: {escape(point.decision_type)}</small>"
        "</li>"
        for point in step.decision_points
    )
    decision_block = (
        f"<ul class='decision-points'>{decisions}</ul>"
        if decisions
        else "<p>No decision points attached to this step.</p>"
    )
    return (
        "<li class='case-step'>"
        f"<h3>{escape(step.title)}</h3>"
        f"<p>{escape(step.prompt)}</p>"
        f"{expected}"
        f"{decision_block}"
        "</li>"
    )


def _evidence_packets_block(packets: list[EvidencePacket]) -> str:
    if not packets:
        return empty_state(
            "No evidence packets yet",
            "Evidence packets attached to this case will appear before submission.",
        )
    items = "".join(
        "<li>"
        f"<strong>{escape(packet.title)}</strong>"
        f"<span>{escape(packet.summary or 'No packet summary provided.')}</span>"
        f"<small>Source reference: {escape(packet.source_reference_id or 'none')}</small>"
        "</li>"
        for packet in packets
    )
    return f"""
        <section aria-labelledby="case-evidence-heading" class="source-panel">
          <h2 id="case-evidence-heading">Evidence packets</h2>
          <ul>{items}</ul>
        </section>
    """


def _submission_status_block(session: Session, work_product: WorkProduct | None) -> str:
    if work_product is None:
        return f"""
        <section aria-labelledby="submission-status-heading">
          <h2 id="submission-status-heading">Your work product</h2>
          {empty_state("No work product submitted yet", "Submit a rationale, memo, or artifact reference when you are ready for scoring.")}
        </section>
        """
    body = work_product.body or work_product.artifact_ref or ""
    return f"""
        <section aria-labelledby="submission-status-heading" class="case-submission-status">
          <h2 id="submission-status-heading">Your latest work product</h2>
          <p>Status: <strong>{escape(work_product.status)}</strong></p>
          <p>{escape(body)}</p>
          <p>{_work_product_status_line(session, work_product)}</p>
        </section>
    """


def _work_product_form(*, case: Case, latest: WorkProduct | None) -> str:
    if latest is not None and latest.status in {"submitted", "scored"}:
        return f"""
        <section aria-labelledby="submit-work-product-heading">
          <h2 id="submit-work-product-heading">Submit work product</h2>
          <p>{_next_submission_line(latest)}</p>
        </section>
        """
    first_step = case.steps[0] if case.steps else None
    case_step_id = first_step.id if first_step is not None else ""
    rubric_id = case.rubric_id or ""
    return f"""
        <section aria-labelledby="submit-work-product-heading">
          <h2 id="submit-work-product-heading">Submit work product</h2>
          <form method="post" action="{CASES_PATH}/{escape(case.id)}/work-products">
            <input type="hidden" name="case_step_id" value="{escape(case_step_id)}">
            <input type="hidden" name="rubric_id" value="{escape(rubric_id)}">
            <label for="submission_type">Submission type</label>
            <select id="submission_type" name="submission_type">
              <option value="rationale">rationale</option>
              <option value="memo">memo</option>
              <option value="analysis">analysis</option>
              <option value="classification">classification</option>
              <option value="artifact">artifact</option>
              <option value="other">other</option>
            </select>
            <label for="body">Work product</label>
            <textarea id="body" name="body" rows="6"></textarea>
            <label for="artifact_ref">Artifact reference</label>
            <input id="artifact_ref" name="artifact_ref" placeholder="Optional file or URL reference">
            <button type="submit">Submit work product</button>
          </form>
        </section>
    """


def _next_submission_line(work_product: WorkProduct) -> str:
    if work_product.status == "submitted":
        return "Your latest work product is awaiting scoring before another submission is needed."
    return "Transfer evidence has been recorded for your latest scored work product."


def _latest_work_product(session: Session, *, case_id: str, learner_id: str) -> WorkProduct | None:
    products = list_work_products(
        session,
        case_id=case_id,
        learner_id=learner_id,
        limit=1,
    )
    return products[0] if products else None


def _work_product_status_line(session: Session, work_product: WorkProduct | None) -> str:
    if work_product is None:
        return "No work product submitted yet."
    if work_product.status == "scored":
        score_line = _score_line(session, work_product.rubric_score_id)
        return f"Transfer evidence recorded. {score_line}"
    if work_product.status == "submitted":
        return "Submitted; awaiting scoring for transfer evidence."
    if work_product.status == "revision-requested":
        return "Revision requested; submit an updated work product when ready."
    return f"Current work product status: {escape(work_product.status)}."


def _score_line(session: Session, rubric_score_id: str | None) -> str:
    if not rubric_score_id:
        return ""
    score = session.get(RubricScore, rubric_score_id)
    if score is None:
        return ""
    return f"Current score {float(score.normalized_score):.0%}."


def _node_label(session: Session, node_id: str | None) -> str:
    if not node_id:
        return "not linked yet"
    node = session.get(KnowledgeNode, node_id)
    if node is None:
        return escape(node_id)
    return escape(node.title)


def _case_url(*, case_id: str) -> str:
    return f"{CASES_PATH}/{escape(case_id)}"


def _case_not_found_page() -> str:
    return _page(
        title="Transfer Case",
        eyebrow="Transfer evidence",
        heading="Transfer case not available",
        body=empty_state(
            "Transfer case not available",
            "This transfer case is missing or not published. Return to the transfer case list.",
        )
        + f'<p class="back-link"><a href="{CASES_PATH}">Back to transfer cases</a></p>',
    )


def _page(*, title: str, eyebrow: str, heading: str, body: str) -> str:
    return render_page(
        title,
        f"""
        <main class="surface transfer-case-surface">
          <header>
            <p class="eyebrow">{escape(eyebrow)}</p>
            <h1>{escape(heading)}</h1>
          </header>
          {body}
        </main>
        """,
        active_path="/app/learner",
    )


def _read_form(body: str) -> dict[str, str]:
    raw_form = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] for key, values in raw_form.items()}


def _learner_id_for_user(*, session: Session, current_user: User) -> str:
    learners = list_learners_for_user(session, user_id=current_user.id)
    if learners:
        return learners[0].id
    return DEFAULT_LOCAL_LEARNER_ID


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _submission_type(value: str | None) -> WorkProductSubmissionType:
    candidate = value or "rationale"
    if candidate not in WORK_PRODUCT_SUBMISSION_TYPES:
        raise ValueError(f"unknown work product submission type {candidate!r}")
    return cast(WorkProductSubmissionType, candidate)


def _form_error(exc: ValidationError | ValueError) -> str:
    if isinstance(exc, ValueError):
        return str(exc)
    return "Enter a work product body or artifact reference before submitting."


def _notice_block(notice: str | None) -> str:
    if not notice:
        return ""
    return f"<p role='status' class='notice'>{escape(notice)}</p>"


def _error_notice(error: str | None) -> str:
    if not error:
        return ""
    return f"<p role='alert' class='notice'>{escape(error)}</p>"
