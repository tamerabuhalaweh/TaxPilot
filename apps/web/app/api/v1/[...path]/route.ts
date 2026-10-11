import { NextRequest, NextResponse } from "next/server";
import { PROXY_MAX_RESPONSE_BYTES, bodyTooLarge, filterHeaders } from "../../../../lib/proxy";
import { edgeClientKey, edgeLoginAllowed, edgeLoginHit, edgeRetryAfterMs } from "../../../../lib/rate-limit";

/**
 * Same-origin API proxy (Backend-for-Frontend).
 *
 * The browser calls /api/* on this host; this handler forwards server-side to a
 * fixed, deploy-configured backend (API_INTERNAL_URL). The destination host comes
 * ONLY from server environment — never from request input — so this cannot be
 * abused as an open proxy. Only allowlisted headers are forwarded (no untrusted
 * x-forwarded-*, no hop headers). Failures map to 502 without backend details.
 */
const TIMEOUT_MS = 10_000;

function backendBase(): string {
  return process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
}

async function forward(req: NextRequest, segments: string[], method: string): Promise<NextResponse> {
  if (bodyTooLarge(req.headers.get("content-length"))) {
    return NextResponse.json(
      { error: { code: "PAYLOAD_TOO_LARGE", message: "Request body exceeds the allowed size." } },
      { status: 413 }
    );
  }
  // Edge login throttle (P0-B): per observed-peer key, before touching the backend.
  // The backend keeps authoritative per-email limiting; this tier stops sprays.
  if (method === "POST" && segments.join("/") === "auth/login") {
    const key = edgeClientKey(req.headers.get("x-forwarded-for"));
    const now = Date.now();
    if (!edgeLoginAllowed(key, now)) {
      const waitSecs = Math.ceil(edgeRetryAfterMs(key, now) / 1000);
      return NextResponse.json(
        { error: { code: "RATE_LIMITED", message: "Too many attempts. Try again later." } },
        { status: 429, headers: { "Retry-After": String(waitSecs) } }
      );
    }
    edgeLoginHit(key, now);
  }
  const url = `${backendBase()}/api/v1/${segments.join("/")}${req.nextUrl.search}`;
  const headers = filterHeaders(req.headers.entries());
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const body = method === "GET" || method === "HEAD" ? undefined : await req.arrayBuffer();
    const res = await fetch(url, { method, headers, body, signal: controller.signal });
    const buf = await res.arrayBuffer();
    if (buf.byteLength > PROXY_MAX_RESPONSE_BYTES) {
      return NextResponse.json(
        { error: { code: "BAD_GATEWAY", message: "Backend response too large." } },
        { status: 502 }
      );
    }
    // set-cookie values are forwarded explicitly (all of them: session + CSRF):
    // the backend owns session issuance and the browser stays same-origin, so
    // no third-party cookie exposure occurs.
    const outgoing = new Headers({ "content-type": res.headers.get("content-type") ?? "application/json" });
    const headersWithCookies = res.headers as Headers & { getSetCookie?: () => string[] };
    const setCookies =
      typeof headersWithCookies.getSetCookie === "function"
        ? headersWithCookies.getSetCookie()
        : res.headers.get("set-cookie")
          ? [res.headers.get("set-cookie") as string]
          : [];
    for (const cookie of setCookies) outgoing.append("set-cookie", cookie);
    return new NextResponse(buf, { status: res.status, headers: outgoing });
  } catch {
    return NextResponse.json(
      { error: { code: "BACKEND_UNREACHABLE", message: "Backend is unreachable. Try again shortly." } },
      { status: 502 }
    );
  } finally {
    clearTimeout(timer);
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return forward(req, (await ctx.params).path, "GET");
}

export async function POST(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return forward(req, (await ctx.params).path, "POST");
}

export async function PUT(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return forward(req, (await ctx.params).path, "PUT");
}

export async function PATCH(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return forward(req, (await ctx.params).path, "PATCH");
}

export async function DELETE(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  return forward(req, (await ctx.params).path, "DELETE");
}
