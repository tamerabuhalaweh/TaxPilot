import { expect, test } from "@playwright/test";

/**
 * Sprint 1 vertical slice (EP-02/EP-03 evidence): register (dev auto-verify) →
 * dashboard with workspace → create client → sign out → sign-in gate returns.
 * Synthetic credentials only; the suite never touches real user data.
 */
test("register, manage a client, sign out and back in", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;
  const password = "correct horse battery staple";

  await page.goto("/login");
  await page.getByRole("button", { name: "Need an account? Register" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByLabel("Firm name").fill("E2E Accounting");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText(email)).toBeVisible();

  await page.getByRole("link", { name: "Clients", exact: true }).click();
  await expect(page).toHaveURL("/clients");
  await page.getByLabel("New client name").fill("E2E Client");
  await page.getByRole("button", { name: "Add Client" }).click();
  await expect(page.getByText("E2E Client")).toBeVisible();
  await page.getByRole("link", { name: "Dashboard" }).click();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByText("E2E Client")).toBeVisible();
});
