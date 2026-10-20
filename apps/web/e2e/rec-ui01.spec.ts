import { readFileSync } from "node:fs";
import { inflateRawSync } from "node:zlib";

import { expect, test, type Page } from "@playwright/test";

/**
 * REC-UI-01 acceptance (real backend). CI enables the restricted synthetic demo
 * (TAXPILOT_DEMO_RECON_ENABLED=1). Journey: register → create client → start a
 * review → run the deterministic synthetic scenario → inspect findings with
 * source-row evidence → switch scenarios → verify the exported PDF/XLSX bytes.
 * Synthetic data only.
 */

const ENGAGEMENT_START = "2026-01-01";
const ENGAGEMENT_END = "2026-09-30";
const FIXTURE_PERIOD = "2026-01-01 to 2026-12-31";
const FIXTURE_PERIOD_UI = "2026-01-01 – 2026-12-31";
const FIXTURE_ID_V1 = "synthetic-sales-gl-v1";
const FIXTURE_ID_V2 = "synthetic-sales-gl-v2";

/** Minimal ZIP reader (central directory) so the test can inspect real XLSX XML. */
function unzip(buffer: Buffer): Map<string, Buffer> {
  const files = new Map<string, Buffer>();
  let eocd = -1;
  for (let i = buffer.length - 22; i >= 0; i -= 1) {
    if (buffer.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("not a ZIP archive");
  const count = buffer.readUInt16LE(eocd + 10);
  let pointer = buffer.readUInt32LE(eocd + 16);
  for (let entry = 0; entry < count; entry += 1) {
    if (buffer.readUInt32LE(pointer) !== 0x02014b50) throw new Error("bad central directory");
    const method = buffer.readUInt16LE(pointer + 10);
    const compressedSize = buffer.readUInt32LE(pointer + 20);
    const nameLength = buffer.readUInt16LE(pointer + 28);
    const extraLength = buffer.readUInt16LE(pointer + 30);
    const commentLength = buffer.readUInt16LE(pointer + 32);
    const localOffset = buffer.readUInt32LE(pointer + 42);
    const name = buffer.subarray(pointer + 46, pointer + 46 + nameLength).toString("utf8");
    const localNameLength = buffer.readUInt16LE(localOffset + 26);
    const localExtraLength = buffer.readUInt16LE(localOffset + 28);
    const dataStart = localOffset + 30 + localNameLength + localExtraLength;
    const raw = buffer.subarray(dataStart, dataStart + compressedSize);
    files.set(name, method === 0 ? Buffer.from(raw) : inflateRawSync(raw));
    pointer += 46 + nameLength + extraLength + commentLength;
  }
  return files;
}

async function downloadBytes(page: Page, name: string): Promise<{ filename: string; bytes: Buffer; text: string }> {
  const event = page.waitForEvent("download");
  await page.getByRole("button", { name }).click();
  const download = await event;
  const path = await download.path();
  if (!path) throw new Error(`download ${name} has no local path`);
  const bytes = readFileSync(path);
  return { filename: download.suggestedFilename(), bytes, text: bytes.toString("latin1") };
}

async function signUpAndCreateReview(page: Page): Promise<string> {
  const email = `e2e-rec-${Date.now()}-${Math.random().toString(16).slice(2)}@example.com`;
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
  await page.getByLabel("Period start").fill(ENGAGEMENT_START);
  await page.getByLabel("Period end").fill(ENGAGEMENT_END);
  await page.getByRole("button", { name: "Start Review" }).click();
  await expect(page).toHaveURL(/\/reviews\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: "Review workspace" })).toBeVisible();
  return page.url();
}

