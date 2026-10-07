# AGENTS.md

Context for coding assistants working in this repository.

## What this is

The **pi fork of [`mem0ai/mem0`](https://github.com/mem0ai/mem0)** — the memory
service behind Denis's Pi agents and bots. It exists to own one deployment, not
to contribute upstream. [`PI-FORK.md`](PI-FORK.md) is the authoritative account
of what we changed and why; read it before touching the gates.

`main` is the trunk and the base for every pull request: the upstream tree plus
our patch. Upstream is not tracked — we never rebase, we cherry-pick the commits
we want from a later release. Consequences:

- There is no upstream PR, CLA or review gate. Do not open one.
- Upstream-owned files stay as close to upstream as possible, so cherry-picks
  keep applying. Change them only when the fork genuinely needs to.
- A file that only exists for upstream's benefit should be deleted, not
  maintained — most already were.
- Upstream behaviour is preserved: the gates are the fork's only behavioural
  change. A cleanup commit must not change what the service returns.

## Layout

| Path | What it is |
|---|---|
| `mem0/` | Upstream Python SDK plus our patch: `systemone/` (the gates) and the two hook sites in `memory/main.py` |
| `mem0/configs/systemone.py` | `SystemOneConfig` — endpoint, model, thresholds, per-gate enable |
| `server/` | Upstream's FastAPI REST server, vendored unchanged |
| `deploy/` | Our compose stack (server + pgvector + Ollama), image and key provisioning |
| `tests/systemone/` | The gate tests |
| `tests/` (rest) | Upstream's SDK tests |
| `sdk/js/` | `mem0-js-sdk` — the JavaScript client for the service (git-dependency, tag-released). Not wired into a consumer yet |

Not here any more, deliberately: the docs site, the dashboard, `integrations/`,
the TypeScript SDK, the CLIs, `examples/`, `skills/`, `scripts/`, the
`evaluation/` submodule and `.github/` workflows.

## Toolchain

```bash
devenv shell                     # dev shell: py3.11/3.12, hatch, uv, node, pnpm, ruff, isort
setup                            # create the py3.11 hatch env + git hooks
hatch shell dev_py_3_11          # the documented Python env
check                            # pytest tests/ in that env
check-systemone                  # the gates only — the fast loop
lint / format / sort-imports
```

- **Python:** hatch owns the environments (`pyproject.toml`); never `pip install`
  into a global interpreter. Requires Python 3.11 or 3.12 here — 3.10 is EOL and
  no longer in nixpkgs.
- **Lint/format:** ruff, line length **120**, `select = ["E4","E7","E9","F"]`;
  isort with `profile = "black"`. `devenv`'s `lint`/`format` use nixpkgs ruff,
  because PyPI's ruff binary cannot execute on NixOS without `nix-ld`.
- **JS SDK:** pnpm, tsup build, vitest.
- **Server:** Docker only. `server-up` runs the dev stack; there is no
  non-Docker path.

## Conventions

- Python: `snake_case.py`, `test_<module>.py`, Pydantic v2 for models and config.
- JS/TS: `snake_case.ts` is not used — follow the package's existing style;
  ES modules only, strict mode.
- Commits: [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`).
- Never commit `.env`, keys or credentials. `deploy/` takes secrets at up time
  (`MEM0_ADMIN_API_KEY`, `MEM0_JWT_SECRET`) and `deploy/README.md` says how.

## What to ship with a change

| Change | Expect |
|---|---|
| **Bug fix** | A regression test that fails without the fix, written first; the fix; `check-systemone` or `check` passing; `lint` clean |
| **Gate behaviour** | A test in `tests/systemone/` covering the decision *and* the request shape; fail-open behaviour is a contract — a gate that errors must keep everything |
| **New SDK endpoint** | Client method, a vitest case against a mock server, README table update, version bump in `sdk/js/package.json` |
| **Deploy change** | `deploy/README.md` updated in the same commit; the stack must come back after a reboot |

Fix bugs at the root, not at the symptom. If a guard belongs in a shared
function, put it there rather than in each caller.

## The gates, in one paragraph

`SystemOneGates` asks a System One decision model (TypeSafe wire format, served
by Ollama/Kev/TypeSafe) one `noul` question per item in a single HTTP call —
once over extracted facts before they are stored, once over search results
before they are returned. Items below the threshold are dropped. **Every
failure path keeps the whole batch**: a flaky decision model must never lose or
hide memories. The question phrasing names the item and its state path; that is
what makes small local models discriminate.
