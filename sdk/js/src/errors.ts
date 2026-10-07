export type Mem0ErrorCode =
  | 'timeout'
  | 'cancelled'
  | 'http'
  | 'network'
  | 'invalid-response';

/** Every failure the client raises, tagged so callers can decide what to retry. */
export class Mem0Error extends Error {
  readonly code: Mem0ErrorCode;
  readonly status: number | undefined;

  constructor(code: Mem0ErrorCode, message: string, options: { status?: number; cause?: unknown } = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = 'Mem0Error';
    this.code = code;
    this.status = options.status;
  }
}