test("synthetic reconciliation walkthrough binds exports to the displayed run", async ({ page }) => {
  await signUpAndCreateReview(page);

  // F2: the engagement period and the scenario's fixed comparison period are
  // shown as separate facts, with an explicit mismatch notice.
  await expect(page.getByText("Engagement period").first()).toBeVisible();
  await expect(page.getByText("Scenario comparison period").first()).toBeVisible();
  await expect(page.getByText(FIXTURE_PERIOD_UI)).toBeVisible();
  await expect(page.getByText(/does not read the engagement period/)).toBeVisible();

  await page.getByRole("button", { name: "Run reconciliation" }).click();
  await expect(page.getByText("Run summary")).toBeVisible();
  const stats = page.locator(".tp-stat");
  await expect(stats).toHaveCount(4);
  await expect(stats.nth(0)).toContainText("5");
  await expect(stats.nth(1)).toContainText("3");
  await expect(page.locator(".tp-synth").first()).toContainText("SYNTHETIC DEMO DATA");
  await expect(page.getByText(FIXTURE_ID_V1)).toBeVisible();

  await page.getByRole("tab", { name: "Findings" }).click();
  await expect(page.locator(".tp-finding")).toHaveCount(5);
  await expect(page.locator("table.tp-table tbody tr").first()).toBeVisible();

  // F1: changing the scenario invalidates the displayed run; nothing stale and
  // nothing exportable survives the switch.
  await page.getByRole("tab", { name: "Reconciliation" }).click();
  await page.getByLabel("Synthetic scenario").selectOption(FIXTURE_ID_V2);
  await expect(page.getByText("Run summary")).toHaveCount(0);
  await expect(page.getByText("No run yet")).toBeVisible();
  await page.getByRole("tab", { name: "Reports" }).click();
  await expect(page.getByRole("button", { name: "Export PDF" })).toHaveCount(0);
  await expect(page.getByText("No run yet")).toBeVisible();

  await page.getByRole("tab", { name: "Reconciliation" }).click();
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  await expect(page.getByText("Run summary")).toBeVisible();
  await expect(page.locator(".tp-stat").nth(0)).toContainText("1");
  await expect(page.getByText("50.000 JOD", { exact: true })).toBeVisible();
  await expect(page.getByText(FIXTURE_ID_V2)).toBeVisible();
  const fingerprint = /[0-9a-f]{12}/.exec(await page.getByText(/Findings fingerprint/).first().innerText());
  expect(fingerprint).not.toBeNull();

  await page.getByRole("tab", { name: "Findings" }).click();
  await expect(page.locator(".tp-finding")).toHaveCount(1);

  // F3: inspect the real PDF bytes from the export route.
  await page.getByRole("tab", { name: "Reports" }).click();
  await expect(page.getByText("Exports are bound to this run")).toBeVisible();
  const pdf = await downloadBytes(page, "Export PDF");
  expect(pdf.filename).toBe(`synthetic-recon-${FIXTURE_ID_V2}.pdf`);
  expect(pdf.text.startsWith("%PDF-")).toBe(true);
  expect(pdf.text).toContain("SYNTHETIC DEMO DATA - NOT CUSTOMER RECORDS / NOT A TAX FILING");
  expect(pdf.text).toContain(`Engagement period: ${ENGAGEMENT_START} to ${ENGAGEMENT_END}`);
  expect(pdf.text).toContain(`Fixture comparison period: ${FIXTURE_PERIOD}`);
  expect(pdf.text).toContain("50.000");
  expect(pdf.text).toContain("INV-2001");
  expect(pdf.text).toContain(fingerprint![0]);

  // F3: inspect the real XLSX bytes (Summary/Findings/Evidence content).
  const xlsx = await downloadBytes(page, "Export XLSX");
  expect(xlsx.filename).toBe(`synthetic-recon-${FIXTURE_ID_V2}.xlsx`);
  const entries = unzip(xlsx.bytes);
  const workbook = entries.get("xl/workbook.xml")?.toString("utf8") ?? "";
  for (const sheet of ["Summary", "Findings", "Evidence"]) {
    expect(workbook).toContain(`name="${sheet}"`);
  }
  const xml = [...entries.values()].map((entry) => entry.toString("utf8")).join("\n");
  expect(xml).toContain("SYNTHETIC DEMO DATA");
  expect(xml).toContain("NOT CUSTOMER RECORDS / NOT A TAX FILING");
  expect(xml).toContain("Engagement period");
  expect(xml).toContain("Fixture comparison period");
  expect(xml).toContain(`${ENGAGEMENT_START} to ${ENGAGEMENT_END}`);
  expect(xml).toContain(FIXTURE_PERIOD);
  expect(xml).toContain("50.000");
  expect(xml).toContain("INV-2001");
  expect(xml).toContain(fingerprint![0]);
});

test("an in-flight run from a previous scenario cannot overwrite the new selection", async ({ page }) => {
  await signUpAndCreateReview(page);

  let held = false;
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let resumed: () => void = () => undefined;
  const continued = new Promise<void>((resolve) => {
    resumed = resolve;
  });

  await page.route("**/api/v1/engagements/*/demo-recon-runs", async (route) => {
    if (!held && route.request().method() === "POST") {
      held = true;
      await gate;
      await route.continue();
      resumed();
      return;
    }
    await route.continue();
  });

  const firstResponse = page.waitForResponse(
    (response) => response.url().includes("/demo-recon-runs") && response.request().method() === "POST"
  );
  await page.getByRole("button", { name: "Run reconciliation" }).click();
  await expect(page.getByRole("button", { name: "Running…" })).toBeVisible();

  // Switch while the first run is still in flight.
  await page.getByLabel("Synthetic scenario").selectOption(FIXTURE_ID_V2);
  release();
  await firstResponse;
  await continued;

  await expect(page.getByText("Run summary")).toHaveCount(0);
  await expect(page.getByText("No run yet")).toBeVisible();
  await expect(page.getByLabel("Synthetic scenario")).toHaveValue(FIXTURE_ID_V2);
});

test("Arabic workspace is RTL and keeps the synthetic labels", async ({ page }) => {
  await signUpAndCreateReview(page);

  await page.getByRole("button", { name: "العربية" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("html")).toHaveAttribute("lang", "ar");
  await expect(page.getByRole("heading", { name: "مساحة عمل المراجعة" })).toBeVisible();
  await expect(page.getByText("فترة المراجعة").first()).toBeVisible();
  await expect(page.getByText("فترة مقارنة السيناريو").first()).toBeVisible();
  await expect(page.locator(".tp-synth").first()).toContainText("SYNTHETIC DEMO DATA");

  await page.getByRole("button", { name: "تشغيل التسوية" }).click();
  await expect(page.getByText("ملخص التشغيل")).toBeVisible();
  await expect(page.locator(".tp-stat").nth(0)).toContainText("5");
  await page.getByRole("tab", { name: "الملاحظات" }).click();
  await expect(page.locator(".tp-finding")).toHaveCount(5);
});

test("review workspace prompts sign-in when unauthenticated", async ({ page }) => {
  await page.goto("/reviews/00000000-0000-0000-0000-000000000000");
  await expect(page.getByRole("link", { name: "Sign in" })).toBeVisible();
});
