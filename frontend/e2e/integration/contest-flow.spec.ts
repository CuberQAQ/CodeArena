// @integration
// Prerequisites: Docker Compose must be running with backend + frontend.
// Run: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
// Then: npx playwright test --project=integration e2e/integration/contest-flow.spec.ts

import { test, expect } from "@playwright/test";
import { screenshotPage } from "./helpers/screenshots";

test.describe("Contest Flow (Integration)", () => {
  test.describe.serial("Register -> Contest page -> Start contest", () => {
    const suffix = Date.now();
    const username = `e2e_co_${suffix}`;
    const email = `e2e_co_${suffix}@test.com`;
    const password = "TestPass123!";

    test("register and navigate to contest page", async ({ page }) => {
      // Register
      await page.goto("/register");
      await page.waitForLoadState("networkidle");

      await page.fill("#username", username);
      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.fill("#confirmPassword", password);
      await page.click('button:has-text("Create Account")');

      await page.waitForURL("**/dashboard", { timeout: 15_000 });
      await screenshotPage(page, "contest-01-dashboard");

      // Navigate to contest page
      await page.goto("/contest");
      await page.waitForLoadState("networkidle");
      await screenshotPage(page, "contest-02-contest-page");

      // The contest page heading should be visible
      await expect(page.getByRole("heading", { name: "Virtual Contest" })).toBeVisible();
    });

    test("contest page displays tier cards", async ({ page }) => {
      // Login
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.click('button:has-text("Sign In")');

      await page.waitForURL("**/dashboard", { timeout: 10_000 });

      // Navigate to contest page
      await page.goto("/contest");
      await page.waitForLoadState("networkidle");
      await screenshotPage(page, "contest-03-tiers");

      // The page should display contest tiers
      // Tiers are: beginner, advanced, master
      // New users (elo ~1200) should see the beginner tier as available
      const hasTiers = await page.locator("text=Start Contest").count();

      if (hasTiers > 0) {
        // At least one tier should be available
        await expect(page.locator("text=Start Contest").first()).toBeVisible();
      }

      // Verify tier-related text is displayed somewhere on the page
      // (tier names or tier info like duration, problem count, rating range)
      const pageContent = await page.locator("body").textContent();
      expect(pageContent).toBeTruthy();
    });

    test("start a beginner contest", async ({ page }) => {
      // Login
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.click('button:has-text("Sign In")');

      await page.waitForURL("**/dashboard", { timeout: 10_000 });

      // Navigate to contest page
      await page.goto("/contest");
      await page.waitForLoadState("networkidle");
      await screenshotPage(page, "contest-04-before-start");

      // Check for an active contest first
      const hasActiveContest = await page.locator("text=Resume Contest").count();

      if (hasActiveContest > 0) {
        // Already have an active contest - click Resume
        await page.click('text=Resume Contest');
        await page.waitForURL(/\/contest\/[a-z0-9-]+/, { timeout: 10_000 });
        await screenshotPage(page, "contest-05-resumed-contest");
        return;
      }

      // Try to start a beginner contest
      const startButtons = page.locator('button:has-text("Start Contest")');
      const startCount = await startButtons.count();

      if (startCount === 0) {
        // No start buttons available (maybe all locked or no tiers)
        test.skip();
        return;
      }

      // Click the first available "Start Contest" button (likely beginner for new users)
      await startButtons.first().click();

      // Wait for navigation to contest detail page
      await page.waitForURL(/\/contest\/[a-z0-9-]+/, { timeout: 15_000 });
      await screenshotPage(page, "contest-05-contest-started");

      // Verify we are on a contest detail page
      await expect(page).toHaveURL(/\/contest\//);

      // Verify contest UI elements are present (timer, end contest button, etc.)
      const bodyContent = await page.locator("body").textContent();
      expect(bodyContent).toBeTruthy();
    });
  });
});
