# refactor — near-duplicate memory maintenance

The store drifts. The same fact gets captured several times, worded
differently, and nothing removes the older copies. This tool clusters those
memories and has a small pi agent merge each cluster into a cleaner set, which
is how the list comes down.

It is a manual maintenance pass, not part of the service. Same-fact decisions
come **only** from the agent — there is no separate LLM consolidation step, and
every survivor is an existing memory, rewritten in place so its id and
timestamp survive.

## Two phases, never one

```sh
export MEM0_PI_KEY=$(...)           # the consumer key for --user

./refactor.py plan  --ssh <host>    # export + cluster + agent -> review.md
$EDITOR .refactor-work/review.md    # the gate
./refactor.py apply --ssh <host>    # backup + PUT rewrites + DELETE removals
```

`plan` changes nothing. `apply` refuses to run without `MEM0_PI_KEY` and takes a
`pg_dump` into `.refactor-work/backup-<ts>.sql.gz` first (`--skip-backup` to
skip). The review file is the gate; the backup is the undo.

## How it works

1. **Export** — the whole `user_id` scope from `pgvector`: id, text, timestamps
   and the 768-d vector, as CSV. `--ssh <host>` runs the export through that
   host's podman stack (the DB is not exposed).
2. **Cluster** — cosine similarity, edges at `--floor` (default 0.82), connected
   components. Anything not in a cluster of two or more is left alone. Keep the
   floor high: lower values chain unrelated memories into one blob.
3. **Agent** — one headless pi call per cluster:

   ```
   pi -p --model opencode-go/deepseek-v4.1-flash --thinking low \
      --no-extensions --no-skills --no-context-files --no-session --no-approve \
      --tools read,write "<prompt>"
   ```

   The prompt merges only same-fact memories, trusts the newer memory on
   conflict, preserves every unique fact, keeps each survivor to ~2 sentences,
   and must partition the input ids exactly once into survivors + `delete`. The
   output is validated against the schema and retried up to three times.
4. **Review** — `.refactor-work/review.md` lists, per cluster, each rewrite
   (old → new) and each deletion (with its text).
5. **Apply** — `PUT /memories/{id}` for rewritten survivors, `DELETE
   /memories/{id}` for the rest.

## Requirements

- `numpy` for clustering, and the `pi` CLI on `PATH`.
- `MEM0_PI_KEY` set for `apply` (read from the environment, never argv).
- A System One endpoint is *not* needed — the agent is not the gate model; it
  runs wherever `pi` runs.

## Files written

Everything lands in `--work` (default `.refactor-work/`, gitignored):

| path | what |
|---|---|
| `in/cluster_NNN.json` | the agent's input, one cluster per file |
| `out/cluster_NNN.json` | the agent's validated output |
| `logs/cluster_NNN.log` | the pi run, for a failed cluster |
| `review.md` | the human review file |
| `actions.json` | the exact operations `apply` replays |
| `backup-*.sql.gz` | the pre-apply dump |
