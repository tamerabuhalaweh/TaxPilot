import { describe, expect, it } from "vitest";
import {
  clearEdgeBuckets,
  edgeClientKey,
  edgeLoginAllowed,
  edgeLoginHit,
  edgeRetryAfterMs,
  LOGIN_MAX_ATTEMPTS,
} from "./rate-limit";

describe("BFF edge login throttle", () => {
  it("keys on the last proxy hop, ignoring spoofed left entries", () => {
    expect(edgeClientKey(null)).toBe("direct");
    expect(edgeClientKey("203.0.113.7")).toBe("203.0.113.7");
    // Attacker-controlled prefixes never select the bucket.
    expect(edgeClientKey("198.51.100.9, 203.0.113.7")).toBe("203.0.113.7");
    expect(edgeClientKey(" 198.51.100.9 ,, 203.0.113.7 ")).toBe("203.0.113.7");
  });

  it("allows a generous burst per window per key, independently", () => {
    const store = new Map<string, number[]>();
    const now = 1_000_000;
    for (let i = 0; i < LOGIN_MAX_ATTEMPTS; i++) {
      expect(edgeLoginAllowed("a", now + i * 100, store)).toBe(true);
      edgeLoginHit("a", now + i * 100, store);
    }
    expect(edgeLoginAllowed("a", now + LOGIN_MAX_ATTEMPTS * 100, store)).toBe(false);
    expect(edgeLoginAllowed("b", now + LOGIN_MAX_ATTEMPTS * 100, store)).toBe(true);
    expect(edgeRetryAfterMs("a", now + LOGIN_MAX_ATTEMPTS * 100, store)).toBeGreaterThan(0);
  });

  it("slides the window and reports zero retry when clear", () => {
    const store = new Map<string, number[]>();
    edgeLoginHit("a", 0, store);
    expect(edgeRetryAfterMs("a", 16 * 60 * 1000, store)).toBe(0);
    expect(edgeLoginAllowed("a", 16 * 60 * 1000, store)).toBe(true);
    clearEdgeBuckets(store);
  });
});
