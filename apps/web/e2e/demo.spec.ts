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
  await page.getByRole("tab", { name: "Findings" }).click();
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

test("demo review statuses are translated, never raw codes", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("In progress").first()).toBeVisible();
  await page.getByRole("button", { name: "العربية" }).click();
  await expect(page.getByText("قيد التنفيذ").first()).toBeVisible();
  await expect(page.getByText("معتمدة").first()).toBeVisible();
  await expect(page.getByText("in progress")).toHaveCount(0);
  await expect(page.getByText("approved")).toHaveCount(0);
});

test("demo navigation highlights section parents on nested routes", async ({ page }) => {
  await page.goto("/clients/demo-client-1");
  await expect(page.getByRole("link", { name: "Clients", exact: true })).toHaveAttribute(
    "aria-current",
    "page"
  );
  await page.goto("/reviews/new");
  await expect(page.getByRole("link", { name: "Reviews", exact: true })).toHaveAttribute(
    "aria-current",
    "page"
  );
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Dashboard", exact: true })).toHaveAttribute(
    "aria-current",
    "page"
  );
});

test("demo tabs support arrow, home, and end keys with aria linkage", async ({ page }) => {
  await page.goto("/clients/demo-client-1");
  const documents = page.getByRole("tab", { name: "Documents" });
  const findings = page.getByRole("tab", { name: "Findings" });
  const reports = page.getByRole("tab", { name: "Reports" });
  await expect(documents).toHaveAttribute("aria-selected", "false");
  // Establish selection first (roving tabindex keeps focus on the selected tab).
  await documents.click();
  await expect(documents).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight");
  await expect(findings).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("End");
  await expect(reports).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(page.getByRole("tab", { name: "Profile" })).toHaveAttribute("aria-selected", "true");
  // Tab-panel linkage resolves to the visible panel.
  const panelId = await reports.getAttribute("aria-controls");
  await page.keyboard.press("End");
  await expect(page.locator(`[id="${panelId}"]`)).toHaveAttribute("role", "tabpanel");
});

test("demo tabs wrap selection and focus together at boundaries", async ({ page }) => {
  await page.goto("/clients/demo-client-1");
  const profile = page.getByRole("tab", { name: "Profile" });
  const reports = page.getByRole("tab", { name: "Reports" });
  await reports.click();
  await expect(reports).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowRight"); // wraps last -> first
  await expect(profile).toHaveAttribute("aria-selected", "true");
  await expect(profile).toBeFocused();
  await page.keyboard.press("ArrowLeft"); // wraps first -> last
  await expect(reports).toHaveAttribute("aria-selected", "true");
  await expect(reports).toBeFocused();
});

test("demo tabs keyboard works in RTL with mirrored arrows", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "العربية" }).click();
  await page.goto("/clients/demo-client-1");
  const docs = page.getByRole("tab", { name: "المستندات" });
  const findings = page.getByRole("tab", { name: "الملاحظات" });
  await docs.click();
  await expect(docs).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowLeft"); // forward in RTL
  await expect(findings).toHaveAttribute("aria-selected", "true");
  await expect(findings).toBeFocused();
  await page.keyboard.press("ArrowRight"); // back in RTL
  await expect(docs).toHaveAttribute("aria-selected", "true");
  await expect(docs).toBeFocused();
});

test("demo reload keeps the truthful no-save message", async ({ page }) => {
  await page.goto("/reviews/new");
  const message = "selections are not saved";
  await expect(page.getByText(message)).toBeVisible();
  await page.reload();
  await expect(page.getByText(message)).toBeVisible();
});

test("demo archived clients are inspectable via the status filter", async ({ page }) => {
  await page.goto("/clients");
  await expect(page.getByText("Amman Consulting Group")).toBeHidden();
  await page.getByRole("button", { name: "Archived", exact: true }).click();
  await expect(page.getByText("Amman Consulting Group")).toBeVisible();
  await page.getByRole("button", { name: "All", exact: true }).click();
  await expect(page.getByText("Example Trading LLC")).toBeVisible();
  await expect(page.getByText("Amman Consulting Group")).toBeVisible();
});
