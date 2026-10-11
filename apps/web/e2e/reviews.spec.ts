import { expect, test } from "@playwright/test";

/**
 * Sprint 0 user journey (P0-E evidence):
 * page loads → reaches backend (same-origin proxy) → backend failure shows a
 * useful error → AR/EN layout works → primary action navigates somewhere real.
 */
test("dashboard loads and shows backend-connected state", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Backend connected")).toBeVisible();
});

test("backend failure shows a useful error state, not a hang", async ({ page }) => {
  await page.route("/api/**", (route) => route.abort());
  await page.goto("/");
  await expect(page.locator(".tp-alert")).toContainText("Backend unreachable");
});

test("arabic toggle switches layout to RTL with translated strings", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "العربية" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "لوحة التحكم" })).toBeVisible();
});

test("new review navigates to an honestly labeled placeholder", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "New Review" }).click();
  await expect(page).toHaveURL(/\/reviews\/new/);
  await expect(page.getByRole("heading", { name: /coming in Sprint 1/ })).toBeVisible();
});
