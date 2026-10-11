import { describe, expect, it } from "vitest";
import { bodyTooLarge, filterHeaders } from "./proxy";

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
