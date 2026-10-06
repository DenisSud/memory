# The memory service

Self-hosted mem0, run as its own compose project: one server, its own Postgres,
its own URL. Nothing else runs it — pi bots, the personal agent and anything
later reach it over HTTP with a key and a `user_id`.

The library in this repo is what the server installs (see `PI-FORK.md`): it
carries the **System One gates**, the service's memory filtering.

| path | what |
|---|---|
| `compose.yml` | the stack: `mem0` + `db` (pgvector), named `mem0`/`mem0-db` |
| `Dockerfile` | the image: this repo's package + upstream's `server/`, dashboard excluded |
| `configure.sh` | replays the canonical `/configure` overrides after a deploy |
| `provision-keys.sh` | creates the admin account (first run) and consumer keys |

## Run it

```sh
# the repo is private: use a read-only deploy key for this host
git clone ssh://git@git.sudakov.site:2223/DenisSud/mem0.git ~/mem0
# when Forgejo runs on this same host, the public name does not hairpin —
# use its local SSH endpoint instead (and keep it as the remote):
#   git clone ssh://git@127.0.0.1:2223/DenisSud/mem0.git ~/mem0
cd ~/mem0/deploy
# first time and after any data reset (~/mem0/deploy/{pgdata,history} hold the state):
mkdir -p pgdata history
# secrets are piped and exported, never written to a file:
printf '%s\n%s\n' "$MEM0_ADMIN_API_KEY" "$MEM0_JWT_SECRET" | ssh <host> \
  'read -r A && read -r B && cd ~/mem0/deploy && export MEM0_ADMIN_API_KEY="$A" MEM0_JWT_SECRET="$B" && podman-compose up -d --build'
```

Then replay the configuration (overrides live in Postgres and die with it):

```sh
MEM0_URL=https://memory.sudakov.site OLLAMA_BASE_URL=http://<pc>:11434/v1 \
  MEM0_ADMIN_API_KEY=... ./configure.sh
```

Verify: no key → 401, admin key → `/configure` 200, and an add → search →
delete round trip. `pgvector` dims freeze at the first insert — fix the dims
before any memory is stored, not after.

## The gates

The service filters memories itself, through a System One model, in two places
(one extra HTTP call each):

- **ingest** — after extraction, before storing: a fact survives only if the
  model answers that it is durable information; chatter, requests, one-off
  details and secrets are dropped;
- **output** — after the vector search: a memory is returned only if the model
  answers that it bears on the query.

Both gates fail open (an error or timeout keeps everything), ask one `noul`
question per item in a single call, and share the threshold from `/configure`
(`MEM0_GATE_THRESHOLD`, default 0.5). The timeout default is 15 s because the
first call after the model unloads pays its load time, and a shorter one times
out — the request then passes unfiltered. Keep the model warm
(`OLLAMA_KEEP_ALIVE`) if that first call matters. The code is `mem0/systemone/`; the
load-bearing part is the instruction wording in `gates.py`, tuned for small
local System One models — a vague question scores everything high and filters
nothing.

Measured on a local Ollama (`/v1/systemone`), over 5 candidate memories and 8
candidate facts, as the probability gap between items that should pass and items
that should not:

| model | output gate | ingest gate | per call |
|---|---|---|---|
| `nimble:latest` | +0.95 | +0.85 | ~0.6 s |
| `clef-flash:9b-8k` | +0.81 | +0.40 | ~0.3 s |
| `tev1:4b` | +0.55 | −0.14 | ~3 s |

`clef-flash:9b-8k` is the default: it is the fastest of the three and the one we
keep loaded. Its ingest separation is the weakest of the three, so the ingest
gate is the one to watch — raise `MEM0_GATE_THRESHOLD` if trivia slips through.
`nimble:latest` separates best if quality ever matters more than latency. A
hosted jev is the upgrade path: the config is a base URL, a model and an
optional key, nothing else.

## Consumers

Each holds only the base URL, a key, and the `user_id` it writes and reads
under. Nothing is scoped server-side: a consumer key only lacks admin powers
(`/configure`, `/reset`, unfiltered listing) and can be revoked per consumer —
namespaces live in the client.

| consumer | URL | key | user_id |
|---|---|---|---|
| pi bots container | `https://memory.sudakov.site` | Bitwarden `mem0 fleet` | per agent |
| personal pi (`~/.pi/agent`) | `https://memory.sudakov.site` | Bitwarden `mem0 pi` | `denis` |

Keys come from `provision-keys.sh` and are shown once.

## Backups

```sh
podman exec mem0-db pg_dump -U mem0 -d postgres  | gzip > mem0-memories-$(date +%F).sql.gz
podman exec mem0-db pg_dump -U mem0 -d mem0_app  | gzip > mem0-app-$(date +%F).sql.gz
```

`postgres` holds the memories, `mem0_app` the accounts and keys. Take both
before moving or upgrading the stack; `pg_restore`/`psql` puts them back.

## Updating

```sh
cd ~/mem0 && git fetch --tags && git checkout <tag>
cd deploy && MEM0_ADMIN_API_KEY=... MEM0_JWT_SECRET=... podman-compose up -d --build
```

The compose project is independent of anything that talks to it: stopping a
consumer never stops memory, and the data (`deploy/pgdata`) is not touched by a
rebuild. Rerun `configure.sh` only if the config changed.

## Open items

- Nightly `pg_dump` + off-host copy.
- The server keeps a chat log (`deploy/history/`) and feeds recent messages into
  extraction context — a deleted memory can be re-extracted from it. Wipe
  `history/` alongside `pgdata/` for a truly clean slate.
