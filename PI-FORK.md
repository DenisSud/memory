# The pi fork of mem0

This is a fork of [`mem0ai/mem0`](https://github.com/mem0ai/mem0) that we run as
the memory service. It exists so integration that belongs to the service lives
in the service, instead of being worked around in every client.

- `main` — upstream `main`, kept pristine.
- `pi` — our patch branch, currently based on the upstream tag `v2.2.1` (the
  version the deployment pins).

## What we change

The **System One gates**: a decision model judges memories as they enter the
service and as they leave it. One extra step per ingest, one per search.

- `mem0/configs/systemone.py` — `SystemOneConfig` and `SystemOneGateConfig`.
- `mem0/systemone/` — the System One client and the two gates.
- `mem0/memory/main.py` — `Memory` and `AsyncMemory` build the gates from
  config; `_add_to_vector_store` runs the ingest gate on extracted facts,
  `search` runs the output gate on results.

Both gates ask one `noul` question per item in a single HTTP call, and both
**fail open**: if the call errors or times out, nothing is dropped. A flaky
decision model must never lose or hide memories.

Enabling it is configuration, no code:

```json
{
  "systemone": {
    "base_url": "http://localhost:11434/v1",
    "model": "clef-flash:9b-8k",
    "api_key": "optional",
    "timeout_ms": 5000,
    "ingest": { "enabled": true, "threshold": 0.5 },
    "output": { "enabled": true, "threshold": 0.5 }
  }
}
```

Without a `systemone` block the service behaves exactly like upstream.

## Rebase on a new upstream release

```bash
git fetch upstream --tags
git rebase upstream/v<version> pi
```

The patch is small and touches few files; conflicts should stay local to
`main.py`, where the two hooks are marked by comments.

## Tests

```bash
pytest tests/systemone/    # the gates and their wiring into the pipeline
```

Upstream tests cover the rest; run `pytest tests/memory tests/configs` to check
that the pipeline hooks did not disturb them.
