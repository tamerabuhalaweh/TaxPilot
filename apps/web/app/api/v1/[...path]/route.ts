import { NextRequest, NextResponse } from "next/server";

/**
 * Same-origin API proxy (Backend-for-Frontend).
 *
 * The browser calls /api/* on this host; this handler forwards server-side to a
 * fixed, deploy-configured backend (API_INTERNAL_URL). The destination host comes
 * ONLY from server environment — never from request input — so this cannot be
 * abused as an open proxy. Failures map to 502 without leaking backend details.
 */
const HOP_HEADERS = new Set(["host", "connection", "content-length", "transfer-encoding"]);
const TIMEOUT_MS = 10_000;

function backendBase(): string {
  return process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";
}

async function forward(req: NextRequest, segments: string[], method: string): Promise<NextResponse> {
  const url = `${backendBase()}/api/v1/${segments.join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  req.headers.forEach((value, key) => {
    if (!HOP_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const body = method === "GET" || method === "HEAD" ? undefined : await req.arrayBuffer();
    const res = await fetch(url, { method, headers, body, signal: controller.signal });
    const buf = await res.arrayBuffer();
    return new NextResponse(buf, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") ?? "application/json" }
    });
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
