# mem0 — the pi fork

The self-hosted memory service behind Denis's Pi agents and bots.

This is a fork of [`mem0ai/mem0`](https://github.com/mem0ai/mem0), run as one
deployment: upstream's Python SDK and FastAPI server, our **System One gates**
(a decision model filters memories on ingest and on output), our compose stack,
and a small JavaScript client for the service. `main` is the trunk; upstream is
not tracked, so a change we want from a later release is cherry-picked, never
rebased. The deployment pins the tag `v2.2.1-pi1`.

- [`PI-FORK.md`](PI-FORK.md) — what we changed and why. Read this first.
- [`deploy/README.md`](deploy/README.md) — running the stack.
- [`AGENTS.md`](AGENTS.md) — working on the code.

## Layout

| Path | What it is |
|---|---|
| `mem0/` | Upstream Python SDK plus our patch: `systemone/` (the gates) and the two hook sites in `memory/main.py` |
| `server/` | Upstream's FastAPI REST server, vendored unchanged |
| `deploy/` | The compose stack (server + pgvector + Ollama), image and key provisioning |
| `tests/` | Upstream's SDK tests, plus `tests/systemone/` for the gates |
| `sdk/js/` | `mem0-js-sdk` — the JavaScript client |

The docs site, the dashboard, the integrations, the TypeScript SDK, the CLIs,
`examples/` and the GitHub workflows upstream ships are not here: this fork
never builds them.

## Development

```bash
devenv shell                 # py3.11/3.12, hatch, uv, node, pnpm, ruff, isort
setup                        # create the py3.11 hatch env and install git hooks
check                        # pytest tests/
check-systemone              # the gate tests only
lint                         # ruff check
```

Python requires 3.11 or 3.12 (3.10 is end-of-life).

## Using the service

Any HTTP client works. The service takes `X-API-Key` and scopes everything by
`user_id`:

```bash
curl -sS "$MEM0_URL/memories" -H "X-API-Key: $MEM0_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"messages":[{"role":"user","content":"I run NixOS"}],"user_id":"me"}'

curl -sS "$MEM0_URL/search" -H "X-API-Key: $MEM0_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"query":"what do I run?","filters":{"user_id":"me"}}'
```

From JavaScript, [`sdk/js`](sdk/js/README.md) wraps the same four endpoints:

```ts
import { Mem0Client } from 'mem0-js-sdk';

const mem0 = new Mem0Client({ baseUrl: process.env.MEM0_URL!, apiKey: process.env.MEM0_API_KEY });
await mem0.add([{ role: 'user', content: 'I run NixOS' }], { userId: 'me' });
const memories = await mem0.search('what do I run?', { userId: 'me', topK: 5 });
```

## License

Apache-2.0, as upstream.
