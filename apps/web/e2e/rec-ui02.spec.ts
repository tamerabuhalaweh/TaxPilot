import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * REC-UI-02 acceptance (real backend, synthetic fixtures only).
 *
 * Covers the accountant-facing polish found in the browser audit: real
 * navigation into reviews, a plain-language result summary, review-first
 * findings with "what to check next", honest report contents/language, Arabic
 * labels for UI chrome while engine text stays English, and mobile evidence.
 */

const START = "2026-01-01";
const END = "2026-09-30";
const FIXTURE_PERIOD_UI = "2026-01-01 – 2026-12-31";

async function signUpAndCreateReview(page: Page): Promise<void> {
  const email = `e2e-ui02-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;
  const password = "correct horse battery staple";

  await page.goto("/login");
  await page.getByRole("button", { name: "Need an account? Register" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByLabel("Firm name").fill("REC UI 02 Co");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL("/");

  await page.getByRole("link", { name: "Clients", exact: true }).click();
  await page.getByLabel("New client name").fill("Synthetic Client");
  await page.getByRole("button", { name: "Add Client" }).click();
  await expect(page.getByText("Synthetic Client")).toBeVisible();

  await page.getByRole("link", { name: "Reviews", exact: true }).click();
  await page.getByRole("link", { name: "New Review" }).click();
  await page.getByLabel("Period start").fill(START);
  await page.getByLabel("Period end").fill(END);
  await page.getByRole("button", { name: "Start Review" }).click();
  await expect(page).toHaveURL(/\/reviews\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "Review workspace" })).toBeVisible();
}

async function runScenario(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  await expect(page.getByText("Run summary")).toBeVisible();
}

test("dashboard, reviews index, and client detail open the real workspace", async ({ page }) => {
  await signUpAndCreateReview(page);
  const workspaceUrl = page.url();

  await page.getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await expect(page.getByText("Coming soon")).toHaveCount(0);
  await expect(page.getByText("Synthetic Client").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Open" }).first()).toBeVisible();

  await page.getByRole("link", { name: "Reviews", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Reviews" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Synthetic Client" })).toBeVisible();
  await page.getByRole("link", { name: "Open", exact: true }).click();
  await expect(page).toHaveURL(workspaceUrl);

  await page.getByRole("link", { name: "Clients", exact: true }).click();
  await page.getByRole("link", { name: "Open", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Synthetic Client" })).toBeVisible();
  await page.getByRole("tab", { name: "Reviews" }).click();
  await expect(page.getByRole("cell", { name: "Sales ↔ GL reconciliation" })).toBeVisible();
  await page.getByRole("link", { name: "Open", exact: true }).click();
  await expect(page).toHaveURL(workspaceUrl);
});

test("workspace states the client, conclusion, per-currency result, and next checks", async ({ page }) => {
  await signUpAndCreateReview(page);

  await expect(page.locator(".tp-workspace-meta")).toContainText("Synthetic Client");
  await expect(page.locator(".tp-workspace-meta")).toContainText("Sales ↔ GL reconciliation");
  await expect(page.locator(".tp-workspace-meta")).toContainText("Synthetic scenario");
  await expect(page.getByText(FIXTURE_PERIOD_UI).first()).toHaveAttribute("dir", "ltr");

  await runScenario(page);

  const conclusion = page.locator(".tp-conclusion");
  await expect(conclusion).toContainText("Review required");
  await expect(conclusion).toContainText("1 currency differs beyond tolerance: JOD");
  await expect(conclusion).toContainText("Coverage is incomplete for USD");

  const currencyRow = page.getByRole("row", { name: /JOD/ });
  await expect(currencyRow).toContainText("3500.000");
  await expect(currencyRow).toContainText("3400.000");
  await expect(currencyRow).toContainText("100.000");
  await expect(currencyRow).toContainText("Difference beyond tolerance");

  await expect(page.getByText("Equal totals are not proof of completeness").first()).toBeVisible();
  await expect(page.getByText(/Confirm coverage against both source registers/)).toBeVisible();

  await page.getByRole("tab", { name: "Findings" }).click();
  const findings = page.locator(".tp-finding");
  await expect(findings).toHaveCount(5);
  // Review-required and high severity come first, not the informational notes.
  await expect(findings.first()).toContainText("Sales and GL totals differ");
  await expect(findings.first().locator(".tp-sev")).toHaveClass(/tp-sev-high/);
  await expect(findings.first()).toContainText("What to check next");
  await expect(findings.first()).toContainText("Synthetic sales register");

  await page.getByRole("button", { name: "Informational (2)" }).click();
  await expect(page.locator(".tp-finding")).toHaveCount(2);
  await page.getByRole("button", { name: "All (5)" }).click();
  await expect(page.locator(".tp-finding")).toHaveCount(5);

  await findings.first().getByText("Technical details").click();
  await expect(findings.first()).toContainText("JO/REC-005/1");
  await expect(findings.first()).toContainText("Finding ID");
});

test("reports state their contents and exports carry the improved summary", async ({ page }) => {
  await signUpAndCreateReview(page);
  await runScenario(page);

  await page.getByRole("tab", { name: "Reports" }).click();
  await expect(page.getByRole("heading", { name: "What the report contains" })).toBeVisible();
  await expect(page.getByText("Review-ordered findings with what to check next")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Report language" })).toBeVisible();
  await expect(page.getByText(/PDF and XLSX reports are generated in English only/)).toBeVisible();
  await expect(page.getByText("If the run changes, the previous download is rejected as stale.")).toBeVisible();

  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export PDF" }).click();
  const download = await downloadEvent;
  const path = await download.path();
  if (!path) throw new Error("download has no local path");
  const text = readFileSync(path).toString("latin1");
  expect(text.startsWith("%PDF-")).toBe(true);
  expect(text).toContain("RESULT SUMMARY");
  expect(text).toContain("Review required");
  expect(text).toContain("Caution: Equal totals do not prove completeness");
  expect(text).toContain("What to check next:");
  expect(text).toContain("Page 1 of");
});

test("Arabic labels UI chrome while engine text stays English and evidence stacks on mobile", async ({
  page
}) => {
  await signUpAndCreateReview(page);
  await runScenario(page);

  await page.getByRole("button", { name: "العربية" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.getByRole("heading", { name: "مساحة عمل المراجعة" })).toBeVisible();
  await expect(page.locator(".tp-conclusion")).toContainText("تحتاج مراجعة");
  await expect(page.locator(".tp-conclusion")).toContainText("التغطية غير مكتملة لـ USD");
  await expect(page.getByText("تساوي الإجماليات ليس دليلاً على الاكتمال")).toBeVisible();
  await expect(page.getByText(FIXTURE_PERIOD_UI).first()).toHaveAttribute("dir", "ltr");

  await page.getByRole("tab", { name: "الملاحظات" }).click();
  const first = page.locator(".tp-finding").first();
  await expect(first.locator(".tp-sev")).toHaveText("عالية");
  await expect(first).toContainText("ما يجب فحصه تالياً");
  await expect(first).toContainText("نص المحرك (بالإنجليزية)");
  const engineTitle = first.locator(".tp-engine");
  await expect(engineTitle).toHaveAttribute("lang", "en");
  await expect(engineTitle).toContainText("Sales and GL totals differ");

  await page.setViewportSize({ width: 390, height: 844 });
  const stacked = await page.evaluate(
    () => getComputedStyle(document.querySelector(".tp-evidence tr") as HTMLElement).display
  );
  expect(stacked).toBe("block");
  const overflow = await page.evaluate(
    () => document.scrollingElement!.scrollWidth - document.documentElement.clientWidth
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
