/** A conversation message, in the shape the service expects. */
export interface Message {
  role: string;
  content: string;
}

/** A stored memory as the service returns it. */
export interface MemoryItem {
  id: string;
  memory: string;
  score?: number;
  user_id?: string;
  agent_id?: string;
  created_at?: string;
  updated_at?: string;
}

/** One memory the server extracted and stored during an `add`. */
export interface AddedMemory {
  id: string;
  memory: string;
  event: string;
}

/** The result of an `add` call. */
export interface AddResult {
  results?: AddedMemory[];
}

/** `fetch`-compatible function; inject one for tests or a custom transport. */
export type FetchLike = (input: string | URL, init?: RequestInit) => Promise<Response>;

export interface Mem0ClientOptions {
  /** Service root, e.g. `https://memory.example.com`. A trailing slash is ignored. */
  baseUrl: string;
  /** Sent as `X-API-Key`. */
  apiKey?: string;
  /** Per-request timeout in milliseconds. Default `30000`. */
  timeoutMs?: number;
  /** Override the global `fetch`. */
  fetch?: FetchLike;
}

/** Identifies the memory scope. Every read and write is scoped by `userId`. */
export interface ScopeOptions {
  userId: string;
  agentId?: string;
  /** Cancels the request; rejects with a `Mem0Error` whose code is `cancelled`. */
  signal?: AbortSignal;
}

export interface AddOptions extends ScopeOptions {
  /** Let the server run its extraction pass. Omit for the server default (`true`). */
  infer?: boolean;
}

export interface SearchOptions extends ScopeOptions {
  /** Maximum number of results. Omit for the server default. */
  topK?: number;
}

export interface DeleteOptions {
  signal?: AbortSignal;
}
