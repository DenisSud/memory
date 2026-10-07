#!/usr/bin/env python3
"""Refactor near-duplicate memories with a headless pi agent.

The store drifts: the same fact gets captured several times, phrased
differently, and nothing removes the older copies. This is the maintenance pass
that clusters those memories and has a small pi agent merge each cluster into a
cleaner set, trusting the newer memory on conflict.

It is deliberately two phases, never one:

  plan   export the store, cluster by embedding similarity, run the agent on
         each cluster, write <work>/review.md and <work>/actions.json. Changes
         nothing.
  apply  take a pg_dump backup, then replay <work>/actions.json against the
         service (PUT rewritten survivors, DELETE the rest).

Read review.md between them. The agent is good but not infallible; the review
file is the gate, and the backup is the undo.

Same-fact decisions come only from the agent — there is no separate LLM
consolidation step, and a survivor is always an existing memory (rewritten in
place, so its id and timestamp survive).

Example
-------
    export MEM0_PI_KEY=$(...)
    ./tools/refactor/refactor.py plan --ssh 192.168.1.6
    $EDITOR .refactor-work/review.md
    ./tools/refactor/refactor.py apply --ssh 192.168.1.6

Needs numpy (clustering) and the `pi` CLI on PATH.
"""

from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DEFAULT_BASE_URL = os.environ.get("MEM0_URL", "https://memory.sudakov.site")
DEFAULT_MODEL = "opencode-go/deepseek-v4.1-flash"
DEFAULT_THINKING = "low"
DEFAULT_FLOOR = 0.82
DEFAULT_JOBS = 4
DEFAULT_USER = "denis"
DEFAULT_WORK = ".refactor-work"

DUMP_SQL = (
    "\\copy (select id, payload->>'data' as data, "
    "payload->>'created_at' as created_at, payload->>'updated_at' as updated_at, "
    "vector::text as vec from memories where payload->>'user_id'='{user}') "
    "to stdout with (format csv, header true)"
)

RULES = """You curate a personal memory store. Read {infile}. It holds ONE cluster of related memories:
{{"cluster_id": N, "memories": [{{"id","updated_at","text"}}, ...]}}.

Goal: a minimal set of SHORT, self-contained memories that preserves every unique fact.

Rules:
1. Merge two memories ONLY if they assert the same fact(s) and one is redundant given the other. If they merely share a topic but each carries distinct information, keep both.
2. On a genuine conflict (same fact, different value), trust the NEWER memory (higher updated_at) and drop the older value.
3. When merging, the surviving memory's text must contain every unique fact, number, path, name, date and correction from the memories it replaces. Never invent facts.
4. Keep each surviving memory focused: one fact or a tight set of facts, at most ~2 sentences / 400 characters. Never concatenate unrelated memories into one blob.
5. The surviving memory of a merge is the newest of those merged; reuse its "id". A memory that needs no change stays exactly as it is.
6. Every input id must appear EXACTLY ONCE: either as a survivor in "memories" or in "delete". If nothing should merge, list all ids in "memories" and use an empty "delete".

Output ONLY this JSON (no prose, no markdown fences):
{{"cluster_id": N, "memories": [{{"id": "<surviving id>", "text": "<final text>"}}], "delete": ["<id>", ...]}}

Write that JSON to {outfile} using the write tool, then reply DONE."""


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def dump_command(ssh: str | None, user: str) -> str:
    sql = DUMP_SQL.format(user=user)
    inner = "podman exec -i mem0-db psql -U mem0 -d postgres -c " + shlex.quote(sql)
    return f"ssh {shlex.quote(ssh)} {shlex.quote(inner)}" if ssh else inner


def dump_backup_command(ssh: str | None) -> str:
    inner = "podman exec mem0-db pg_dump -U mem0 -d postgres"
    return f"ssh {shlex.quote(ssh)} {shlex.quote(inner)}" if ssh else inner


def read_csv(cmd: str) -> list[dict]:
    proc = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        fail(f"export failed: {proc.stderr.decode()[:400]}")
    text = proc.stdout.decode()
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        fail("export returned no rows")
    for col in ("id", "data", "updated_at", "vec"):
        if col not in rows[0]:
            fail(f"export missing column {col!r}")
    return rows


# ---------------------------------------------------------------------------
# clustering
# ---------------------------------------------------------------------------

