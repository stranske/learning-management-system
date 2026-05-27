"""Authoring surfaces for goals, knowledge nodes/edges, and prompts.

These routes implement Surface 3 (authoring and content setup) and Surface 4
(knowledge graph studio) from ``docs/product/development-testing-surfaces.md``.
The author can create the trimmed learning-object set -- ``LearningGoal``,
``KnowledgeNode``, ``KnowledgeEdge``, and ``Prompt`` -- directly, reusing the
existing scope-aware repositories. The surfaces deliberately stop at that set
and do not expose course/module/lesson containers.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from lms.db.session import get_session
from lms.graphs.models import (
    EDGE_STATUSES,
    EDGE_TYPES,
    KNOWLEDGE_TYPES,
    NODE_STATUSES,
    OWNERSHIP_SCOPES,
    KnowledgeEdge,
    KnowledgeNode,
)
from lms.graphs.repository import (
    create_knowledge_edge,
    create_knowledge_node,
    list_knowledge_edges,
    list_knowledge_nodes_across_scopes,
)
from lms.learners.models import GOAL_STATUSES, LearningGoal
from lms.learners.repository import create_learning_goal, list_learning_goals_for_learner
from lms.prompts.models import (
    ANSWER_FORMS,
    AUTHORING_METHODS,
    COGNITIVE_ACTIONS,
    DEMAND_LEVELS,
)
from lms.prompts.repository import create_prompt, list_prompts
from lms.sources.models import SourceReference
from lms.sources.repository import list_source_references
from lms.ui.shell import empty_state, render_page

router = APIRouter(tags=["author-ui"])
SessionDep = Annotated[Session, Depends(get_session)]

_AUTHOR_PATH = "/app/author"
_DEFAULT_LEARNER = "learner-1"


@router.get("/app/author", response_class=HTMLResponse)
def author_home_route() -> str:
    """Return the authoring landing page linking the authoring surfaces."""
    body = """
        <main class="surface app-surface author-surface">
          <header>
            <p class="eyebrow">Authoring</p>
            <h1>Author</h1>
            <p>Create the learning-object set directly: goals, knowledge graph,
            and source-cited prompts.</p>
          </header>
          <nav aria-label="Authoring surfaces">
            <ul>
              <li><a href="/app/author/goals">Learning goals</a></li>
              <li><a href="/app/author/knowledge">Knowledge graph</a></li>
              <li><a href="/app/author/prompts">Prompts</a></li>
            </ul>
          </nav>
        </main>
    """
    return render_page("Author", body, active_path=_AUTHOR_PATH)


# ---------------------------------------------------------------------------
# Knowledge graph studio (Surface 4): nodes + edges
# ---------------------------------------------------------------------------


@router.get("/app/author/knowledge", response_class=HTMLResponse)
def author_knowledge_route(session: SessionDep) -> str:
    """Render the knowledge node/edge authoring studio."""
    return _render_knowledge_page(session)


@router.post("/app/author/knowledge/nodes", response_class=HTMLResponse)
async def create_knowledge_node_route(request: Request, session: SessionDep) -> str:
    """Create a knowledge node from the authoring form."""
    form = _form(await request.body())
    try:
        node = create_knowledge_node(
            session,
            title=_scalar(form, "title"),
            knowledge_type=_scalar(form, "knowledge_type"),
            scope=_scalar(form, "scope"),
            actor_id=_scalar(form, "actor_id", "author-1"),
            description=_scalar(form, "description") or None,
            status=_scalar(form, "status", "draft"),
        )
    except ValueError as exc:
        return _render_knowledge_page(session, notice=str(exc), error=True)
    session.commit()
    notice = f"Knowledge node created: {node.id} ({node.title}) [{node.status}]."
    return _render_knowledge_page(session, notice=notice)


@router.post("/app/author/knowledge/edges", response_class=HTMLResponse)
async def create_knowledge_edge_route(request: Request, session: SessionDep) -> str:
    """Create a knowledge edge, rejecting cross-scope edges via graph rules."""
    form = _form(await request.body())
    try:
        edge = create_knowledge_edge(
            session,
            source_node_id=_scalar(form, "source_node_id"),
            target_node_id=_scalar(form, "target_node_id"),
            edge_type=_scalar(form, "edge_type"),
            scope=_scalar(form, "scope"),
            actor_id=_scalar(form, "actor_id", "author-1"),
            target_scope=_scalar(form, "target_scope") or None,
            is_graph_reference=_scalar(form, "is_graph_reference") == "true",
            confidence=_optional_float(_scalar(form, "confidence")),
            status=_scalar(form, "status", "draft"),
        )
    except ValueError as exc:
        return _render_knowledge_page(session, notice=str(exc), error=True)
    session.commit()
    notice = f"Knowledge edge created: {edge.id} ({edge.edge_type})."
    return _render_knowledge_page(session, notice=notice)


def _render_knowledge_page(
    session: Session,
    *,
    notice: str = "",
    error: bool = False,
) -> str:
    nodes = list_knowledge_nodes_across_scopes(session)
    edges = _edges_across_scopes(session)
    node_options = _node_options(nodes)

    if nodes:
        node_items = "".join(
            "<li>"
            f"<strong>{escape(node.title)}</strong> "
            f"<code>{escape(node.id)}</code> "
            f"<small>{escape(node.knowledge_type)} · {escape(node.ownership_scope)} · "
            f"status {escape(node.status)}</small>"
            "</li>"
            for node in nodes
        )
        nodes_block = f"<ul class='node-list'>{node_items}</ul>"
    else:
        nodes_block = empty_state(
            "No knowledge nodes yet",
            "Create a node below to start building the graph.",
        )

    if edges:
        edge_items = "".join(
            "<li>"
            f"<code>{escape(edge.source_node_id)}</code> &rarr; "
            f"<code>{escape(edge.target_node_id)}</code> "
            f"<small>{escape(edge.edge_type)} · {escape(edge.source_scope)}"
            f"&rarr;{escape(edge.target_scope)} · status {escape(edge.status)}"
            f"{' · graph-reference' if edge.is_graph_reference else ''}</small>"
            "</li>"
            for edge in edges
        )
        edges_block = f"<ul class='edge-list'>{edge_items}</ul>"
    else:
        edges_block = empty_state(
            "No knowledge edges yet",
            "Connect two nodes with a prerequisite or competency edge.",
        )

    body = f"""
        <main class="surface app-surface author-surface">
          <header>
            <p class="eyebrow">Authoring · Knowledge graph</p>
            <h1>Knowledge graph studio</h1>
          </header>
          {_notice(notice, error=error)}
          <section aria-labelledby="nodes-heading">
            <h2 id="nodes-heading">Nodes</h2>
            {nodes_block}
            <form class="node-form" method="post" action="/app/author/knowledge/nodes">
              <label for="node-title">Title</label>
              <input id="node-title" name="title" required>
              <label for="node-description">Description</label>
              <textarea id="node-description" name="description" rows="2"></textarea>
              <label for="node-knowledge-type">Knowledge type</label>
              <select id="node-knowledge-type" name="knowledge_type">{_options(KNOWLEDGE_TYPES)}</select>
              <label for="node-scope">Ownership scope</label>
              <select id="node-scope" name="scope">{_options(OWNERSHIP_SCOPES)}</select>
              <label for="node-status">Status</label>
              <select id="node-status" name="status">{_options(NODE_STATUSES)}</select>
              <label for="node-actor">Author</label>
              <input id="node-actor" name="actor_id" value="author-1">
              <button type="submit">Create node</button>
            </form>
          </section>
          <section aria-labelledby="edges-heading">
            <h2 id="edges-heading">Edges</h2>
            {edges_block}
            <form class="edge-form" method="post" action="/app/author/knowledge/edges">
              <label for="edge-source">Source node</label>
              <select id="edge-source" name="source_node_id">{node_options}</select>
              <label for="edge-target">Target node</label>
              <select id="edge-target" name="target_node_id">{node_options}</select>
              <label for="edge-type">Edge type</label>
              <select id="edge-type" name="edge_type">{_options(EDGE_TYPES)}</select>
              <label for="edge-scope">Source scope</label>
              <select id="edge-scope" name="scope">{_options(OWNERSHIP_SCOPES)}</select>
              <label for="edge-target-scope">Target scope</label>
              <select id="edge-target-scope" name="target_scope">{_options(OWNERSHIP_SCOPES)}</select>
              <label class="check">
                <input type="checkbox" name="is_graph_reference" value="true">
                Cross-scope graph reference
              </label>
              <label for="edge-confidence">Confidence (0.0-1.0)</label>
              <input id="edge-confidence" name="confidence" type="text" inputmode="decimal">
              <label for="edge-status">Status</label>
              <select id="edge-status" name="status">{_options(EDGE_STATUSES)}</select>
              <label for="edge-actor">Author</label>
              <input id="edge-actor" name="actor_id" value="author-1">
              <button type="submit">Create edge</button>
            </form>
          </section>
        </main>
    """
    return render_page("Author · Knowledge", body, active_path=_AUTHOR_PATH)


# ---------------------------------------------------------------------------
# Learning goal editor (Surface 3)
# ---------------------------------------------------------------------------


@router.get("/app/author/goals", response_class=HTMLResponse)
def author_goals_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = _DEFAULT_LEARNER,
) -> str:
    """Render the learning-goal authoring surface for one learner."""
    return _render_goals_page(session, learner_id=learner_id)


@router.post("/app/author/goals", response_class=HTMLResponse)
async def create_goal_route(request: Request, session: SessionDep) -> str:
    """Create a learning goal tied to published target nodes."""
    form = _form(await request.body())
    learner_id = _scalar(form, "learner_id", _DEFAULT_LEARNER)
    try:
        goal = create_learning_goal(
            session,
            learner_id=learner_id,
            title=_scalar(form, "title"),
            knowledge_type=_scalar(form, "knowledge_type"),
            target_node_ids=_multi(form, "target_node_ids"),
            ownership_scope=_scalar(form, "ownership_scope"),
            status=_scalar(form, "status", "active"),
        )
    except ValueError as exc:
        return _render_goals_page(session, learner_id=learner_id, notice=str(exc), error=True)
    session.commit()
    notice = f"Learning goal created: {goal.id} ({goal.title})."
    return _render_goals_page(session, learner_id=learner_id, notice=notice)


def _render_goals_page(
    session: Session,
    *,
    learner_id: str,
    notice: str = "",
    error: bool = False,
) -> str:
    goals = list_learning_goals_for_learner(session, learner_id=learner_id)
    published_nodes = [
        node for node in list_knowledge_nodes_across_scopes(session) if node.status == "published"
    ]

    if goals:
        goal_items = "".join(
            "<li>"
            f"<strong>{escape(goal.title)}</strong> <code>{escape(goal.id)}</code> "
            f"<small>{escape(goal.knowledge_type)} · {escape(goal.ownership_scope)} · "
            f"status {escape(goal.status)} · {len(goal.target_nodes)} target node(s)</small>"
            "</li>"
            for goal in goals
        )
        goals_block = f"<ul class='goal-list'>{goal_items}</ul>"
    else:
        goals_block = empty_state(
            "No learning goals yet",
            "Create a goal targeting one or more published knowledge nodes.",
        )

    if published_nodes:
        target_block = f"<select id='goal-targets' name='target_node_ids' multiple required>{_node_options(published_nodes)}</select>"
    else:
        target_block = empty_state(
            "No published nodes available",
            "Publish a knowledge node before linking it to a goal.",
        )

    body = f"""
        <main class="surface app-surface author-surface">
          <header>
            <p class="eyebrow">Authoring · Goals</p>
            <h1>Learning goals</h1>
            <p>Learner <code>{escape(learner_id)}</code></p>
          </header>
          {_notice(notice, error=error)}
          <section aria-labelledby="goals-heading">
            <h2 id="goals-heading">Goals</h2>
            {goals_block}
          </section>
          <section aria-labelledby="goal-form-heading">
            <h2 id="goal-form-heading">Create goal</h2>
            <form class="goal-form" method="post" action="/app/author/goals">
              <input type="hidden" name="learner_id" value="{escape(learner_id)}">
              <label for="goal-title">Title</label>
              <input id="goal-title" name="title" required>
              <label for="goal-knowledge-type">Knowledge type</label>
              <select id="goal-knowledge-type" name="knowledge_type">{_options(KNOWLEDGE_TYPES)}</select>
              <label for="goal-scope">Ownership scope</label>
              <select id="goal-scope" name="ownership_scope">{_options(OWNERSHIP_SCOPES)}</select>
              <label for="goal-status">Status</label>
              <select id="goal-status" name="status">{_options(GOAL_STATUSES)}</select>
              <label for="goal-targets">Target nodes (published)</label>
              {target_block}
              <button type="submit">Create goal</button>
            </form>
          </section>
        </main>
    """
    return render_page("Author · Goals", body, active_path=_AUTHOR_PATH)


# ---------------------------------------------------------------------------
# Prompt editor (Surface 3)
# ---------------------------------------------------------------------------


@router.get("/app/author/prompts", response_class=HTMLResponse)
def author_prompts_route(
    session: SessionDep,
    learner_id: Annotated[str, Query(min_length=1, max_length=36)] = _DEFAULT_LEARNER,
) -> str:
    """Render the prompt authoring surface with provenance and source drift."""
    return _render_prompts_page(session, learner_id=learner_id)


@router.post("/app/author/prompts", response_class=HTMLResponse)
async def create_prompt_route(request: Request, session: SessionDep) -> str:
    """Create a draft prompt linked to a goal, target node, and sources."""
    form = _form(await request.body())
    learner_id = _scalar(form, "learner_id", _DEFAULT_LEARNER)
    try:
        prompt = create_prompt(
            session,
            target_node_id=_scalar(form, "target_node_id"),
            learning_goal_id=_scalar(form, "learning_goal_id"),
            knowledge_type=_scalar(form, "knowledge_type"),
            intended_cognitive_action=_scalar(form, "intended_cognitive_action"),
            demand_level=_scalar(form, "demand_level"),
            expected_answer_form=_scalar(form, "expected_answer_form"),
            body=_scalar(form, "body"),
            source_reference_ids=_multi(form, "source_reference_ids"),
            authoring_method=_scalar(form, "authoring_method", "human-authored"),
            authoring_actor=_scalar(form, "authoring_actor", "author-1"),
        )
    except ValueError as exc:
        return _render_prompts_page(session, learner_id=learner_id, notice=str(exc), error=True)
    session.commit()
    notice = f"Prompt created: {prompt.id} (status {prompt.status})."
    return _render_prompts_page(session, learner_id=learner_id, notice=notice)


def _render_prompts_page(
    session: Session,
    *,
    learner_id: str,
    notice: str = "",
    error: bool = False,
) -> str:
    prompts = list_prompts(session)
    goals = list_learning_goals_for_learner(session, learner_id=learner_id)
    published_nodes = [
        node for node in list_knowledge_nodes_across_scopes(session) if node.status == "published"
    ]
    sources = list_source_references(session)

    if prompts:
        prompt_items = "".join(
            "<li>"
            f"<code>{escape(prompt.id)}</code> "
            f"<small>{escape(prompt.knowledge_type)} · {escape(prompt.intended_cognitive_action)} · "
            f"{escape(prompt.demand_level)} · {escape(prompt.expected_answer_form)} · "
            f"status {escape(prompt.status)}</small>"
            f"<p class='prompt-provenance'>Provenance: {escape(prompt.authoring_method)}; "
            f"author {escape(prompt.authoring_actor)}; "
            f"reviewer {escape(prompt.reviewing_actor or 'pending review')}.</p>"
            "</li>"
            for prompt in prompts
        )
        prompts_block = f"<ul class='prompt-list'>{prompt_items}</ul>"
    else:
        prompts_block = empty_state(
            "No prompts yet",
            "Author a source-cited prompt against a published node.",
        )

    if sources:
        source_items = "".join(
            "<li>"
            f"<code>{escape(source.id)}</code> {escape(source.stable_locator)} "
            f"<small>drift {escape(source.drift_status)}</small>"
            "</li>"
            for source in sources
        )
        sources_block = f"<ul class='source-list'>{source_items}</ul>"
        source_picker = (
            "<select id='prompt-sources' name='source_reference_ids' multiple required>"
            f"{_source_options(sources)}</select>"
        )
    else:
        sources_block = empty_state(
            "No source references yet",
            "Add a source reference before authoring a prompt.",
        )
        source_picker = sources_block

    goal_picker = (
        f"<select id='prompt-goal' name='learning_goal_id'>{_goal_options(goals)}</select>"
        if goals
        else empty_state("No goals yet", "Create a learning goal before authoring a prompt.")
    )
    node_picker = (
        f"<select id='prompt-node' name='target_node_id'>{_node_options(published_nodes)}</select>"
        if published_nodes
        else empty_state("No published nodes", "Publish a node before authoring a prompt.")
    )

    body = f"""
        <main class="surface app-surface author-surface">
          <header>
            <p class="eyebrow">Authoring · Prompts</p>
            <h1>Prompts</h1>
          </header>
          {_notice(notice, error=error)}
          <section aria-labelledby="prompts-heading">
            <h2 id="prompts-heading">Prompts</h2>
            {prompts_block}
          </section>
          <section aria-labelledby="sources-heading">
            <h2 id="sources-heading">Source references</h2>
            {sources_block}
          </section>
          <section aria-labelledby="prompt-form-heading">
            <h2 id="prompt-form-heading">Create prompt</h2>
            <form class="prompt-form" method="post" action="/app/author/prompts">
              <input type="hidden" name="learner_id" value="{escape(learner_id)}">
              <label for="prompt-goal">Learning goal</label>
              {goal_picker}
              <label for="prompt-node">Target node (published)</label>
              {node_picker}
              <label for="prompt-knowledge-type">Knowledge type</label>
              <select id="prompt-knowledge-type" name="knowledge_type">{_options(KNOWLEDGE_TYPES)}</select>
              <label for="prompt-action">Intended cognitive action</label>
              <select id="prompt-action" name="intended_cognitive_action">{_options(COGNITIVE_ACTIONS)}</select>
              <label for="prompt-demand">Demand level</label>
              <select id="prompt-demand" name="demand_level">{_options(DEMAND_LEVELS)}</select>
              <label for="prompt-answer-form">Expected answer form</label>
              <select id="prompt-answer-form" name="expected_answer_form">{_options(ANSWER_FORMS)}</select>
              <label for="prompt-method">Authoring method</label>
              <select id="prompt-method" name="authoring_method">{_options(AUTHORING_METHODS)}</select>
              <label for="prompt-actor">Author</label>
              <input id="prompt-actor" name="authoring_actor" value="author-1">
              <label for="prompt-sources">Source references</label>
              {source_picker}
              <label for="prompt-body">Prompt wording</label>
              <textarea id="prompt-body" name="body" rows="4" required></textarea>
              <button type="submit">Create prompt</button>
            </form>
          </section>
        </main>
    """
    return render_page("Author · Prompts", body, active_path=_AUTHOR_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _form(body: bytes) -> dict[str, list[str]]:
    return parse_qs(body.decode(), keep_blank_values=True)


def _scalar(form: dict[str, list[str]], key: str, default: str = "") -> str:
    values = form.get(key)
    return values[-1] if values else default


def _multi(form: dict[str, list[str]], key: str) -> list[str]:
    out: list[str] = []
    for value in form.get(key, []):
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


def _optional_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    return float(value)


def _options(values: Iterable[str], selected: str | None = None) -> str:
    return "".join(
        f'<option value="{escape(value)}"'
        f"{' selected' if value == selected else ''}>{escape(value)}</option>"
        for value in values
    )


def _node_options(nodes: Sequence[KnowledgeNode]) -> str:
    return "".join(
        f'<option value="{escape(node.id)}">'
        f"{escape(node.title)} [{escape(node.ownership_scope)}/{escape(node.status)}]"
        "</option>"
        for node in nodes
    )


def _goal_options(goals: Sequence[LearningGoal]) -> str:
    return "".join(
        f'<option value="{escape(goal.id)}">{escape(goal.title)} [{escape(goal.ownership_scope)}]</option>'
        for goal in goals
    )


def _source_options(sources: Sequence[SourceReference]) -> str:
    return "".join(
        f'<option value="{escape(source.id)}">{escape(source.stable_locator)}</option>'
        for source in sources
    )


def _edges_across_scopes(session: Session) -> list[KnowledgeEdge]:
    edges: list[KnowledgeEdge] = []
    seen: set[str] = set()
    for scope in OWNERSHIP_SCOPES:
        for edge in list_knowledge_edges(session, scope=scope):
            if edge.id not in seen:
                seen.add(edge.id)
                edges.append(edge)
    return edges


def _notice(message: str, *, error: bool = False) -> str:
    if not message:
        return ""
    css = "notice error" if error else "notice success"
    invalid = ' aria-invalid="true"' if error else ""
    return f'<p class="{css}"{invalid} role="status">{escape(message)}</p>'
