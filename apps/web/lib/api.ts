/** Typed API client. Same-origin transport only: the browser calls /api/* on this
 * host and the route handler in app/api/v1/[...path] forwards server-side to the
 * deploy-configured backend. No cross-origin calls, no credentials involved. */
export interface HealthPayload {
  status: "ok";
  service: string;
  version: string;
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthPayload> {
  const res = await fetch("/api/v1/health", { signal });
  if (!res.ok) throw new Error(`backend health failed: ${res.status}`);
  return (await res.json()) as HealthPayload;
}
