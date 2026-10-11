/**
 * Internet-facing login throttle for the BFF tier (P0-B).
 *
 * The backend API intentionally does per-email limiting only: behind this proxy
 * every browser shares the BFF's server address, so a backend per-IP bucket would
 * let one customer lock out all others. This limiter keys on the peer address as
 * observed by OUR edge (last X-Forwarded-For entry — the hop that talked to us —
 * or "direct" with no proxy chain). Attacker-controlled left entries never select
 * the bucket: spoofing them cannot shift blame to, or borrow quota from, anyone.
 *
 * In-memory sliding window per process: correct for dev/single-instance; platform
 * edge rate limiting is the production answer (tracked pre-production gate).
 */
export interface WindowState {
  hits: number[];
}

export const LOGIN_WINDOW_MS = 15 * 60 * 1000;
// Generous on purpose: this tier stops high-rate sprays from one peer address,
// while the backend's per-email limiter (5/15min + reset-on-success) remains the
// strict account protection. Shared office/NAT egress must not lock out quickly.
export const LOGIN_MAX_ATTEMPTS = 20;

const buckets = new Map<string, number[]>();

export function edgeClientKey(forwardedFor: string | null): string {
  if (!forwardedFor) return "direct";
  const parts = forwardedFor
    .split(",")
    .map((p) => p.trim().toLowerCase())
    .filter((p) => p !== "");
  return parts.length > 0 ? parts[parts.length - 1] : "direct";
}

export function edgeLoginAllowed(key: string, nowMs: number, store: Map<string, number[]> = buckets): boolean {
  const cutoff = nowMs - LOGIN_WINDOW_MS;
  const hits = (store.get(key) ?? []).filter((t) => t > cutoff);
  store.set(key, hits);
  return hits.length < LOGIN_MAX_ATTEMPTS;
}

export function edgeLoginHit(key: string, nowMs: number, store: Map<string, number[]> = buckets): void {
  const hits = store.get(key) ?? [];
  hits.push(nowMs);
  store.set(key, hits);
}

export function edgeRetryAfterMs(key: string, nowMs: number, store: Map<string, number[]> = buckets): number {
  const hits = (store.get(key) ?? []).filter((t) => t > nowMs - LOGIN_WINDOW_MS);
  if (hits.length < LOGIN_MAX_ATTEMPTS) return 0;
  return Math.max(0, Math.min(...hits) + LOGIN_WINDOW_MS - nowMs);
}

export function clearEdgeBuckets(store: Map<string, number[]> = buckets): void {
  store.clear();
}
