import { expect, test } from "@playwright/test";

/**
 * REC-UI-01 acceptance (real backend). CI enables the restricted synthetic demo
 * (TAXPILOT_DEMO_RECON_ENABLED=1). Journey: register → create client → start a
 * review → run the deterministic synthetic scenario → inspect findings with
 * source-row evidence → export a labelled PDF and XLSX. Synthetic data only.
 */
test("synthetic reconciliation walkthrough with labelled exports", async ({ page }) => {
  const email = `e2e-rec-${Date.now()}@example.com`;
  const password = "correct horse battery staple";

  await page.goto("/login");
  await page.getByRole("button", { name: "Need an account? Register" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByLabel("Firm name").fill("REC UI Co");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL("/");

  await page.getByRole("link", { name: "Clients", exact: true }).click();
  await page.getByLabel("New client name").fill("Synthetic Client");
  await page.getByRole("button", { name: "Add Client" }).click();
  await expect(page.getByText("Synthetic Client")).toBeVisible();

  await page.getByRole("link", { name: "Reviews", exact: true }).click();
  await page.getByRole("link", { name: "New Review" }).click();
  await expect(page.getByRole("heading", { name: "New Review" })).toBeVisible();
  await page.getByLabel("Period start").fill("2026-01-01");
  await page.getByLabel("Period end").fill("2026-09-30");
  await page.getByRole("button", { name: "Start Review" }).click();
  await expect(page).toHaveURL(/\/reviews\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "Review workspace" })).toBeVisible();

  await page.getByRole("button", { name: "Run reconciliation" }).click();
  await expect(page.getByText("Run summary")).toBeVisible();
  const stats = page.locator(".tp-stat");
  await expect(stats).toHaveCount(4);
  await expect(stats.nth(0)).toContainText("5");
  await expect(stats.nth(1)).toContainText("3");
  await expect(page.locator(".tp-synth").first()).toContainText("SYNTHETIC DEMO DATA");

  await page.getByRole("tab", { name: "Findings" }).click();
  await expect(page.locator(".tp-finding")).toHaveCount(5);
  await expect(page.locator("table.tp-table tbody tr").first()).toBeVisible();

  await page.getByRole("tab", { name: "Reports" }).click();
  const pdf = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PDF" }).click();
  expect((await pdf).suggestedFilename()).toMatch(/^synthetic-recon-.*\.pdf$/);
  const xlsx = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export XLSX" }).click();
  expect((await xlsx).suggestedFilename()).toMatch(/^synthetic-recon-.*\.xlsx$/);
});

test("review workspace prompts sign-in when unauthenticated", async ({ page }) => {
  await page.goto("/reviews/00000000-0000-0000-0000-000000000000");
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
});
