"""Contract tests for the author graph design surface."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from lms.evidence.models import EvidenceRecord
from lms.graphs.models import KnowledgeEdge, KnowledgeNode
from lms.graphs.repository import create_knowledge_node
from lms.llm.models import LLMSession
from lms.llm.proposals import LLMProposal


def test_graph_view_edits_nodes_edges_and_scope(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client

    node_response = client.post(
        "/app/author/graph/nodes",
        data={
            "title": "Prerequisite retrieval",
            "description": "Use retrieval before transfer.",
            "knowledge_type": "conceptual",
            "ownership_scope": "personal",
            "status": "published",
            "actor_id": "spoofed-browser-actor",
        },
    )

    assert node_response.status_code == 200
    assert "Node saved." in node_response.text
    assert "Prerequisite retrieval" in node_response.text
    assert "0 evidence records" in node_response.text

    with session_factory() as session:
        source = session.query(KnowledgeNode).filter_by(title="Prerequisite retrieval").one()
        target = create_knowledge_node(
            session,
            title="Transfer problem",
            knowledge_type="procedural",
            scope="personal",
            actor_id="test-author",
            status="published",
        )
        session.add(
            EvidenceRecord(
                learner_id="learner-graph",
                knowledge_node_id=source.id,
                demand_level="medium",
                knowledge_type="conceptual",
                correctness=True,
                support_level="none",
            )
        )
        session.commit()
        source_id = source.id
        target_id = target.id

    edge_response = client.post(
        "/app/author/graph/edges",
        data={
            "source_node_id": source_id,
            "target_node_id": target_id,
            "ownership_scope": "personal",
            "target_scope": "personal",
            "edge_type": "transfer-context",
            "status": "published",
            "confidence": "0.82",
        },
    )

    assert edge_response.status_code == 200
    assert "Edge saved." in edge_response.text
    assert "Prerequisite retrieval" in edge_response.text
    assert "Transfer problem" in edge_response.text
    assert "transfer-context" in edge_response.text
    assert "confidence 0.82" in edge_response.text
    assert "1 evidence records" in edge_response.text

    with session_factory() as session:
        edge = session.query(KnowledgeEdge).filter_by(source_node_id=source_id).one()
        assert edge.target_node_id == target_id
        assert edge.is_graph_reference is False


def test_graph_view_shows_llm_proposals_pending_human_approval(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        node = create_knowledge_node(
            session,
            title="LLM proposed node",
            knowledge_type="judgment",
            scope="personal",
            provenance="llm-proposed",
            actor_id="authoring-assist",
            status="draft",
        )
        llm_session = LLMSession(
            mode="authoring-assist",
            trace_class="evidence-grade",
            provider="openai",
            model="gpt-test",
        )
        session.add(llm_session)
        session.flush()
        proposal = LLMProposal(
            llm_session_id=llm_session.id,
            llm_model="gpt-test",
            proposed_by="authoring-assist",
            knowledge_node_id=node.id,
        )
        session.add(proposal)
        session.commit()
        proposal_id = proposal.id
        node_id = node.id

    response = client.get("/app/author/graph")

    assert response.status_code == 200
    assert "LLM proposals" in response.text
    assert "Proposal" in response.text
    assert "gpt-test" in response.text
    assert 'data-action="approve-proposal"' in response.text
    assert 'data-action="reject-proposal"' in response.text

    approve_response = client.post(
        f"/app/author/graph/proposals/{proposal_id}/approve",
        data={"ownership_scope": "personal", "actor_id": "spoofed-browser-actor"},
    )

    assert approve_response.status_code == 200
    assert "Proposal published." in approve_response.text
    with session_factory() as session:
        approved_node = session.get(KnowledgeNode, node_id)
        assert approved_node is not None
        assert approved_node.status == "published"


def test_graph_view_blocks_cross_scope_normal_edges(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = api_client
    with session_factory() as session:
        personal = create_knowledge_node(
            session,
            title="Personal source",
            knowledge_type="conceptual",
            scope="personal",
            actor_id="test-author",
            status="published",
        )
        institutional = create_knowledge_node(
            session,
            title="Institutional target",
            knowledge_type="conceptual",
            scope="institutional",
            actor_id="test-author",
            status="published",
        )
        session.commit()
        personal_id = personal.id
        institutional_id = institutional.id

    response = client.post(
        "/app/author/graph/edges",
        data={
            "source_node_id": personal_id,
            "target_node_id": institutional_id,
            "ownership_scope": "personal",
            "target_scope": "institutional",
            "edge_type": "prerequisite",
            "status": "draft",
        },
    )

    assert response.status_code == 200
    assert "cross-scope edges require is_graph_reference=True" in response.text


def test_graph_view_has_empty_state(
    api_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api_client

    response = client.get("/app/author/graph")

    assert response.status_code == 200
    assert "No graph nodes yet." in response.text
    assert "No graph edges yet." in response.text
    assert "No proposal drafts pending human approval." in response.text
