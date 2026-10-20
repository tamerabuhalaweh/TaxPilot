/** Typed API client. Same-origin transport only: the browser calls /api/* on this
 * host and the route handler in app/api/v1/[...path] forwards server-side to the
 * deploy-configured backend. Session travels in an httpOnly SameSite cookie set
 * by the backend; the browser attaches it automatically (same-origin, no JS access).
 * No cross-origin calls, no credentials involved. */
export interface HealthPayload {
  status: "ok";
  service: string;
  version: string;
}

export interface Membership {
  tenant_id: string;
  tenant_name?: string | null;
  role: string;
}

export interface MePayload {
  user_id: string;
  email: string;
  active_tenant_id: string | null;
  csrf_token?: string | null;
  memberships: Membership[];
}

export interface ClientPayload {
  id: string;
  name: string;
  external_ref?: string | null;
  sector?: string | null;
  contact?: string | null;
  status: string;
}

export interface ApiError {
  error: { code: string; message: string };
}

// Session CSRF token, read per request from the readable tp_csrf companion cookie
// (survives full-page navigations, unlike module memory). The httpOnly session
// cookie itself is never readable here; cross-origin JS cannot read either value.
function csrfFromCookie(): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === "tp_csrf") return decodeURIComponent(rest.join("=")) || null;
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "content-type": "application/json" };
  const method = (init?.method ?? "GET").toUpperCase();
  // Session-bound CSRF token for cookie-ambient mutations (P0-C). Login,
  // register, and verify carry no session yet and are exempt server-side.
  const csrf = csrfFromCookie();
  if (csrf && method !== "GET" && method !== "HEAD" && !path.endsWith("/auth/login")) {
    headers["x-csrf-token"] = csrf;
  }
  const res = await fetch(path, { ...init, headers: { ...headers, ...(init?.headers ?? {}) } });
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    let message = `Request failed: ${res.status}`;
    try {
      const body = (await res.json()) as ApiError;
      code = body.error.code;
      message = body.error.message;
    } catch {
      /* keep generic */
    }
    throw new ApiRequestError(code, message, res.status);
  }
  return (await res.json()) as T;
}

export class ApiRequestError extends Error {
  code: string;
  status: number;
  constructor(code: string, message: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthPayload> {
  const res = await fetch("/api/v1/health", { signal });
  if (!res.ok) throw new Error(`backend health failed: ${res.status}`);
  return (await res.json()) as HealthPayload;
}

export async function fetchMe(signal?: AbortSignal): Promise<MePayload> {
  const res = await fetch("/api/v1/users/me", { signal });
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    try {
      code = ((await res.json()) as ApiError).error.code;
    } catch {
      /* keep generic */
    }
    throw new ApiRequestError(code, "Not signed in.", res.status);
  }
  return (await res.json()) as MePayload;
}

export async function register(email: string, password: string, firmName: string): Promise<unknown> {
  return request("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, firm_name: firmName })
  });
}

export async function login(email: string, password: string): Promise<MePayload> {
  return request<MePayload>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
}

export async function logout(): Promise<void> {
  await request("/api/v1/auth/logout", { method: "POST", body: "{}" });
}

export async function verifyAccount(token: string): Promise<void> {
  await request("/api/v1/auth/verify", {
    method: "POST",
    body: JSON.stringify({ token })
  });
}

export async function listClients(status: "active" | "archived" | "all" = "active"): Promise<ClientPayload[]> {
  return request<ClientPayload[]>(`/api/v1/clients?status=${status}`);
}

export async function createClient(name: string): Promise<ClientPayload> {
  return request<ClientPayload>("/api/v1/clients", {
    method: "POST",
    body: JSON.stringify({ name })
  });
}

export async function getClient(id: string): Promise<ClientPayload> {
  return request<ClientPayload>(`/api/v1/clients/${encodeURIComponent(id)}`);
}

/** Engagement (review) record from the workspace API. */
export interface EngagementPayload {
  id: string;
  client_id: string;
  review_type: string;
  period_start: string;
  period_end: string;
  status: "DRAFT" | "ACTIVE" | "CLOSED" | "ARCHIVED";
  revision: number;
  created_at: string;
}

export async function listEngagements(clientId?: string): Promise<EngagementPayload[]> {
  const query = clientId ? `?client_id=${encodeURIComponent(clientId)}` : "";
  return request<EngagementPayload[]>(`/api/v1/engagements${query}`);
}

export async function getEngagement(id: string): Promise<EngagementPayload> {
  return request<EngagementPayload>(`/api/v1/engagements/${encodeURIComponent(id)}`);
}

