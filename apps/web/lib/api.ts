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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init
  });
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

export async function listClients(): Promise<ClientPayload[]> {
  return request<ClientPayload[]>("/api/v1/clients");
}

export async function createClient(name: string): Promise<ClientPayload> {
  return request<ClientPayload>("/api/v1/clients", {
    method: "POST",
    body: JSON.stringify({ name })
  });
}
