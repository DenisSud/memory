import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { describe, expect, it } from 'vitest';
import { Mem0Client, Mem0Error } from '../src/index.js';

interface Recorded {
  method: string;
  url: string;
  headers: IncomingMessage['headers'];
  body: unknown;
}

type Handler = (req: IncomingMessage, res: ServerResponse) => void;

/** Run `handler` on a throwaway HTTP server and hand the client its address. */
async function withServer(
  handler: Handler,
  run: (baseUrl: string, requests: Recorded[]) => Promise<void>,
): Promise<void> {
  const requests: Recorded[] = [];
  const server: Server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      requests.push({
        method: req.method ?? '',
        url: req.url ?? '',
        headers: req.headers,
        body: raw ? JSON.parse(raw) : undefined,
      });
      handler(req, res);
    });
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (address === null || typeof address === 'string') throw new Error('server has no port');
  try {
    await run(`http://127.0.0.1:${address.port}`, requests);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

function json(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

function client(baseUrl: string, options: { timeoutMs?: number } = {}): Mem0Client {
  return new Mem0Client({ baseUrl, apiKey: 'test-key', ...options });
}

describe('Mem0Client.add', () => {
  it('posts the conversation and returns the extracted memories', async () => {
    await withServer(
      (_req, res) => json(res, 200, { results: [{ id: 'm1', memory: 'Denis runs NixOS', event: 'ADD' }] }),
      async (baseUrl, requests) => {
        const result = await client(baseUrl).add([{ role: 'user', content: 'I run NixOS' }], {
          userId: 'u1',
          agentId: 'a1',
          infer: false,
        });

        expect(result?.results?.[0]).toEqual({ id: 'm1', memory: 'Denis runs NixOS', event: 'ADD' });
        expect(requests[0].method).toBe('POST');
        expect(requests[0].url).toBe('/memories');
        expect(requests[0].headers['x-api-key']).toBe('test-key');
        expect(requests[0].body).toEqual({
          messages: [{ role: 'user', content: 'I run NixOS' }],
          user_id: 'u1',
          agent_id: 'a1',
          infer: false,
        });
      },
    );
  });

  it('omits infer when the caller does not set it', async () => {
    await withServer(
      (_req, res) => json(res, 200, { results: [] }),
      async (baseUrl, requests) => {
        await client(baseUrl).add([{ role: 'user', content: 'hi' }], { userId: 'u1' });
        expect(requests[0].body).toEqual({ messages: [{ role: 'user', content: 'hi' }], user_id: 'u1' });
      },
    );
  });

  it('rejects an empty message list without calling the server', async () => {
    const mem0 = new Mem0Client({ baseUrl: 'http://127.0.0.1:1' });
    await expect(mem0.add([], { userId: 'u1' })).rejects.toThrow(TypeError);
  });
});

describe('Mem0Client.search', () => {
  it('sends the filter, the limit and the query, and normalizes the results', async () => {
    await withServer(
      (_req, res) => json(res, 200, { results: [{ id: 'm1', memory: 'Denis runs NixOS', score: 0.91, user_id: 'u1' }] }),
      async (baseUrl, requests) => {
        const memories = await client(baseUrl).search('what do I run?', {
          userId: 'u1',
          agentId: 'a1',
          topK: 3,
        });

        expect(memories).toEqual([{ id: 'm1', memory: 'Denis runs NixOS', score: 0.91, user_id: 'u1' }]);
        expect(requests[0].url).toBe('/search');
        expect(requests[0].body).toEqual({
          query: 'what do I run?',
          filters: { user_id: 'u1', agent_id: 'a1' },
          top_k: 3,
        });
      },
    );
  });

  it('accepts a bare array response', async () => {
    await withServer(
      (_req, res) => json(res, 200, [{ id: 'm1', memory: 'x' }]),
      async (baseUrl) => {
        expect(await client(baseUrl).search('x', { userId: 'u1' })).toEqual([{ id: 'm1', memory: 'x' }]);
      },
    );
  });

  it('returns an empty list when the server has no results', async () => {
    await withServer(
      (_req, res) => json(res, 200, { results: [] }),
      async (baseUrl) => {
        expect(await client(baseUrl).search('x', { userId: 'u1' })).toEqual([]);
      },
    );
  });
});

describe('Mem0Client.getAll', () => {
  it('passes the scope as query parameters', async () => {
    await withServer(
      (_req, res) => json(res, 200, { results: [{ id: 'm1', memory: 'x', created_at: '2026-10-01T00:00:00Z' }] }),
      async (baseUrl, requests) => {
        const memories = await client(baseUrl).getAll({ userId: 'u1', agentId: 'a1' });
        expect(memories[0].created_at).toBe('2026-10-01T00:00:00Z');
        expect(requests[0].method).toBe('GET');
        expect(requests[0].url).toBe('/memories?user_id=u1&agent_id=a1');
      },
    );
  });
});

describe('Mem0Client.delete', () => {
  it('deletes by encoded id', async () => {
    await withServer(
      (_req, res) => {
        res.writeHead(204);
        res.end();
      },
      async (baseUrl, requests) => {
        await client(baseUrl).delete('id/with slash');
        expect(requests[0].method).toBe('DELETE');
        expect(requests[0].url).toBe('/memories/id%2Fwith%20slash');
      },
    );
  });
});

describe('Mem0Client failures', () => {
  it('surfaces an HTTP status as a Mem0Error', async () => {
    await withServer(
      (_req, res) => json(res, 401, { detail: 'unauthorized' }),
      async (baseUrl) => {
        const promise = client(baseUrl).getAll({ userId: 'u1' });
        await expect(promise).rejects.toBeInstanceOf(Mem0Error);
        await expect(promise).rejects.toMatchObject({ code: 'http', status: 401 });
      },
    );
  });

  it('times out', async () => {
    await withServer(
      () => {
        /* never respond */
      },
      async (baseUrl) => {
        await expect(client(baseUrl, { timeoutMs: 50 }).search('x', { userId: 'u1' })).rejects.toMatchObject({
          code: 'timeout',
        });
      },
    );
  });

  it('cancels on the caller signal', async () => {
    await withServer(
      (_req, res) => {
        setTimeout(() => json(res, 200, { results: [] }), 200);
      },
      async (baseUrl) => {
        const controller = new AbortController();
        setTimeout(() => controller.abort(), 10);
        await expect(
          client(baseUrl).search('x', { userId: 'u1', signal: controller.signal }),
        ).rejects.toMatchObject({ code: 'cancelled' });
      },
    );
  });

  it('rejects a body that is not JSON', async () => {
    await withServer(
      (_req, res) => {
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end('not json');
      },
      async (baseUrl) => {
        await expect(client(baseUrl).getAll({ userId: 'u1' })).rejects.toMatchObject({
          code: 'invalid-response',
        });
      },
    );
  });
});

describe('Mem0Client construction', () => {
  it('rejects a non-http baseUrl', () => {
    expect(() => new Mem0Client({ baseUrl: 'ftp://memory.example.com' })).toThrow(TypeError);
  });

  it('rejects a non-positive timeout', () => {
    expect(() => new Mem0Client({ baseUrl: 'http://memory.example.com', timeoutMs: 0 })).toThrow(RangeError);
  });

  it('normalizes a trailing slash', () => {
    expect(new Mem0Client({ baseUrl: 'http://memory.example.com/' }).baseUrl).toBe('http://memory.example.com');
  });
});
