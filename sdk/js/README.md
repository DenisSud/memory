# mem0-js-sdk

JavaScript client for the self-hosted mem0 service — the four endpoints the
Pi memory extension uses, with no dependencies beyond `fetch`.

## Install

Consumed as a Git dependency, pinned to a release tag:

```json
{
  "dependencies": {
    "mem0-js-sdk": "git+https://github.com/DenisSud/memory.git#mem0-js-sdk-v0.1.0&path:/sdk/js"
  }
}
```

pnpm clones the repository at that tag, prepares `sdk/js` and runs its build
(`packageManager` and the `prepare` script in `package.json` drive that), so the
consumer needs git access to the repository and nothing else.

## Use

```ts
import { Mem0Client } from 'mem0-js-sdk';

const mem0 = new Mem0Client({
  baseUrl: process.env.MEM0_URL!,   // e.g. https://memory.example.com
  apiKey: process.env.MEM0_API_KEY, // sent as X-API-Key
});

// Store a conversation; the server extracts the facts.
await mem0.add(
  [
    { role: 'user', content: 'I run NixOS on a Ryzen box' },
    { role: 'assistant', content: 'Noted.' },
  ],
  { userId: 'denis' },
);

// Semantic search, scoped to the same user.
const memories = await mem0.search('what do I run?', { userId: 'denis', topK: 5 });

// Everything in the scope, and removal by id.
const all = await mem0.getAll({ userId: 'denis' });
await mem0.delete(all[0].id);
```

## API

| Method | Request | Returns |
|---|---|---|
| `add(messages, { userId, agentId?, infer?, signal? })` | `POST /memories` | `AddResult \| null` — the extracted memories |
| `search(query, { userId, agentId?, topK?, signal? })` | `POST /search` | `MemoryItem[]` |
| `getAll({ userId, agentId?, signal? })` | `GET /memories` | `MemoryItem[]` |
| `delete(memoryId, { signal? })` | `DELETE /memories/{id}` | `void` |

`MemoryItem` is `{ id, memory, score?, user_id?, agent_id?, created_at?,
updated_at? }`. The client accepts both the `{ results: [...] }` envelope and a
bare array, and the server's field aliases.

Options: `baseUrl` (required, http/https), `apiKey` (→ `X-API-Key`),
`timeoutMs` (default `30000`), `fetch` (override the global).

## Failures

Every rejection is a `Mem0Error` with a `code`:

| `code` | meaning |
|---|---|
| `timeout` | the request exceeded `timeoutMs` |
| `cancelled` | the caller's `AbortSignal` fired |
| `http` | the server answered a non-2xx status (`status` carries it) |
| `network` | the request never completed |
| `invalid-response` | a 2xx body that is not JSON |

## Development

```bash
pnpm install
pnpm test        # vitest, real HTTP server on a loopback port
pnpm typecheck
pnpm build       # tsup → dist/, ESM + CJS + types
```

Releases are tags of this repository, prefixed with the package name
(`mem0-js-sdk-v0.1.0`, matching upstream's `vercel-ai-v*` tags). Bump `version`
here and tag the commit; consumers pin the tag.
