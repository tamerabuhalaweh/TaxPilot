import { expect, test } from "@playwright/test";
import http from "node:http";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3000";

function chunkedPost(path: string, totalBytes: number, chunkBytes = 65536): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const target = new URL(path, BASE);
    const req = http.request(
      {
        hostname: target.hostname,
        port: Number(target.port),
        path: target.pathname,
        method: "POST",
        headers: { "content-type": "application/json", "transfer-encoding": "chunked" }
      },
      (res) => {
        let text = "";
        res.on("data", (c) => (text += c));
        res.on("end", () => resolve({ status: res.statusCode ?? 0, body: text }));
      }
    );
    req.on("error", reject);
    let sent = 0;
    const chunk = Buffer.alloc(Math.min(chunkBytes, totalBytes), 120);
    while (sent < totalBytes) {
      const piece = chunk.subarray(0, Math.min(chunk.length, totalBytes - sent));
      req.write(piece);
      sent += piece.length;
    }
    req.end();
  });
}

test("chunked body without content-length under the limit is forwarded", async () => {
  // 1 KiB, no Content-Length: the proxy must stream it through. The backend
  // answers 422 (opaque bytes are not JSON) — the point is the proxy forwarded
  // instead of rejecting.
  const { status } = await chunkedPost("/api/v1/clients", 1024);
  expect(status).toBe(422);
});

test("chunked oversized body without content-length is rejected, not forwarded", async () => {
  const { status, body } = await chunkedPost("/api/v1/clients", 2 * 1024 * 1024);
  expect(status).toBe(413);
  expect(body).toContain("PAYLOAD_TOO_LARGE");
});
