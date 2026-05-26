"""SQLAlchemy model for LLM-generated authoring proposals.

An ``LLMProposal`` row binds a single :class:`LLMSession` to the draft entities
it generated (``KnowledgeNode``, ``KnowledgeEdge``, ``Prompt``). The row makes
the llm_session_id and llm_model traceable from any produced entity and keeps
the trust boundary explicit: proposed entities stay draft/llm-generated until a
human approves them, and the proposal row is the audit anchor for that review.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from lms.auth.models import new_uuid, utc_now
from lms.db.base import Base


class LLMProposal(Base):
    """One LLM-proposed draft bundle awaiting human approval.

    Each proposal corresponds to exactly one :class:`LLMSession`. The optional
    foreign keys record which draft entities were produced by the proposal so a
    reviewer can locate the artifacts and the audit trail from a single row.
    """

    __tablename__ = "llm_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    llm_session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("llm_sessions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        unique=True,
    )
    llm_model: Mapped[str] = mapped_column(String(120), nullable=False)
    proposed_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    knowledge_node_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_nodes.id", ondelete="SET NULL"),
        index=True,
    )
    knowledge_edge_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_edges.id", ondelete="SET NULL"),
        index=True,
    )
    prompt_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("prompts.id", ondelete="SET NULL"),
        index=True,
    )
    source_reference_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("source_references.id", ondelete="SET NULL"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        server_default=func.now(),
        nullable=False,
    )