export async function createEngagement(input: {
  client_id: string;
  review_type: string;
  period_start: string;
  period_end: string;
}): Promise<EngagementPayload> {
  return request<EngagementPayload>("/api/v1/engagements", {
    method: "POST",
    body: JSON.stringify(input)
  });
}

/** Restricted synthetic-demo reconciliation payloads (REC-UI-01). */
export interface DemoFixturePayload {
  fixture_id: string;
  title: string;
  description: string;
  jurisdiction: string;
  rules_version: string;
  period_start: string;
  period_end: string;
  sales_dataset_id: string;
  gl_dataset_id: string;
  account_scope: string[];
  currency_scope: string[];
}

export interface DemoMoney {
  amount: string;
  currency: string;
}

export interface DemoEvidence {
  dataset_id: string;
  source: string;
  row_number: number;
  raw_reference: string;
  role: "sales" | "gl";
}

export interface DemoFinding {
  finding_id: string;
  category: string;
  severity: string;
  review_state: string | null;
  review_required: boolean;
  rule: string;
  outcome_kind: string;
  title: string;
  what: string;
  compared: string;
  difference: string;
  why: string;
  guidance: string;
  sales: DemoMoney[];
  gl: DemoMoney[];
  delta: string | null;
  delta_currency: string | null;
  evidence: DemoEvidence[];
  rationale: string[];
  flags: string[];
}

export interface DemoCurrencyResult {
  currency: string;
  outcome: "DIFFERENCE" | "INCONCLUSIVE_COVERAGE";
  sales_total: string | null;
  gl_total: string | null;
  delta: string | null;
}

export interface DemoCoverage {
  complete: boolean;
  currencies: string[];
  reasons: string[];
  explanations: string[];
}

export interface DemoConclusion {
  status: "BLOCKED" | "REVIEW_REQUIRED" | "NO_REVIEW_ITEMS";
  headline: string;
  detail: string;
  caution: string;
  currency_results: DemoCurrencyResult[];
  coverage: DemoCoverage;
}

export interface DemoRunPayload {
  synthetic: boolean;
  label: string;
  fixture_id: string;
  fixture_title: string;
  jurisdiction: string;
  rules_version: string;
  period_start: string;
  period_end: string;
  policy_id: string | null;
  policy_version: string | null;
  comparison_basis: string | null;
  sales_measure: string | null;
  gl_account_scope: string[];
  debit_credit_convention: string | null;
  currency_scope: string[];
  tolerance: string | null;
  blocked: boolean;
  block_reasons: string[];
  inconclusive: boolean;
  inconclusive_reasons: string[];
  recon_fingerprint: string;
  findings_fingerprint: string;
  summary: Record<string, unknown>;
  findings: DemoFinding[];
  conclusion: DemoConclusion;
}

export async function listDemoFixtures(): Promise<DemoFixturePayload[]> {
  return request<DemoFixturePayload[]>("/api/v1/demo-recon/fixtures");
}

export async function runDemoRecon(engagementId: string, fixtureId: string): Promise<DemoRunPayload> {
  return request<DemoRunPayload>(
    `/api/v1/engagements/${encodeURIComponent(engagementId)}/demo-recon-runs`,
    { method: "POST", body: JSON.stringify({ fixture_id: fixtureId }) }
  );
}

export interface DemoReportBinding {
  fixtureId: string;
  reconFingerprint: string;
  findingsFingerprint: string;
}

/** Download a deterministic, labelled demo report bound to the displayed run.
 *
 * The fingerprints are sent as expected values so the API refuses to export a
 * report that does not match what the reviewer is looking at. */
export async function downloadDemoReport(
  engagementId: string,
  binding: DemoReportBinding,
  format: "pdf" | "xlsx"
): Promise<void> {
  const params = new URLSearchParams({
    fixture_id: binding.fixtureId,
    format,
    expected_recon_fingerprint: binding.reconFingerprint,
    expected_findings_fingerprint: binding.findingsFingerprint
  });
  const res = await fetch(
    `/api/v1/engagements/${encodeURIComponent(engagementId)}/demo-recon-runs/report?${params.toString()}`
  );
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    let message = `Export failed: ${res.status}`;
    try {
      const body = (await res.json()) as ApiError;
      code = body.error.code;
      message = body.error.message;
    } catch {
      /* keep generic */
    }
    throw new ApiRequestError(code, message, res.status);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `synthetic-recon-${binding.fixtureId}.${format}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
