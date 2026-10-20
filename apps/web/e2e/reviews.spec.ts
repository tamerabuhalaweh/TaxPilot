import { expect, test } from "@playwright/test";

/**
 * Sprint 0 journey parts that survive the Sprint 1 session gate (P0-E evidence
 * stays valid): backend failure shows a useful error, AR/EN layout works, and the
 * primary action navigates somewhere real. Authenticated flows live in auth.spec.ts.
 */
test("unauthenticated dashboard prompts sign-in, not an empty workspace", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
});

test("connected dashboard reports real workspace counts, never placeholder KPIs", async ({ page }) => {
  // Register + sign in through the real backend, then inspect the dashboard.
  const email = `e2e-metrics-${Date.now()}@example.com`;
  const password = "correct horse battery staple";
  await page.goto("/login");
  await page.getByRole("button", { name: "Need an account? Register" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByLabel("Firm name").fill("Metrics Co");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL("/");
  // A fresh workspace really has zero clients and reviews: measured zeros, not
  // invented "coming soon" placeholders.
  await expect(page.getByText("Coming soon")).toHaveCount(0);
  const stats = page.locator(".tp-stat-value");
  await expect(stats).toHaveCount(4);
  for (const cell of await stats.all()) {
    await expect(cell).toHaveText("0");
  }
  await expect(page.getByText("No reviews yet. Start one from the New Review page.")).toBeVisible();
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

test("new review shows the planned journey with three source types", async ({ page }) => {
  await page.goto("/reviews/new");
  await expect(page).toHaveURL(/\/reviews\/new/);
  await expect(page.getByRole("heading", { name: "New Review" })).toBeVisible();
  await expect(page.getByText("Sales Register")).toBeVisible();
  await expect(page.getByText("JoFotara Excel Export")).toBeVisible();
  await expect(page.getByText("General Ledger")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start Review" })).toBeDisabled();
});
