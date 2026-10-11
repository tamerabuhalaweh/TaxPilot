/**
 * BFF proxy policy (#36): only explicitly allowlisted headers are forwarded.
 * Everything else — including Cookie handling outside the session cookie,
 * x-forwarded-*, forwarded, host/connection internals — is dropped. The backend
 * origin itself comes only from server environment, never request input.
 */
export const FORWARDED_HEADERS = [
  "authorization",
  "cookie",
  "content-type",
  "accept",
  "accept-language",
  "x-request-id",
  "x-csrf-token",
  "idempotency-key"
] as const;

export const PROXY_MAX_BODY_BYTES = 1_048_576; // 1 MiB (auth/JSON only; uploads get own limits later)
export const PROXY_MAX_RESPONSE_BYTES = 10_485_760; // 10 MiB sanity cap

export function filterHeaders(input: Iterable<[string, string]>): Record<string, string> {
  const allow = new Set<string>(FORWARDED_HEADERS);
  const out: Record<string, string> = {};
  for (const [key, value] of input) {
    if (allow.has(key.toLowerCase())) out[key] = value;
  }
  return out;
}

export function bodyTooLarge(contentLength: string | null): boolean {
  if (contentLength === null) return false;
  const n = Number(contentLength);
  return Number.isFinite(n) && n > PROXY_MAX_BODY_BYTES;
}

export type BoundedRead =
  | { ok: true; bytes: Uint8Array }
  | { ok: false; received: number };

/** Cap on bytes drained past the limit while producing a clean 413. Beyond this
 * the connection is abandoned instead (client observes a network error rather
 * than a status). Either way nothing oversized is buffered or forwarded. */
export const PROXY_MAX_DISCARD_BYTES = 16 * 1024 * 1024;

/**
 * Bounded streaming read (R2): enforced even when Content-Length is missing or
 * lies. Bodies over the limit are drained (not stored) so legitimate-but-large
 * callers still receive a clean 413; nothing oversized is buffered or forwarded.
 * Callers must reject (!ok) with 413 without touching the backend.
 */
export async function readBoundedBody(
  stream: ReadableStream<Uint8Array> | null,
  limit: number
): Promise<BoundedRead> {
  if (!stream) return { ok: true, bytes: new Uint8Array(0) };
  const reader = stream.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  let discarded = 0;
  let over = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!over) {
        total += value.byteLength;
        if (total > limit) {
          over = true;
        } else {
          chunks.push(value);
        }
      } else {
        discarded += value.byteLength;
        if (discarded > PROXY_MAX_DISCARD_BYTES) {
          return { ok: false, received: total + discarded };
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
  if (over) return { ok: false, received: total + discarded };
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { ok: true, bytes: out };
}
