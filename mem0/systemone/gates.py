"""The two System One gates: ingest (before storing) and output (before returning).

Each gate judges a batch in a single System One call: one question per item,
against a state that carries every item. Items below the gate's threshold are
dropped; a call that fails keeps the whole batch.

The instructions name the item and the state path it lives at, and the state
keys the items by that name. That phrasing is what makes small local System One
models discriminate: a vague question ("is this relevant?") scores everything
high, while naming the field scores a clear yes or no.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from mem0.configs.systemone import SystemOneConfig
from mem0.systemone.client import SystemOneClient, SystemOneError

logger = logging.getLogger(__name__)

INGEST_QUESTION = (
    "Look at fact {id} (state.facts.{id}). Does it contain durable information worth remembering: "
    "facts about the user, their preferences, environment, projects, decisions, corrections, or lasting "
    "context? Routine chatter, one-off details, requests to the assistant, and secrets are NOT durable."
)
INGEST_CRITERIA = {
    "true": "The fact contains durable information worth remembering.",
    "false": "The fact is routine, ephemeral, a request, or a secret.",
}

OUTPUT_QUESTION = "Is memory {id} relevant to the search query?"
OUTPUT_CRITERIA = {
    "true": "The memory contains information useful as context for the query.",
    "false": "The memory is unrelated to the query.",
}


class SystemOneGates:
    """Applies the configured gates through one System One client."""

    def __init__(self, config: SystemOneConfig):
        self.ingest = config.ingest
        self.output = config.output
        self.client = SystemOneClient(config.base_url, config.model, config.api_key, config.timeout_ms)

    def filter_facts(self, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep the facts that pass the ingest gate."""
        if not self.ingest.enabled or not facts:
            return facts
        ids, state, questions = _ingest_request(facts)
        try:
            probabilities = self.client.ask(state, questions)
        except SystemOneError as e:
            logger.warning(f"Ingest gate failed, keeping all {len(facts)} facts: {e}")
            return facts
        return _keep(facts, ids, probabilities, self.ingest.threshold, "ingest")

    async def filter_facts_async(self, facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Async counterpart of :meth:`filter_facts`."""
        if not self.ingest.enabled or not facts:
            return facts
        ids, state, questions = _ingest_request(facts)
        try:
            probabilities = await self.client.ask_async(state, questions)
        except SystemOneError as e:
            logger.warning(f"Ingest gate failed, keeping all {len(facts)} facts: {e}")
            return facts
        return _keep(facts, ids, probabilities, self.ingest.threshold, "ingest")

    def filter_results(self, query: str, memories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep the search results that pass the output gate."""
        if not self.output.enabled or not memories:
            return memories
        ids, state, questions = _output_request(query, memories)
        try:
            probabilities = self.client.ask(state, questions)
        except SystemOneError as e:
            logger.warning(f"Output gate failed, keeping all {len(memories)} results: {e}")
            return memories
        return _keep(memories, ids, probabilities, self.output.threshold, "output")

    async def filter_results_async(self, query: str, memories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Async counterpart of :meth:`filter_results`."""
        if not self.output.enabled or not memories:
            return memories
        ids, state, questions = _output_request(query, memories)
        try:
            probabilities = await self.client.ask_async(state, questions)
        except SystemOneError as e:
            logger.warning(f"Output gate failed, keeping all {len(memories)} results: {e}")
            return memories
        return _keep(memories, ids, probabilities, self.output.threshold, "output")


def _ingest_request(facts: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
    ids = [f"fact_{i}" for i in range(len(facts))]
    state = {"facts": {item_id: fact.get("text", "") for item_id, fact in zip(ids, facts)}}
    questions = {
        item_id: {"type": "noul", "instructions": INGEST_QUESTION.format(id=item_id), "criteria": INGEST_CRITERIA}
        for item_id in ids
    }
    return ids, state, questions


def _output_request(query: str, memories: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, Any], Dict[str, Any]]:
    ids = [f"memory_{i}" for i in range(len(memories))]
    state = {
        "query": query,
        "memories": {item_id: memory.get("memory", "") for item_id, memory in zip(ids, memories)},
    }
    questions = {
        item_id: {"type": "noul", "instructions": OUTPUT_QUESTION.format(id=item_id), "criteria": OUTPUT_CRITERIA}
        for item_id in ids
    }
    return ids, state, questions


def _keep(
    items: List[Dict[str, Any]],
    ids: List[str],
    probabilities: Dict[str, Optional[float]],
    threshold: float,
    gate: str,
) -> List[Dict[str, Any]]:
    kept = []
    for item, item_id in zip(items, ids):
        probability = probabilities.get(item_id)
        if probability is None or probability >= threshold:
            kept.append(item)
        else:
            logger.debug(f"{gate} gate dropped {item_id} (p={probability:.3f}): {item!r}")
    return kept
