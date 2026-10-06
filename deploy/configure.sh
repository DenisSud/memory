#!/usr/bin/env bash
# Replay the canonical mem0 configuration. Run after every fresh deploy:
# the overrides live in Postgres and are lost with the database.
#
#   MEM0_ADMIN_API_KEY=... ./configure.sh
#
# Env: MEM0_URL (default http://127.0.0.1:8888), OLLAMA_BASE_URL,
#      MEM0_LLM_MODEL, MEM0_EMBEDDER_MODEL, MEM0_EMBED_DIMS,
#      MEM0_SYSTEMONE_BASE_URL (default OLLAMA_BASE_URL), MEM0_SYSTEMONE_MODEL,
#      MEM0_SYSTEMONE_API_KEY, MEM0_SYSTEMONE_TIMEOUT_MS (default 15000),
#      MEM0_GATE_THRESHOLD, MEM0_INGEST_ENABLED, MEM0_OUTPUT_ENABLED.
#
# Why every field: the LLM must run with reasoning off (thinking consumes the
# token budget on Ollama), the embedder + vector store dims must match the
# embedder model (pgvector table dimensions freeze at first insert), and the
# System One gates are where the service filters memories — one gate on ingest,
# one on output. Both gates fail open, so a stopped decision model degrades
# recall quality instead of breaking it. The timeout is generous because the
# first call after the model unloads pays its load time; with a shorter one that
# first call times out and passes unfiltered.
set -euo pipefail

base="${MEM0_URL:-http://127.0.0.1:8888}"
admin="${MEM0_ADMIN_API_KEY:?MEM0_ADMIN_API_KEY is required}"
ollama="${OLLAMA_BASE_URL:-http://127.0.0.1:11434/v1}"
llm_model="${MEM0_LLM_MODEL:-qwen3.5:4b}"
embedder_model="${MEM0_EMBEDDER_MODEL:-nomic-embed-text-v2-moe}"
dims="${MEM0_EMBED_DIMS:-768}"
gate_base="${MEM0_SYSTEMONE_BASE_URL:-$ollama}"
gate_model="${MEM0_SYSTEMONE_MODEL:-clef-flash:9b-8k}"
gate_key="${MEM0_SYSTEMONE_API_KEY:-}"
gate_timeout="${MEM0_SYSTEMONE_TIMEOUT_MS:-15000}"
gate_threshold="${MEM0_GATE_THRESHOLD:-0.5}"
ingest_enabled="${MEM0_INGEST_ENABLED:-true}"
output_enabled="${MEM0_OUTPUT_ENABLED:-true}"

payload=$(
  cat <<EOF
{
  "version": "v1.1",
  "vector_store": { "provider": "pgvector", "config": { "embedding_model_dims": $dims } },
  "llm": {
    "provider": "openai",
    "config": {
      "model": "$llm_model",
      "openai_base_url": "$ollama",
      "is_reasoning_model": true,
      "reasoning_effort": "none"
    }
  },
  "embedder": {
    "provider": "openai",
    "config": {
      "model": "$embedder_model",
      "openai_base_url": "$ollama",
      "embedding_dims": $dims
    }
  },
  "systemone": {
    "base_url": "$gate_base",
    "model": "$gate_model",
    "api_key": "$gate_key",
    "timeout_ms": $gate_timeout,
    "ingest": { "enabled": $ingest_enabled, "threshold": $gate_threshold },
    "output": { "enabled": $output_enabled, "threshold": $gate_threshold }
  }
}
EOF
)

curl -fsS -X POST "$base/configure" \
  -H "X-API-Key: $admin" -H 'Content-Type: application/json' \
  -d "$payload" >/dev/null
echo "configure: applied (llm=$llm_model, embedder=$embedder_model, dims=$dims)"
echo "configure: gates model=$gate_model threshold=$gate_threshold ingest=$ingest_enabled output=$output_enabled"
curl -fsS "$base/configure" -H "X-API-Key: $admin" | head -c 500
echo
