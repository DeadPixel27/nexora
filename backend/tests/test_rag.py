"""RAG chunking + in-memory retrieval (no OpenAI)."""

import pytest

from app.services.rag.chunking import chunk_text
from app.services.rag import store as rag_store


@pytest.fixture(autouse=True)
def _reset_rag(monkeypatch):
    rag_store.reset_memory_chunks()
    monkeypatch.setattr(
        "app.persistence.supabase_repository.is_supabase_configured",
        lambda: False,
    )
    yield
    rag_store.reset_memory_chunks()


def test_chunk_text_overlap():
    text = "a" * 500 + " " + "b" * 500
    chunks = chunk_text(
        text, document_id="d1", filename="f.pdf", chunk_size=400, overlap=50
    )
    assert len(chunks) >= 2
    assert chunks[0].chunk_index == 0
    assert chunks[0].document_id == "d1"


def test_memory_match_chunks_orders_by_similarity():
    rag_store.replace_run_chunks(
        run_id="run-1",
        user_id="u1",
        rows=[
            {
                "document_id": "d1",
                "filename": "a.pdf",
                "chunk_index": 0,
                "content": "invoice total is 100",
                "embedding": [1.0, 0.0, 0.0],
            },
            {
                "document_id": "d1",
                "filename": "a.pdf",
                "chunk_index": 1,
                "content": "unrelated weather notes",
                "embedding": [0.0, 1.0, 0.0],
            },
        ],
    )
    matches = rag_store.match_chunks(
        run_id="run-1",
        query_embedding=[0.9, 0.1, 0.0],
        match_count=1,
    )
    assert len(matches) == 1
    assert "invoice" in matches[0]["content"]
