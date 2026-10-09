/** Typed API client configuration. No tax logic here — transport only. */
export interface HealthPayload {
  status: "ok";
  service: string;
  version: string;
}

export function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthPayload> {
  const res = await fetch(`${apiBase()}/api/v1/health`, { signal });
  if (!res.ok) throw new Error(`backend health failed: ${res.status}`);
  return (await res.json()) as HealthPayload;
}
