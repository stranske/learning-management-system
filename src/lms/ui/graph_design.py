"""Author graph design HTML surface."""

from __future__ import annotations

from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.evidence.models import EvidenceRecord
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.graphs.repository import (
    create_knowledge_edge,
    create_knowledge_node,
    list_knowledge_edges,
    list_knowledge_nodes,
    update_knowledge_edge,
    update_knowledge_node,
)
from lms.llm.proposals import LLMProposal
from lms.mastery.service import mastery_estimates_for_learner
from lms.ui.shell import render_page

router = APIRouter(tags=["graph-design-ui"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/app/author/graph", response_class=HTMLResponse)
def graph_design_route(
    session: SessionDep,
    scope: Annotated[str, Query(pattern="^(personal|institutional)$")] = "personal",
    learner_id: Annotated[str | None, Query(min_length=1, max_length=36)] = None,
) -> str:
    """Return a compact authoring graph surface."""
    return _graph_surface(session=session, scope=scope, learner_id=learner_id)


@router.post("/app/author/graph/nodes", response_class=HTMLResponse)
async def create_graph_node_route(request: Request, session: SessionDep) -> str:
    """Create a node from the graph authoring form."""
    form = await _form_data(request)
    scope = _scope(form.get("ownership_scope"))
    try:
        create_knowledge_node(
            session,
            title=form.get("title", "").strip(),
            description=form.get("description") or None,
            knowledge_type=form.get("knowledge_type", "conceptual"),
            scope=scope,
            status=form.get("status", "draft"),
            provenance="manual",
            actor_id="graph-ui",
            source_subsystem="graph-ui",
        )
        session.commit()
        message = "Node saved."
    except ValueError as exc:
        session.rollback()
        message = str(exc)
    return _graph_surface(session=session, scope=scope, message=message)


@router.post("/app/author/graph/edges", response_class=HTMLResponse)
async def create_graph_edge_route(request: Request, session: SessionDep) -> str:
    """Create an edge from the graph authoring form."""
    form = await _form_data(request)
    scope = _scope(form.get("ownership_scope"))
    try:
        create_knowledge_edge(
            session,
            source_node_id=form.get("source_node_id", "").strip(),
            target_node_id=form.get("target_node_id", "").strip(),
            edge_type=form.get("edge_type", "prerequisite"),
            scope=scope,
            target_scope=_scope(form.get("target_scope") or scope),
            is_graph_reference=form.get("is_graph_reference") == "true",
            confidence=_optional_float(form.get("confidence")),
            status=form.get("status", "draft"),
            notes=form.get("notes") or None,
            actor_id="graph-ui",
            source_subsystem="graph-ui",
        )
        session.commit()
        message = "Edge saved."
    except ValueError as exc:
        session.rollback()
        message = str(exc)
    return _graph_surface(session=session, scope=scope, message=message)


@router.post("/app/author/graph/proposals/{proposal_id}/approve", response_class=HTMLResponse)
async def approve_graph_proposal_route(
    proposal_id: str,
    request: Request,
    session: SessionDep,
) -> str:
    """Publish draft graph artifacts linked to an LLM proposal."""
    form = await _form_data(request)
    scope = _scope(form.get("ownership_scope"))
    message = _set_proposal_status(
        session=session,
        proposal_id=proposal_id,
        node_status="published",
        edge_status="published",
        actor_id="graph-ui",
    )
    session.commit()
    return _graph_surface(session=session, scope=scope, message=message)


@router.post("/app/author/graph/proposals/{proposal_id}/reject", response_class=HTMLResponse)
async def reject_graph_proposal_route(
    proposal_id: str,
    request: Request,
    session: SessionDep,
) -> str:
    """Deprecate draft graph artifacts linked to an LLM proposal."""
    form = await _form_data(request)
    scope = _scope(form.get("ownership_scope"))
    message = _set_proposal_status(
        session=session,
        proposal_id=proposal_id,
        node_status="deprecated",
        edge_status="deprecated",
        actor_id="graph-ui",
    )
    session.commit()
    return _graph_surface(session=session, scope=scope, message=message)


def _graph_surface(
    *,
    session: Session,
    scope: str,
    learner_id: str | None = None,
    message: str | None = None,
) -> str:
    nodes = list_knowledge_nodes(session, scope=scope, limit=200)
    edges = list_knowledge_edges(session, scope=scope, limit=200)
    proposals = _list_graph_proposals(session, scope=scope)
    evidence_counts = _evidence_counts(session)
    mastery_by_node = _mastery_by_node(session, learner_id=learner_id)
    node_options = "".join(
        f'<option value="{escape(node.id)}">{escape(node.title)}</option>' for node in nodes
    )
    node_items = "".join(
        _node_item(node, evidence_counts=evidence_counts, mastery_by_node=mastery_by_node)
        for node in nodes
    )
    node_titles = {node.id: node.title for node in nodes}
    edge_items = "".join(_edge_item(edge, node_titles=node_titles) for edge in edges)
    proposal_items = "".join(_proposal_item(proposal, scope=scope) for proposal in proposals)
    target_scope_options = "".join(
        f'<option value="{escape(candidate)}"'
        f"{' selected' if candidate == scope else ''}>{escape(candidate)}</option>"
        for candidate in ("personal", "institutional")
    )

    return render_page(
        "Graph",
        f"""
        <main class="surface graph-design-surface">
          <header>
            <p class="eyebrow">Author graph</p>
            <h1>Graph design</h1>
            <p>{escape(message or "Edit nodes, test typed edges, and review LLM drafts.")}</p>
          </header>
          <section aria-labelledby="nodes-heading">
            <h2 id="nodes-heading">Nodes</h2>
            {node_items or '<p class="empty-state">No graph nodes yet.</p>'}
            <form method="post" action="/app/author/graph/nodes" data-action="create-node">
              <input type="hidden" name="ownership_scope" value="{escape(scope)}">
              <label>Title <input name="title" required></label>
              <label>Type
                <select name="knowledge_type">
                  <option value="conceptual">conceptual</option>
                  <option value="procedural">procedural</option>
                  <option value="judgment">judgment</option>
                  <option value="factual">factual</option>
                </select>
              </label>
              <label>Status
                <select name="status">
                  <option value="draft">draft</option>
                  <option value="published">published</option>
                </select>
              </label>
              <label>Description <textarea name="description" rows="3"></textarea></label>
              <button type="submit">Save node</button>
            </form>
          </section>
          <section aria-labelledby="edges-heading">
            <h2 id="edges-heading">Adjacency</h2>
            {edge_items or '<p class="empty-state">No graph edges yet.</p>'}
            <form method="post" action="/app/author/graph/edges" data-action="create-edge">
              <input type="hidden" name="ownership_scope" value="{escape(scope)}">
              <label>Source <select name="source_node_id">{node_options}</select></label>
              <label>Target <select name="target_node_id">{node_options}</select></label>
              <label>Type
                <select name="edge_type">
                  <option value="prerequisite">prerequisite</option>
                  <option value="transfer-context">transfer-context</option>
                  <option value="supports-competency">supports-competency</option>
                  <option value="analogy">analogy</option>
                </select>
              </label>
              <label>Target scope
                <select name="target_scope">
                  {target_scope_options}
                </select>
              </label>
              <label>Confidence <input name="confidence" inputmode="decimal" placeholder="0.0-1.0"></label>
              <label class="check"><input type="checkbox" name="is_graph_reference" value="true"> graph-reference</label>
              <button type="submit">Save edge</button>
            </form>
          </section>
          <section aria-labelledby="proposals-heading">
            <h2 id="proposals-heading">LLM proposals</h2>
            {proposal_items or '<p class="empty-state">No proposal drafts pending human approval.</p>'}
          </section>
        </main>
        """,
        active_path="/app/author/graph",
    )


def _node_item(
    node: KnowledgeNode,
    *,
    evidence_counts: dict[str, int],
    mastery_by_node: dict[str, dict[str, object]],
) -> str:
    mastery = mastery_by_node.get(node.id)
    mastery_text = (
        f"mastery {_metric_percent(mastery.get('current_estimate'))}, "
        f"confidence {_metric_percent(mastery.get('confidence'))}"
        if mastery is not None
        else "mastery pending"
    )
    return (
        '<article class="graph-node" data-node-id="{id}">'
        "<h3>{title}</h3>"
        "<p>{kind} · {scope} · {status} · {provenance}</p>"
        "<p>{description}</p>"
        '<p data-signal="evidence-summary">{count} evidence records · {mastery}</p>'
        "</article>"
    ).format(
        id=escape(node.id),
        title=escape(node.title),
        kind=escape(node.knowledge_type),
        scope=escape(node.ownership_scope),
        status=escape(node.status),
        provenance=escape(node.provenance),
        description=escape(node.description or "No description."),
        count=evidence_counts.get(node.id, 0),
        mastery=escape(mastery_text),
    )


def _edge_item(edge: KnowledgeEdge, *, node_titles: dict[str, str]) -> str:
    marker = "graph-reference" if edge.is_graph_reference else "scope-pure"
    return (
        '<article class="graph-edge" data-edge-id="{id}">'
        "<h3>{source} -&gt; {target}</h3>"
        "<p>{edge_type} · {status} · {source_scope} to {target_scope} · {marker}</p>"
        "<p>confidence {confidence}</p>"
        "</article>"
    ).format(
        id=escape(edge.id),
        source=escape(node_titles.get(edge.source_node_id, edge.source_node_id)),
        target=escape(node_titles.get(edge.target_node_id, edge.target_node_id)),
        edge_type=escape(edge.edge_type),
        status=escape(edge.status),
        source_scope=escape(edge.source_scope),
        target_scope=escape(edge.target_scope),
        marker=marker,
        confidence="unscored" if edge.confidence is None else f"{edge.confidence:.2f}",
    )


def _proposal_item(proposal: LLMProposal, *, scope: str) -> str:
    title = (
        proposal.knowledge_node_id
        or proposal.knowledge_edge_id
        or proposal.prompt_id
        or proposal.id
    )
    return (
        f'<article class="graph-proposal" data-proposal-id="{escape(proposal.id)}">'
        f"<h3>Proposal {escape(title)}</h3>"
        f"<p>{escape(proposal.llm_model)} · proposed by {escape(proposal.proposed_by)}</p>"
        f'<form method="post" action="/app/author/graph/proposals/{escape(proposal.id)}/approve">'
        f'<input type="hidden" name="ownership_scope" value="{escape(scope)}">'
        '<button type="submit" data-action="approve-proposal">Approve</button>'
        "</form>"
        f'<form method="post" action="/app/author/graph/proposals/{escape(proposal.id)}/reject">'
        f'<input type="hidden" name="ownership_scope" value="{escape(scope)}">'
        '<button type="submit" data-action="reject-proposal">Reject</button>'
        "</form>"
        "</article>"
    )


def _list_graph_proposals(session: Session, *, scope: str) -> list[LLMProposal]:
    statement = (
        select(LLMProposal)
        .outerjoin(KnowledgeNode, LLMProposal.knowledge_node_id == KnowledgeNode.id)
        .outerjoin(KnowledgeEdge, LLMProposal.knowledge_edge_id == KnowledgeEdge.id)
        .where(
            (KnowledgeNode.ownership_scope == scope)
            | (KnowledgeEdge.source_scope == scope)
            | (KnowledgeEdge.target_scope == scope)
        )
        .where((KnowledgeNode.status == "draft") | (KnowledgeEdge.status == "draft"))
        .order_by(LLMProposal.created_at.desc(), LLMProposal.id)
    )
    return list(session.scalars(statement))


def _evidence_counts(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(EvidenceRecord.knowledge_node_id, func.count(EvidenceRecord.id)).group_by(
            EvidenceRecord.knowledge_node_id
        )
    )
    return {str(node_id): int(count) for node_id, count in rows}


def _mastery_by_node(
    session: Session,
    *,
    learner_id: str | None,
) -> dict[str, dict[str, object]]:
    if learner_id is None:
        return {}
    return {
        str(item["knowledge_node_id"]): item
        for item in mastery_estimates_for_learner(session, learner_id)
    }


def _set_proposal_status(
    *,
    session: Session,
    proposal_id: str,
    node_status: str,
    edge_status: str,
    actor_id: str,
) -> str:
    proposal = session.get(LLMProposal, proposal_id)
    if proposal is None:
        return "Proposal not found."
    if proposal.knowledge_node_id is not None:
        node = session.get(KnowledgeNode, proposal.knowledge_node_id)
        if node is not None:
            update_knowledge_node(session, node, status=node_status, actor_id=actor_id)
    if proposal.knowledge_edge_id is not None:
        edge = session.get(KnowledgeEdge, proposal.knowledge_edge_id)
        if edge is not None:
            update_knowledge_edge(
                session,
                edge,
                status=edge_status,
                actor_id=actor_id,
                source_subsystem="graph-ui",
            )
    return f"Proposal {node_status}."


async def _form_data(request: Request) -> dict[str, str]:
    raw_form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    return {key: values[-1] for key, values in raw_form.items()}


def _scope(value: str | None) -> str:
    return value if value in {"personal", "institutional"} else "personal"


def _metric_percent(value: object) -> str:
    return f"{float(value):.0%}" if isinstance(value, int | float) else "pending"


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)
