import { defineConfig } from "@playwright/test";

/**
 * Browser journey tests. The API + web servers are started by the caller
 * (CI `browser` job or local run) so backend-up vs backend-down states are
 * deterministic. See package.json scripts: e2e (assumes servers up).
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000"
  },
  reporter: "line"
});
