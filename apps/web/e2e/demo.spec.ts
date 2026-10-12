import { expect, test } from "@playwright/test";

/**
 * Demo-build smoke (NEXT_PUBLIC_PREVIEW_MODE=demo, no backend).
 * Proves the deployed visual-preview configuration: persistent banner, synthetic
 * clients, honest disabled operations, AR persistence, mobile layout, and zero
 * authentication traffic. Runs in its own CI job against a demo build.
 */
test("demo banner is persistent and content is synthetic", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".tp-demo-banner")).toContainText("Preview only");
  await expect(page.getByText("Example Trading LLC").first()).toBeVisible();
});

test("demo clients search and detail work without a backend", async ({ page }) => {
  await page.goto("/clients");
  await page.getByLabel("Search clients").fill("food");
  await expect(page.getByText("Jordan Food Industries")).toBeVisible();
  await expect(page.getByText("Example Trading LLC")).toBeHidden();
  await page.getByLabel("Search clients").fill("");
  await page.getByRole("link", { name: "Open" }).first().click();
  await expect(page.getByRole("tab", { name: "Findings" })).toBeVisible();
  await expect(page.getByText("Coming soon").first()).toBeVisible();
});

test("demo new review shows sources with a disabled run", async ({ page }) => {
  await page.goto("/reviews/new");
  await expect(page.getByText("Sales Register")).toBeVisible();
  await expect(page.getByText("JoFotara Excel Export")).toBeVisible();
  await expect(page.getByText("General Ledger")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start Review" })).toBeDisabled();
});

test("demo auth is fully disabled with zero backend auth traffic", async ({ page }) => {
  const authCalls: string[] = [];
  page.on("request", (req) => {
    if (req.url().includes("/api/v1/auth/")) authCalls.push(req.url());
  });
  await page.goto("/login");
  await expect(page.locator("form")).toHaveCount(0);
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Explore the demo workspace" })).toBeVisible();
  // The page itself issued no authentication traffic (no form exists to submit).
  expect(authCalls).toEqual([]);
  // Even a direct call is fail-closed at the proxy without backend contact.
  const status = await page.evaluate(async () => {
    const res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: "a@b.c", password: "x".repeat(12) })
    });
    return { status: res.status, code: ((await res.json()) as { error: { code: string } }).error.code };
  });
  expect(status).toEqual({ status: 403, code: "FEATURE_DISABLED" });
});

test("demo locale persists across navigation, reload, and mobile layout", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "العربية" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await page.getByRole("link", { name: "العملاء", exact: true }).click();
  await expect(page).toHaveURL("/clients");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "العملاء" })).toBeVisible();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(
    () => document.scrollingElement!.scrollWidth - document.documentElement.clientWidth
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
