"""Create prompt provenance tables.

Revision ID: 20260525_0007
Revises: 20260525_0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260525_0007"
down_revision = "20260525_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create prompts, prompt versions, and prompt-source links."""
    op.create_table(
        "prompts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_node_id", sa.String(length=36), nullable=False),
        sa.Column("learning_goal_id", sa.String(length=36), nullable=False),
        sa.Column("knowledge_type", sa.String(length=32), nullable=False),
        sa.Column("intended_cognitive_action", sa.String(length=32), nullable=False),
        sa.Column("demand_level", sa.String(length=32), nullable=False),
        sa.Column("expected_answer_form", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("authoring_method", sa.String(length=32), nullable=False),
        sa.Column("authoring_actor", sa.String(length=255), nullable=False),
        sa.Column("reviewing_actor", sa.String(length=255), nullable=True),
        sa.Column("approval_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("llm_model", sa.String(length=120), nullable=True),
        sa.Column("prompt_template_version", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "knowledge_type IN ('factual', 'conceptual', 'procedural', 'judgment', "
            "'metacognitive', 'social', 'compliance')",
            name=op.f("ck_prompts_knowledge_type_valid"),
        ),
        sa.CheckConstraint(
            "intended_cognitive_action IN ('recall', 'explain', 'apply', 'analyze', "
            "'evaluate', 'create')",
            name=op.f("ck_prompts_intended_cognitive_action_valid"),
        ),
        sa.CheckConstraint(
            "demand_level IN ('low', 'medium', 'high')",
            name=op.f("ck_prompts_demand_level_valid"),
        ),
        sa.CheckConstraint(
            "expected_answer_form IN ('short-text', 'long-text', 'multiple-choice', "
            "'worked-example', 'oral-response')",
            name=op.f("ck_prompts_expected_answer_form_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in-review', 'published', 'archived')",
            name=op.f("ck_prompts_status_valid"),
        ),
        sa.CheckConstraint(
            "authoring_method IN ('human-authored', 'llm-generated', 'imported')",
            name=op.f("ck_prompts_authoring_method_valid"),
        ),
        sa.CheckConstraint(
            "status != 'published' OR (reviewing_actor IS NOT NULL AND approval_timestamp IS NOT NULL)",
            name=op.f("ck_prompts_published_prompt_requires_review"),
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id"],
            ["knowledge_nodes.id"],
            name=op.f("fk_prompts_target_node_id_knowledge_nodes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["learning_goal_id"],
            ["learning_goals.id"],
            name=op.f("fk_prompts_learning_goal_id_learning_goals"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompts")),
    )
    op.create_index(op.f("ix_prompts_target_node_id"), "prompts", ["target_node_id"])
    op.create_index(op.f("ix_prompts_learning_goal_id"), "prompts", ["learning_goal_id"])
    op.create_index(op.f("ix_prompts_knowledge_type"), "prompts", ["knowledge_type"])
    op.create_index(op.f("ix_prompts_demand_level"), "prompts", ["demand_level"])
    op.create_index(op.f("ix_prompts_status"), "prompts", ["status"])
    op.create_index(op.f("ix_prompts_authoring_method"), "prompts", ["authoring_method"])

    op.create_table(
        "prompt_source_references",
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("source_reference_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_prompt_source_references_prompt_id_prompts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_reference_id"],
            ["source_references.id"],
            name=op.f("fk_prompt_source_references_source_reference_id"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "prompt_id",
            "source_reference_id",
            name=op.f("pk_prompt_source_references"),
        ),
    )
    op.create_index(
        op.f("ix_prompt_source_references_source_reference_id"),
        "prompt_source_references",
        ["source_reference_id"],
    )

    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("prompt_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name=op.f("ck_prompt_versions_version_number_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["prompt_id"],
            ["prompts.id"],
            name=op.f("fk_prompt_versions_prompt_id_prompts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint(
            "prompt_id",
            "version_number",
            name=op.f("uq_prompt_versions_prompt_id_version_number"),
        ),
    )
    op.create_index(op.f("ix_prompt_versions_prompt_id"), "prompt_versions", ["prompt_id"])


def downgrade() -> None:
    """Drop prompt provenance tables."""
    op.drop_index(op.f("ix_prompt_versions_prompt_id"), table_name="prompt_versions")
    op.drop_table("prompt_versions")
    op.drop_index(
        op.f("ix_prompt_source_references_source_reference_id"),
        table_name="prompt_source_references",
    )
    op.drop_table("prompt_source_references")
    op.drop_index(op.f("ix_prompts_authoring_method"), table_name="prompts")
    op.drop_index(op.f("ix_prompts_status"), table_name="prompts")
    op.drop_index(op.f("ix_prompts_demand_level"), table_name="prompts")
    op.drop_index(op.f("ix_prompts_knowledge_type"), table_name="prompts")
    op.drop_index(op.f("ix_prompts_learning_goal_id"), table_name="prompts")
    op.drop_index(op.f("ix_prompts_target_node_id"), table_name="prompts")
    op.drop_table("prompts")
