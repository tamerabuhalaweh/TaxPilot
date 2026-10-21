import { NextRequest, NextResponse } from "next/server";
import {
  PROXY_MAX_BODY_BYTES,
  PROXY_MAX_RESPONSE_BYTES,
  bodyTooLarge,
  edgeHeaders,
  filterHeaders,
  readBoundedBody
} from "../../../../lib/proxy";

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
  // Demo builds have no backend and no accounts: auth traffic is fail-closed
  // here so no credential-bearing request can ever leave the preview host.
  // Connected builds leave this path untouched.
  if (process.env.NEXT_PUBLIC_PREVIEW_MODE === "demo" && segments[0] === "auth") {
    return NextResponse.json(
      { error: { code: "FEATURE_DISABLED", message: "Sign-in is disabled in this visual preview." } },
      { status: 403 }
    );
  }
  const url = `${backendBase()}/api/v1/${segments.join("/")}${req.nextUrl.search}`;
  // Server-only trust marker for the hosted API. Never accept or forward this
  // from the browser; the BFF owns it (filterHeaders drops any client copy).
  const headers = { ...filterHeaders(req.headers.entries()), ...edgeHeaders(process.env.API_EDGE_SECRET) };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    let body: ArrayBuffer | undefined;
    if (method !== "GET" && method !== "HEAD") {
      // Bounded streaming read (R2): enforced even when Content-Length is
      // missing or lies. Oversized bodies are rejected here, never forwarded.
      const read = await readBoundedBody(req.body, PROXY_MAX_BODY_BYTES);
      if (!read.ok) {
        return NextResponse.json(
          { error: { code: "PAYLOAD_TOO_LARGE", message: "Request body exceeds the allowed size." } },
          { status: 413 }
        );
      }
      body = read.bytes.buffer as ArrayBuffer;
    }
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
