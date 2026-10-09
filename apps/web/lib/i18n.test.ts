import { describe, expect, it } from "vitest";
import { dirOf, t } from "./i18n";

describe("i18n foundation", () => {
  it("resolves English and Arabic strings", () => {
    expect(t("en", "dashboard.newReview")).toBe("New Review");
    expect(t("ar", "dashboard.newReview")).toBe("مراجعة جديدة");
  });

  it("falls back to English for unknown keys", () => {
    expect(t("ar", "nope.missing")).toBe("nope.missing");
  });

  it("maps Arabic to RTL", () => {
    expect(dirOf("ar")).toBe("rtl");
    expect(dirOf("en")).toBe("ltr");
  });
});
