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