def build_clusters(rows: list[dict], floor: float) -> list[list[int]]:
    import numpy as np

    X = np.vstack([np.fromstring(r["vec"].strip("[]"), sep=",", dtype=np.float32) for r in rows])
    Xn = X / np.linalg.norm(X, axis=1, keepdims=True).clip(min=1e-9)
    S = Xn @ Xn.T
    np.fill_diagonal(S, 0.0)

    parent = list(range(len(rows)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ii, jj = np.where(np.triu(S, 1) >= floor)
    for a, b in zip(ii.tolist(), jj.tolist()):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    groups: dict[int, list[int]] = {}
    for k in range(len(rows)):
        groups.setdefault(find(k), []).append(k)
    clusters = [sorted(v) for v in groups.values() if len(v) > 1]
    clusters.sort(key=lambda v: (-len(v), min(v)))
    return clusters


# ---------------------------------------------------------------------------
# agent
# ---------------------------------------------------------------------------

def validate(src: dict, result: dict) -> str | None:
    in_ids = [m["id"] for m in src["memories"]]
    if result.get("cluster_id") != src["cluster_id"]:
        return "cluster_id mismatch"
    seen: list[str] = []
    for m in result.get("memories", []):
        if m.get("id") not in in_ids:
            return f"unknown survivor id {m.get('id')}"
        if not isinstance(m.get("text"), str) or not m["text"].strip():
            return "empty survivor text"
        seen.append(m["id"])
    for d in result.get("delete", []):
        if d not in in_ids:
            return f"unknown delete id {d}"
        seen.append(d)
    if sorted(seen) != sorted(in_ids) or len(set(seen)) != len(seen):
        return "ids do not partition the input exactly once"
    return None


def run_agent(args, work: str, path: str) -> tuple[int, bool, str]:
    n = int(os.path.basename(path).split("_")[1].split(".")[0])
    src = json.load(open(path))
    outfile = f"{work}/out/cluster_{n:03d}.json"
    inbox = os.path.relpath(path, ".")
    outbox = os.path.relpath(outfile, ".")
    last = ""
    for attempt in range(3):
        prompt = RULES.format(infile=inbox, outfile=outbox)
        if attempt:
            prompt = (f"Your previous output was invalid: {last}. Rewrite {outbox} "
                      f"correctly, preserving the exact schema. Read {inbox} again.\n\n") + prompt
        env = {k: v for k, v in os.environ.items()
               if k not in ("PI_SESSION_FILE", "PI_SESSION_ID", "PI_REASONING_LEVEL")}
        with open(f"{work}/logs/cluster_{n:03d}.log", "w") as lf:
            subprocess.run(
                ["pi", "-p", "--model", args.model, "--thinking", args.thinking,
                 "--no-extensions", "--no-skills", "--no-context-files",
                 "--no-session", "--no-approve", "--tools", "read,write", prompt],
                env=env, stdout=lf, stderr=subprocess.STDOUT, timeout=300)
        try:
            result = json.load(open(outfile))
        except Exception as e:  # noqa: BLE001 - report and retry
            last = f"could not read {outbox}: {e}"
            continue
        err = validate(src, result)
        if err is None:
            return n, True, str(attempt + 1)
        last = err
    return n, False, last


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

def cmd_plan(args) -> None:
    here = os.getcwd()
    work = os.path.abspath(args.work)
    for sub in ("in", "out", "logs"):
        os.makedirs(os.path.join(work, sub), exist_ok=True)

    cmd = args.dump_cmd or dump_command(args.ssh, args.user)
    print(f"exporting memories via: {cmd}")
    rows = read_csv(cmd)
    print(f"memories: {len(rows)}")

    clusters = build_clusters(rows, args.floor)
    if args.limit:
        clusters = clusters[: args.limit]
    print(f"clusters (floor={args.floor}): {len(clusters)} "
          f"members={sum(len(c) for c in clusters)}")

    for n, members in enumerate(clusters, 1):
        out = {"cluster_id": n, "memories": [
            {"id": rows[m]["id"], "updated_at": rows[m]["updated_at"], "text": rows[m]["data"]}
            for m in members]}
        json.dump(out, open(os.path.join(work, "in", f"cluster_{n:03d}.json"), "w"), indent=2)

    inbox = sorted(glob.glob(os.path.join(work, "in", "cluster_*.json")))
    print(f"running pi agent ({args.model}, thinking={args.thinking}) over {len(inbox)} clusters")
    os.chdir(here)  # agent paths are relative to the invocation cwd
    ok = bad = 0
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        for n, good, info in ex.map(lambda p: run_agent(args, work, p), inbox):
            if good:
                ok += 1
            else:
                bad += 1
                print(f"  cluster {n:03d}: FAILED ({info})")
    print(f"agent: ok={ok} failed={bad}")
    if bad:
        fail("some clusters failed; rerun plan, then review")

    # collate
    updates, deletes, unchanged = [], [], []
    lines = ["# mem0 refactor review\n"]
    rewrites = 0
    for path in inbox:
        n = int(os.path.basename(path).split("_")[1].split(".")[0])
        src = json.load(open(path))
        old = {m["id"]: m["text"] for m in src["memories"]}
        out = json.load(open(os.path.join(work, "out", f"cluster_{n:03d}.json")))
        lines.append(f"\n## cluster {n}  ({len(old)} -> {len(out['memories'])} memories, "
                     f"{len(out['delete'])} deleted)\n")
        for m in out["memories"]:
            o = old[m["id"]]
            if o.strip() == m["text"].strip():
                unchanged.append(m["id"])
                lines.append(f"- KEEP unchanged `{m['id'][:8]}`: {o}")
            else:
                rewrites += 1
                updates.append({"id": m["id"], "text": m["text"]})
                lines.append(f"- REWRITE `{m['id'][:8]}`:\n  - old: {o}\n  - new: {m['text']}")
        for d in out["delete"]:
            deletes.append({"id": d, "text": old[d]})
            lines.append(f"- DELETE `{d[:8]}`: {old[d]}")

    json.dump({"base_url": args.base_url, "user": args.user,
               "updates": updates, "deletes": deletes, "unchanged": unchanged},
              open(os.path.join(work, "actions.json"), "w"), indent=2)
    open(os.path.join(work, "review.md"), "w").write("\n".join(lines) + "\n")

    print(f"rewrites={rewrites} unchanged={len(unchanged)} deletes={len(deletes)}")
    print(f"review : {work}/review.md")
    print(f"actions: {work}/actions.json")
    print("Nothing changed. Review the file, then run: refactor.py apply")


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def request(method: str, url: str, key: str, body=None) -> int:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"X-API-Key": key, "content-type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2)
                continue
            raise RuntimeError(f"{method} {url}: HTTP {e.code} {e.read()[:160]}")
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1)
    return 0


def cmd_apply(args) -> None:
    work = os.path.abspath(args.work)
    actions = json.load(open(os.path.join(work, "actions.json")))
    key = os.environ.get("MEM0_PI_KEY")
    if not key:
        fail("MEM0_PI_KEY is not set")

    if not args.skip_backup:
        ts = time.strftime("%Y-%m-%d_%H%M%S")
        backup = os.path.join(work, f"backup-{ts}.sql.gz")
        cmd = dump_backup_command(args.ssh)
        print(f"backup -> {backup}")
        with gzip.open(backup, "wb") as fh:
            proc = subprocess.run(cmd, shell=True, stdout=fh, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            fail(f"backup failed: {proc.stderr.decode()[:400]}")

    ok = 0
    for u in actions["updates"]:
        request("PUT", f"{args.base_url}/memories/{u['id']}", key, {"text": u["text"]})
        ok += 1
    for d in actions["deletes"]:
        request("DELETE", f"{args.base_url}/memories/{d['id']}", key)
        ok += 1
    print(f"applied {ok} operations "
          f"({len(actions['updates'])} rewrites, {len(actions['deletes'])} deletes)")


# ---------------------------------------------------------------------------

def main() -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--work", default=DEFAULT_WORK,
                        help="working directory (default: %(default)s)")
    common.add_argument("--base-url", default=DEFAULT_BASE_URL)
    common.add_argument("--user", default=DEFAULT_USER)
    common.add_argument("--ssh", default=None, help="host that runs the mem0 podman stack")
    common.add_argument("--dump-cmd", default=None, help="override the export command")

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", parents=[common],
                       help="export, cluster, run the agent, write the review")
    p.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--thinking", default=DEFAULT_THINKING)
    p.add_argument("--jobs", type=int, default=DEFAULT_JOBS)
    p.add_argument("--limit", type=int, default=0, help="only the first N clusters (testing)")
    p.set_defaults(func=cmd_plan)

    a = sub.add_parser("apply", parents=[common], help="backup, then apply actions.json")
    a.add_argument("--skip-backup", action="store_true")
    a.set_defaults(func=cmd_apply)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
