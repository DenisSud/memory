"""Tests that the two gates are wired into the memory pipeline.

The gates themselves are covered in ``test_gates.py``; these tests build a
``Memory`` with mocked collaborators, as the upstream pipeline tests do, and
drive ``add``/``search`` to prove the gates run and filter.
"""

import json
from unittest.mock import MagicMock

import pytest

from mem0.memory import main as memory_main
from mem0.memory.main import Memory
from mem0.systemone.gates import SystemOneGates

EXTRACTION = {"memory": [{"text": "Denis runs NixOS"}, {"text": "Denis said hello"}, {"text": "Denis had lunch"}]}


@pytest.fixture
def pipeline_memory(monkeypatch):
    """A real ``Memory`` whose model, embedder, store and history are mocked."""
    vector_store = MagicMock()
    vector_store.search.return_value = []
    monkeypatch.setattr(memory_main.VectorStoreFactory, "create", MagicMock(return_value=vector_store))
    monkeypatch.setattr(memory_main.LlmFactory, "create", MagicMock())
    monkeypatch.setattr(memory_main.EmbedderFactory, "create", MagicMock())
    monkeypatch.setattr(memory_main, "SQLiteManager", MagicMock())
    monkeypatch.setattr(memory_main, "capture_event", MagicMock())

    memory = Memory()
    memory.db.get_last_messages = MagicMock(return_value=[])
    memory.db.save_messages = MagicMock()
    memory.embedding_model.embed_batch = MagicMock(return_value=[[0.1], [0.2], [0.3]])
    return memory, vector_store


def test_ingest_gate_filters_extracted_facts(pipeline_memory, systemone):
    memory, vector_store = pipeline_memory
    _, gates = systemone(probabilities={"fact_0": 0.9, "fact_1": 0.1, "fact_2": 0.1})
    memory.systemone = gates
    memory.llm.generate_response = MagicMock(return_value=json.dumps(EXTRACTION))

    records = memory._add_to_vector_store(
        messages=[{"role": "user", "content": "I run NixOS"}],
        metadata={},
        filters={"user_id": "u1"},
        infer=True,
    )

    assert [record["memory"] for record in records] == ["Denis runs NixOS"]
    assert len(vector_store.insert.call_args.kwargs["payloads"]) == 1


def test_ingest_gate_stores_nothing_when_all_facts_fail(pipeline_memory, systemone):
    memory, vector_store = pipeline_memory
    _, gates = systemone(probabilities={"fact_0": 0.1, "fact_1": 0.1, "fact_2": 0.1})
    memory.systemone = gates
    memory.llm.generate_response = MagicMock(return_value=json.dumps(EXTRACTION))

    records = memory._add_to_vector_store(
        messages=[{"role": "user", "content": "hello"}],
        metadata={},
        filters={"user_id": "u1"},
        infer=True,
    )

    assert records == []
    vector_store.insert.assert_not_called()


def test_output_gate_filters_search_results(monkeypatch, systemone):
    _, gates = systemone(probabilities={"memory_0": 0.9, "memory_1": 0.1})
    assert isinstance(gates, SystemOneGates)
    memory = Memory.__new__(Memory)
    memory.api_version = "v1.1"
    memory.reranker = None
    memory.systemone = gates
    memory._search_vector_store = MagicMock(
        return_value=[{"id": "a", "memory": "Denis runs NixOS"}, {"id": "b", "memory": "Denis had lunch"}]
    )
    monkeypatch.setattr(memory_main, "capture_event", MagicMock())
    monkeypatch.setattr(memory_main, "display_first_run_notice", MagicMock())

    result = Memory.search(memory, "What OS does Denis run?", filters={"user_id": "u1"})

    assert [item["id"] for item in result["results"]] == ["a"]
