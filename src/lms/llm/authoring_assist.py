"""Authoring-assist service that proposes draft KnowledgeNode, KnowledgeEdge,
and Prompt records through the LLM client wrapper.

Proposals are draft-only by design: ``KnowledgeNode`` rows carry
``provenance='llm-proposed'`` and ``status='draft'``; ``Prompt`` rows carry
``authoring_method='llm-generated'`` and ``status='draft'``. A reviewer must
publish each artifact before the scheduler can surface it, which is enforced
by :func:`lms.prompts.repository.require_publishable_prompt`.

Every proposal call routes through :class:`LLMClient.complete` with
``mode='authoring-assist'``, so trace class and cost accounting are recorded on
the :class:`LLMSession` exactly the same way as the formative learner-facing
modes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from lms.audit.repository import record_audit_event
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.graphs.repository import (
    create_knowledge_edge,
    create_knowledge_node,
    get_knowledge_node,
)
from lms.learners.models import LearningGoal
from lms.llm.client import LLMClient
from lms.llm.models import LLMSession
from lms.llm.proposals import LLMProposal
from lms.prompts.models import Prompt
from lms.prompts.repository import create_prompt
from lms.sources.models import SourceReference

PROPOSAL_TEMPLATE_VERSION = "authoring-assist-v1"
PROPOSAL_TRACE_CLASS = "formative"


@dataclass(frozen=True)
class ProposalDraft:
    """Caller-provided draft content for an authoring-assist proposal."""

    related_node_title: str
    related_node_knowledge_type: str
    prompt_body: str
    prompt_knowledge_type: str
    prompt_intended_cognitive_action: str
    prompt_demand_level: str
    prompt_expected_answer_form: str
    related_node_description: str | None = None
    edge_type: str | None = None


@dataclass(frozen=True)
class ProposalResult:
    """Persisted artifacts returned from an authoring-assist proposal."""

    llm_session: LLMSession
    llm_proposal: LLMProposal
    knowledge_node: KnowledgeNode
    prompt: Prompt
    knowledge_edge: KnowledgeEdge | None


def propose_authoring_drafts(
    db_session: Session,
    *,
    client: LLMClient,
    source_reference_id: str,
    target_node_id: str,
    learning_goal_id: str,
    actor_id: str,
    draft: ProposalDraft,
    learner_id: str | None = None,
    provider_name: str | None = None,
) -> ProposalResult:
    """Generate and persist a draft authoring-assist proposal bundle.

    The LLM call exercises the wrapper's source-constraint check using the
    source reference's stable locator. The wrapper enforces budget preflight,
    redaction, and accounting; the service then materializes the produced
    artifacts as draft entities and writes a single :class:`LLMProposal` row
    that ties them to the session.
    """
    source_reference = db_session.get(SourceReference, source_reference_id)
    if source_reference is None:
        raise ValueError(f"source_reference {source_reference_id!r} not found")
    goal = db_session.get(LearningGoal, learning_goal_id)
    if goal is None:
        raise ValueError(f"learning_goal {learning_goal_id!r} not found")
    target_node = get_knowledge_node(db_session, target_node_id, scope=goal.ownership_scope)
    if target_node is None:
        raise ValueError(
            f"target_node {target_node_id!r} not found in scope " f"{goal.ownership_scope!r}"
        )

    prompt_text = _build_provider_prompt(
        source_reference=source_reference,
        target_node=target_node,
        draft=draft,
    )
    response = client.complete(
        mode="authoring-assist",
        prompt=prompt_text,
        trace_class=PROPOSAL_TRACE_CLASS,
        source_constraints=(source_reference.stable_locator,),
        learner_id=learner_id,
        prompt_template_version=PROPOSAL_TEMPLATE_VERSION,
        provider_name=provider_name,
    )
    db_session.add(response.session)
    db_session.flush()

    knowledge_node = create_knowledge_node(
        db_session,
        title=draft.related_node_title,
        description=draft.related_node_description,
        knowledge_type=draft.related_node_knowledge_type,
        scope=goal.ownership_scope,
        actor_id=actor_id,
        status="draft",
        provenance="llm-proposed",
        source_reference_id=source_reference.id,
        source_subsystem="authoring-assist",
    )

    edge: KnowledgeEdge | None = None
    if draft.edge_type is not None:
        edge = create_knowledge_edge(
            db_session,
            source_node_id=knowledge_node.id,
            target_node_id=target_node.id,
            edge_type=draft.edge_type,
            scope=goal.ownership_scope,
            actor_id=actor_id,
            status="draft",
            source_subsystem="authoring-assist",
        )

    prompt = create_prompt(
        db_session,
        target_node_id=target_node.id,
        learning_goal_id=goal.id,
        knowledge_type=draft.prompt_knowledge_type,
        intended_cognitive_action=draft.prompt_intended_cognitive_action,
        demand_level=draft.prompt_demand_level,
        expected_answer_form=draft.prompt_expected_answer_form,
        body=draft.prompt_body,
        source_reference_ids=[source_reference.id],
        authoring_method="llm-generated",
        authoring_actor=actor_id,
        llm_model=response.session.model,
        prompt_template_version=PROPOSAL_TEMPLATE_VERSION,
        source_subsystem="authoring-assist",
    )

    proposal = LLMProposal(
        llm_session_id=response.session.id,
        llm_model=response.session.model,
        proposed_by=actor_id,
        knowledge_node_id=knowledge_node.id,
        knowledge_edge_id=edge.id if edge is not None else None,
        prompt_id=prompt.id,
        source_reference_id=source_reference.id,
    )
    db_session.add(proposal)
    db_session.flush()

    record_audit_event(
        db_session,
        actor_id=actor_id,
        action="propose",
        entity_type="Prompt",
        entity_id=prompt.id,
        source_subsystem="authoring-assist",
        after_summary={
            "llm_proposal_id": proposal.id,
            "llm_session_id": response.session.id,
            "llm_model": response.session.model,
            "knowledge_node_id": knowledge_node.id,
            "knowledge_edge_id": edge.id if edge is not None else None,
            "source_reference_id": source_reference.id,
        },
    )

    return ProposalResult(
        llm_session=response.session,
        llm_proposal=proposal,
        knowledge_node=knowledge_node,
        prompt=prompt,
        knowledge_edge=edge,
    )


def _build_provider_prompt(
    *,
    source_reference: SourceReference,
    target_node: KnowledgeNode,
    draft: ProposalDraft,
) -> str:
    """Render the provider prompt body for an authoring-assist proposal."""
    return "\n".join(
        [
            "Mode: authoring-assist",
            f"Source: {source_reference.stable_locator}",
            f"Source visibility: {source_reference.source_visibility}",
            f"Anchor node: {target_node.title} ({target_node.knowledge_type})",
            f"Proposed related node: {draft.related_node_title}",
            f"Proposed knowledge type: {draft.related_node_knowledge_type}",
            f"Proposed prompt body: {draft.prompt_body}",
            "All proposals must remain draft pending human review.",
        ]
    )
