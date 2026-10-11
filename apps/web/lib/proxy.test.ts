import { describe, expect, it } from "vitest";
import { PROXY_MAX_BODY_BYTES, bodyTooLarge, filterHeaders, readBoundedBody } from "./proxy";

describe("proxy policy", () => {
  it("forwards only allowlisted headers", () => {
    const out = filterHeaders([
      ["authorization", "Bearer x"],
      ["cookie", "tp_session=y"],
      ["x-request-id", "1"],
      ["x-csrf-token", "t"],
      ["x-forwarded-for", "1.2.3.4"],
      ["forwarded", "for=1.2.3.4"],
      ["host", "evil.example"],
      ["x-custom", "nope"]
    ]);
    expect(out).toEqual({
      authorization: "Bearer x",
      cookie: "tp_session=y",
      "x-request-id": "1",
      "x-csrf-token": "t"
    });
  });

  it("rejects oversized bodies by content-length", () => {
    expect(bodyTooLarge(String(2_000_000))).toBe(true);
    expect(bodyTooLarge("100")).toBe(false);
    expect(bodyTooLarge(null)).toBe(false);
    expect(bodyTooLarge("garbage")).toBe(false);
  });
});

function chunkedStream(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    }
  });
}

describe("bounded streaming reads", () => {
  it("passes small bodies through intact", async () => {
    const payload = new TextEncoder().encode(JSON.stringify({ hello: "world" }));
    const read = await readBoundedBody(chunkedStream([payload]), PROXY_MAX_BODY_BYTES);
    expect(read.ok).toBe(true);
    if (read.ok) expect(new TextDecoder().decode(read.bytes)).toBe(JSON.stringify({ hello: "world" }));
  });

  it("rejects oversized streams without a content-length", async () => {
    const big = new Uint8Array(PROXY_MAX_BODY_BYTES + 1).fill(120);
    const read = await readBoundedBody(chunkedStream([big.slice(0, 100), big.slice(100)]), PROXY_MAX_BODY_BYTES);
    expect(read.ok).toBe(false);
    if (!read.ok) expect(read.received).toBe(PROXY_MAX_BODY_BYTES + 1);
  });

  it("accepts a body of exactly the limit", async () => {
    const exact = new Uint8Array(PROXY_MAX_BODY_BYTES).fill(121);
    const read = await readBoundedBody(chunkedStream([exact]), PROXY_MAX_BODY_BYTES);
    expect(read.ok).toBe(true);
  });

  it("treats a null stream as empty", async () => {
    const read = await readBoundedBody(null, PROXY_MAX_BODY_BYTES);
    expect(read).toEqual({ ok: true, bytes: new Uint8Array(0) });
  });
});
