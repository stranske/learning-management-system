"""Pydantic schemas for the prompt authoring API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lms.graphs.schemas import KnowledgeType

CognitiveAction = Literal["recall", "explain", "apply", "analyze", "evaluate", "create"]
DemandLevel = Literal["low", "medium", "high"]
ExpectedAnswerForm = Literal[
    "short-text",
    "long-text",
    "multiple-choice",
    "worked-example",
    "oral-response",
]
PromptStatus = Literal["draft", "in-review", "published", "archived"]
AuthoringMethod = Literal["human-authored", "llm-generated", "imported"]


class PromptCreate(BaseModel):
    """Input for creating a source-grounded prompt."""

    target_node_id: str = Field(min_length=1, max_length=36)
    learning_goal_id: str = Field(min_length=1, max_length=36)
    knowledge_type: KnowledgeType
    intended_cognitive_action: CognitiveAction
    demand_level: DemandLevel
    expected_answer_form: ExpectedAnswerForm
    body: str = Field(min_length=1)
    source_reference_ids: list[str]
    authoring_method: AuthoringMethod
    authoring_actor: str = Field(min_length=1, max_length=255)
    llm_model: str | None = Field(default=None, max_length=120)
    prompt_template_version: str | None = Field(default=None, max_length=120)
    status: PromptStatus | None = None


class PromptVersionCreate(BaseModel):
    """Input for adding a new prompt wording version."""

    body: str = Field(min_length=1)
    actor_id: str = Field(min_length=1, max_length=255)
    knowledge_type: KnowledgeType | None = None
    intended_cognitive_action: CognitiveAction | None = None
    demand_level: DemandLevel | None = None
    expected_answer_form: ExpectedAnswerForm | None = None


class PromptPublish(BaseModel):
    """Input for publishing a reviewed prompt."""

    reviewing_actor: str = Field(min_length=1, max_length=255)
    approval_timestamp: datetime | None = None


class PromptVersionRead(BaseModel):
    """Serializable prompt version."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    prompt_id: str
    version_number: int
    body: str
    created_by: str
    created_at: datetime


class PromptRead(BaseModel):
    """Serializable prompt with provenance and source links."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    target_node_id: str
    learning_goal_id: str
    knowledge_type: str
    intended_cognitive_action: str
    demand_level: str
    expected_answer_form: str
    status: str
    authoring_method: str
    authoring_actor: str
    reviewing_actor: str | None
    approval_timestamp: datetime | None
    llm_model: str | None
    prompt_template_version: str | None
    source_reference_ids: list[str]
    versions: list[PromptVersionRead]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def model_validate_prompt(cls, prompt: object) -> PromptRead:
        """Build a read schema with flattened source-reference ids."""
        return cls.model_validate(_prompt_read_payload(prompt))


def _prompt_read_payload(prompt: Any) -> dict[str, object]:
    prompt_obj = prompt
    return {
        "id": prompt_obj.id,
        "target_node_id": prompt_obj.target_node_id,
        "learning_goal_id": prompt_obj.learning_goal_id,
        "knowledge_type": prompt_obj.knowledge_type,
        "intended_cognitive_action": prompt_obj.intended_cognitive_action,
        "demand_level": prompt_obj.demand_level,
        "expected_answer_form": prompt_obj.expected_answer_form,
        "status": prompt_obj.status,
        "authoring_method": prompt_obj.authoring_method,
        "authoring_actor": prompt_obj.authoring_actor,
        "reviewing_actor": prompt_obj.reviewing_actor,
        "approval_timestamp": prompt_obj.approval_timestamp,
        "llm_model": prompt_obj.llm_model,
        "prompt_template_version": prompt_obj.prompt_template_version,
        "source_reference_ids": [reference.id for reference in prompt_obj.source_references],
        "versions": prompt_obj.versions,
        "created_at": prompt_obj.created_at,
        "updated_at": prompt_obj.updated_at,
    }
