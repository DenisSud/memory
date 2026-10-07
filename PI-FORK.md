# The pi fork of mem0

This is a fork of [`mem0ai/mem0`](https://github.com/mem0ai/mem0) that we run as
the memory service. It exists so integration that belongs to the service lives
in the service, instead of being worked around in every client.

`main` is the trunk and the base for every pull request: the upstream tree plus
the patch below. Upstream is **not tracked** — we never rebase, we cherry-pick
the commits we want from a later release.

Tags:

- `v2.2.1-pi1` — upstream v2.2.1 with our first revision on top (the gates).
- `v2.2.1-pi2` — what the deployment runs: `pi1` plus the listing cap raised
  to 10,000; a live deployment should be diffed against this tag.
- `mem0-js-sdk-v<version>` — the JavaScript client's releases, following
  upstream's own per-package convention (`vercel-ai-v3.0.3`).

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

The **listing cap**: `server/main.py` raises `ALL_MEMORIES_LIMIT` from upstream's
1,000 to 10,000 — consumers list the whole store for status counts and
exact-duplicate maintenance, and the store is already past 1,000.

The **JavaScript client**: `sdk/js` is `mem0-js-sdk`, a typed client for the
four service endpoints. Nothing consumes it yet — the Pi extension keeps its own
client until it is switched over. See `sdk/js/README.md`.

## Running it

`deploy/` is this service's own deployment: the compose stack (mem0 + pgvector),
the image, the `/configure` replay and the key provisioning. It builds from this
repo — the package and upstream's `server/`, dashboard excluded — so the service
and its library never drift. Consumers (pi bots, the personal agent) hold a URL,
a key and a `user_id`; nothing scoped server-side. See `deploy/README.md`.

## Take a change from a later upstream release

```bash
git fetch upstream --tags
git log --oneline v2.2.1..v<version> -- <path>   # find the commit
git cherry-pick <sha>
```

The patch is small and touches few files, so a cherry-pick usually applies
cleanly; conflicts stay local to `main.py`, where the two hooks are marked by
comments.

## Tests

```bash
pytest tests/systemone/    # the gates and their wiring into the pipeline
```

Upstream tests cover the rest; run `pytest tests/memory tests/configs` to check
that the pipeline hooks did not disturb them.
