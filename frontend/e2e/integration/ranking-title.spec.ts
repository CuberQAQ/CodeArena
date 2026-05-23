// @integration
// Prerequisites: Docker Compose must be running with backend + frontend.
// Run: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
// Then: INTEGRATION_BASE_URL=http://localhost:9090 npx playwright test --project=integration e2e/integration/ranking-title.spec.ts

import { test, expect } from "@playwright/test";
import { screenshotPage } from "./helpers/screenshots";

/**
 * RankingPage title switching verification (FR-20.1, FR-21.3).
 * Verifies that the PageHeader title and description update dynamically
 * when switching between Global and Arena tabs.
 */

test.describe("RankingPage title switching (Integration)", () => {
  const suffix = Date.now();
  const username = `e2e_rank_${suffix}`;
  const email = `e2e_rank_${suffix}@test.com`;
  const password = "TestPass123!";  // pragma: allowlist secret

  test.describe.serial("Register -> Ranking page title verification", () => {
    test("register and navigate to ranking page", async ({ page }) => {
      // Register a new user
      await page.goto("/register");
      await page.waitForLoadState("networkidle");

      await page.fill("#username", username);
      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.fill("#confirmPassword", password);
      await page.click('button:has-text("Create Account")');

      await page.waitForURL("**/dashboard", { timeout: 15_000 });

      // Navigate to ranking page
      await page.goto("/ranking");
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);

      // Verify heading shows "Global Ranking" (default tab)
      const heading = page.getByRole("heading", { level: 1 });
      await expect(heading).toContainText("Global Ranking");

      await screenshotPage(page, "ranking-01-global-tab");
    });

    test("switch to arena tab shows Arena Ranking title", async ({ page }) => {
      // Login first
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.click('button:has-text("Sign In")');

      await page.waitForURL("**/dashboard", { timeout: 10_000 });

      // Navigate to ranking page
      await page.goto("/ranking");
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);

      // Click the Arena tab
      const arenaTab = page.locator('button:has-text("Arena")');
      await arenaTab.click();
      await page.waitForTimeout(2000);

      // Verify heading shows "Arena Ranking"
      const heading = page.getByRole("heading", { level: 1 });
      await expect(heading).toContainText("Arena Ranking");

      await screenshotPage(page, "ranking-02-arena-tab");
    });

    test("title updates when switching tabs back and forth", async ({ page }) => {
      // Login first
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.click('button:has-text("Sign In")');

      await page.waitForURL("**/dashboard", { timeout: 10_000 });

      // Navigate to ranking page
      await page.goto("/ranking");
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);

      const heading = page.getByRole("heading", { level: 1 });

      // Initially should show Global Ranking
      await expect(heading).toContainText("Global Ranking");

      // Switch to Arena tab
      await page.locator('button:has-text("Arena")').click();
      await page.waitForTimeout(2000);
      await expect(heading).toContainText("Arena Ranking");
      await expect(heading).not.toContainText("Global Ranking");

      // Switch back to Global tab
      await page.locator('button:has-text("Global")').click();
      await page.waitForTimeout(2000);
      await expect(heading).toContainText("Global Ranking");
      await expect(heading).not.toContainText("Arena Ranking");

      await screenshotPage(page, "ranking-03-switched-back-to-global");
    });

    test("description also switches correctly with tabs", async ({ page }) => {
      // Login first
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.click('button:has-text("Sign In")');

      await page.waitForURL("**/dashboard", { timeout: 10_000 });

      // Navigate to ranking page
      await page.goto("/ranking");
      await page.waitForLoadState("networkidle");
      await page.waitForTimeout(2000);

      // Global tab description should mention "CodeArena users and Codeforces"
      await expect(page.getByText(/CodeArena users and Codeforces/)).toBeVisible();

      // Switch to Arena tab
      await page.locator('button:has-text("Arena")').click();
      await page.waitForTimeout(2000);

      // Arena tab description should mention "CodeArena users only"
      await expect(page.getByText(/CodeArena users only/)).toBeVisible();

      await screenshotPage(page, "ranking-04-arena-description");
    });
  });
});
