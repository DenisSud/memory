"""Tests for the System One gates (ingest and output).

Each gate is one HTTP call; these tests stand in for the System One endpoint
with httpx.MockTransport and assert both the decision and the request the gate
sends.
"""

import asyncio

import httpx
import pytest

from mem0.configs.systemone import SystemOneConfig, SystemOneGateConfig
from mem0.systemone.client import SystemOneClient, SystemOneError
from mem0.systemone.gates import INGEST_CRITERIA, INGEST_QUESTION, OUTPUT_CRITERIA, OUTPUT_QUESTION

FACTS = [{"text": "Denis runs NixOS"}, {"text": "Denis said hello"}, {"text": "Denis prefers trunk-based work"}]
MEMORIES = [
    {"id": "a", "memory": "Denis runs NixOS", "score": 0.9},
    {"id": "b", "memory": "Denis had lunch", "score": 0.8},
]


def _one_question():
    return {
        "fact_0": {"type": "noul", "instructions": INGEST_QUESTION.format(id="fact_0"), "criteria": INGEST_CRITERIA}
    }


class TestIngestGate:
    def test_drops_facts_below_threshold(self, systemone):
        gateway, gates = systemone(
            probabilities={"fact_0": 0.9, "fact_1": 0.2, "fact_2": 0.7},
            ingest=SystemOneGateConfig(threshold=0.5),
        )

        kept = gates.filter_facts(FACTS)

        assert [fact["text"] for fact in kept] == [FACTS[0]["text"], FACTS[2]["text"]]
        assert len(gateway.requests) == 1
        payload = gateway.requests[0]["payload"]
        assert payload["model"] == "clef-flash:9b-8k"
        assert payload["state"] == {
            "facts": {
                "fact_0": "Denis runs NixOS",
                "fact_1": "Denis said hello",
                "fact_2": "Denis prefers trunk-based work",
            }
        }
        assert payload["questions"]["fact_1"]["type"] == "noul"
        assert payload["questions"]["fact_1"]["criteria"] == INGEST_CRITERIA
        assert payload["questions"]["fact_1"]["instructions"] == INGEST_QUESTION.format(id="fact_1")

    def test_missing_answer_keeps_the_fact(self, systemone):
        # Only question "1" is answered, and it fails the gate; the unanswered
        # fact is kept because a gate must fail open.
        _, gates = systemone(probabilities={"fact_1": 0.1})

        kept = gates.filter_facts(FACTS[:2])

        assert [fact["text"] for fact in kept] == [FACTS[0]["text"]]

    def test_transport_error_keeps_everything(self, systemone):
        _, gates = systemone(transport_error=httpx.ConnectError("no route"))

        assert gates.filter_facts(FACTS) == FACTS

    def test_http_error_keeps_everything(self, systemone):
        _, gates = systemone(status_code=500)

        assert gates.filter_facts(FACTS) == FACTS

    def test_disabled_gate_makes_no_call(self, systemone):
        gateway, gates = systemone(probabilities={"fact_0": 0.0}, ingest=SystemOneGateConfig(enabled=False))

        assert gates.filter_facts(FACTS) == FACTS
        assert gateway.requests == []

    def test_empty_facts_makes_no_call(self, systemone):
        gateway, gates = systemone()

        assert gates.filter_facts([]) == []
        assert gateway.requests == []

    def test_async_gate(self, systemone):
        _, gates = systemone(probabilities={"fact_0": 0.9, "fact_1": 0.2})

        kept = asyncio.run(gates.filter_facts_async(FACTS[:2]))

        assert [fact["text"] for fact in kept] == [FACTS[0]["text"]]


class TestOutputGate:
    def test_drops_results_below_threshold(self, systemone):
        gateway, gates = systemone(probabilities={"memory_0": 0.8, "memory_1": 0.1})

        kept = gates.filter_results("What OS does Denis run?", MEMORIES)

        assert [memory["id"] for memory in kept] == ["a"]
        payload = gateway.requests[0]["payload"]
        assert payload["state"] == {
            "query": "What OS does Denis run?",
            "memories": {"memory_0": "Denis runs NixOS", "memory_1": "Denis had lunch"},
        }
        assert payload["questions"]["memory_0"]["criteria"] == OUTPUT_CRITERIA
        assert payload["questions"]["memory_0"]["instructions"] == OUTPUT_QUESTION.format(id="memory_0")

    def test_transport_error_keeps_everything(self, systemone):
        _, gates = systemone(transport_error=httpx.ReadTimeout("too slow"))

        assert gates.filter_results("anything", MEMORIES) == MEMORIES

    def test_disabled_gate_makes_no_call(self, systemone):
        gateway, gates = systemone(probabilities={"memory_0": 0.0}, output=SystemOneGateConfig(enabled=False))

        assert gates.filter_results("anything", MEMORIES) == MEMORIES
        assert gateway.requests == []

    def test_async_gate(self, systemone):
        _, gates = systemone(probabilities={"memory_0": 0.8, "memory_1": 0.1})

        kept = asyncio.run(gates.filter_results_async("What OS does Denis run?", MEMORIES))

        assert [memory["id"] for memory in kept] == ["a"]


class TestClient:
    def test_url_and_bearer_token(self, systemone):
        gateway, _ = systemone()
        client = SystemOneClient("http://systemone.test/v1/", "clef-flash:9b-8k", api_key="secret")

        client.ask({"facts": {}}, _one_question())

        assert gateway.requests[0]["url"] == "http://systemone.test/v1/systemone"
        assert gateway.requests[0]["authorization"] == "Bearer secret"

    def test_http_error_raises_system_one_error(self, systemone):
        systemone(status_code=503)
        client = SystemOneClient("http://systemone.test/v1", "clef-flash:9b-8k")

        with pytest.raises(SystemOneError):
            client.ask({"facts": {}}, _one_question())

    def test_malformed_answer_is_none(self, systemone):
        gateway = systemone()[0]
        client = SystemOneClient("http://systemone.test/v1", "clef-flash:9b-8k")

        assert client.ask({"facts": {}}, _one_question()) == {"fact_0": None}
        assert len(gateway.requests) == 1


class TestConfig:
    def test_gates_are_enabled_by_default(self):
        config = SystemOneConfig(base_url="http://systemone.test/v1")

        assert config.ingest.enabled is True
        assert config.output.enabled is True
        assert config.ingest.threshold == 0.5
        assert config.timeout_ms == 5000

    def test_unknown_keys_are_rejected(self):
        with pytest.raises(Exception):
            SystemOneConfig(base_url="http://systemone.test/v1", unknown=True)

    def test_threshold_must_be_a_probability(self):
        with pytest.raises(Exception):
            SystemOneConfig(base_url="http://systemone.test/v1", ingest={"threshold": 1.5})

    def test_memory_config_carries_systemone(self):
        from mem0.configs.base import MemoryConfig

        config = MemoryConfig(systemone={"base_url": "http://systemone.test/v1"})

        assert config.systemone.model == "clef-flash:9b-8k"
        assert MemoryConfig().systemone is None
