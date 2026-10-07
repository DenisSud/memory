import { Mem0Error } from './errors.js';
import type {
  AddOptions,
  AddResult,
  DeleteOptions,
  FetchLike,
  MemoryItem,
  Mem0ClientOptions,
  Message,
  ScopeOptions,
  SearchOptions,
} from './types.js';

const DEFAULT_TIMEOUT_MS = 30_000;

/**
 * Client for a self-hosted mem0 service: four endpoints over plain HTTP.
 *
 * One instance is safe to share; it holds no connections. Every method is
 * scoped by `userId`, and a failure always rejects with a {@link Mem0Error}
 * carrying a `code` the caller can act on.
 */
export class Mem0Client {
  readonly baseUrl: string;
  readonly timeoutMs: number;

  readonly #apiKey: string | undefined;
  readonly #fetch: FetchLike;

  constructor(options: Mem0ClientOptions) {
    let url: URL;
    try {
      url = new URL(options.baseUrl);
    } catch {
      throw new TypeError(`mem0-js-sdk: baseUrl is not a URL: ${options.baseUrl}`);
    }
    if (url.protocol !== 'http:' && url.protocol !== 'https:') {
      throw new TypeError('mem0-js-sdk: baseUrl must be http or https.');
    }
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
      throw new RangeError('mem0-js-sdk: timeoutMs must be a positive number.');
    }
    this.baseUrl = url.toString().replace(/\/$/, '');
    this.timeoutMs = timeoutMs;
    this.#apiKey = options.apiKey?.trim() || undefined;
    this.#fetch = options.fetch ?? fetch;
  }

  /** Store a conversation. The server extracts and deduplicates the facts. */
  async add(messages: Message[], options: AddOptions): Promise<AddResult | null> {
    if (!Array.isArray(messages) || messages.length === 0) {
      throw new TypeError('mem0-js-sdk: add() needs at least one message.');
    }
    const body = {
      messages,
      user_id: options.userId,
      ...(options.agentId ? { agent_id: options.agentId } : {}),
      ...(options.infer === undefined ? {} : { infer: options.infer }),
    };
    const result = await this.#request('/memories', { method: 'POST', body: JSON.stringify(body) }, options.signal);
    return result === null ? null : (result as AddResult);
  }

  /** Semantic search over the scope. */
  async search(query: string, options: SearchOptions): Promise<MemoryItem[]> {
    if (!query.trim()) throw new TypeError('mem0-js-sdk: search() needs a non-empty query.');
    const body = {
      query,
      filters: {
        user_id: options.userId,
        ...(options.agentId ? { agent_id: options.agentId } : {}),
      },
      ...(options.topK === undefined ? {} : { top_k: options.topK }),
    };
    return normalizeResults(
      await this.#request('/search', { method: 'POST', body: JSON.stringify(body) }, options.signal),
    );
  }

  /** List every memory in the scope. */
  async getAll(options: ScopeOptions): Promise<MemoryItem[]> {
    const params = new URLSearchParams({ user_id: options.userId });
    if (options.agentId) params.set('agent_id', options.agentId);
    return normalizeResults(await this.#request(`/memories?${params}`, { method: 'GET' }, options.signal));
  }

  /** Delete one memory by id. */
  async delete(memoryId: string, options: DeleteOptions = {}): Promise<void> {
    if (!memoryId) throw new TypeError('mem0-js-sdk: delete() needs a memory id.');
    await this.#request(`/memories/${encodeURIComponent(memoryId)}`, { method: 'DELETE' }, options.signal);
  }

  async #request(path: string, init: RequestInit, callerSignal?: AbortSignal): Promise<unknown> {
    const headers: Record<string, string> = { 'content-type': 'application/json' };
    if (this.#apiKey) headers['x-api-key'] = this.#apiKey;

    // One signal carries both deadlines; which one fired decides the error.
    const timeoutSignal = AbortSignal.timeout(this.timeoutMs);
    const signal = callerSignal ? AbortSignal.any([callerSignal, timeoutSignal]) : timeoutSignal;

    let response: Response;
    try {
      response = await this.#fetch(`${this.baseUrl}${path}`, { ...init, headers, signal });
    } catch (cause) {
      throw this.#failure('network', 'request failed', callerSignal, timeoutSignal, cause);
    }

    if (!response.ok) {
      throw new Mem0Error('http', `Mem0 request failed (${response.status}).`, { status: response.status });
    }
    if (response.status === 204) return null;

    try {
      return await response.json();
    } catch (cause) {
      throw this.#failure('invalid-response', 'returned an invalid response', callerSignal, timeoutSignal, cause);
    }
  }

  #failure(
    code: 'network' | 'invalid-response',
    what: string,
    callerSignal: AbortSignal | undefined,
    timeoutSignal: AbortSignal,
    cause: unknown,
  ): Mem0Error {
    if (callerSignal?.aborted) {
      return new Mem0Error('cancelled', 'Mem0 request cancelled.', { cause });
    }
    if (timeoutSignal.aborted) {
      return new Mem0Error('timeout', `Mem0 request timed out after ${this.timeoutMs}ms.`, { cause });
    }
    return new Mem0Error(code, `Mem0 ${what}: ${errorMessage(cause)}`, { cause });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function normalizeResults(raw: unknown): MemoryItem[] {
  const items = Array.isArray(raw) ? raw : isRecord(raw) && Array.isArray(raw.results) ? raw.results : [];
  return items.map(normalizeItem);
}

/** Accept the server's field aliases; never invent a value. */
function normalizeItem(raw: unknown): MemoryItem {
  const record = isRecord(raw) ? raw : {};
  const item: MemoryItem = {
    id: String(record.id ?? record.memory_id ?? ''),
    memory: String(record.memory ?? record.text ?? record.content ?? ''),
  };
  if (typeof record.score === 'number') item.score = record.score;
  if (typeof record.user_id === 'string') item.user_id = record.user_id;
  if (typeof record.agent_id === 'string') item.agent_id = record.agent_id;
  const createdAt = record.created_at ?? record.createdAt;
  if (typeof createdAt === 'string') item.created_at = createdAt;
  const updatedAt = record.updated_at ?? record.updatedAt;
  if (typeof updatedAt === 'string') item.updated_at = updatedAt;
  return item;
}

function errorMessage(cause: unknown): string {
  if (cause instanceof Error) {
    const inner = (cause as { cause?: unknown }).cause;
    if (inner instanceof Error && inner.message && !cause.message.includes(inner.message)) {
      return `${cause.message}: ${inner.message}`;
    }
    return cause.message;
  }
  return String(cause);
}
