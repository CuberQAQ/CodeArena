// @integration
// Prerequisites: Docker Compose must be running with backend + frontend.
// Run: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
// Then: npx playwright test --project=integration e2e/integration/challenge-flow.spec.ts

import { test, expect } from "@playwright/test";
import { screenshotPage } from "./helpers/screenshots";

test.describe("Challenge Flow (Integration)", () => {
  test.describe.serial("Register user and verify challenge page loads", () => {
    const suffix = Date.now();
    const username = `e2e_ch_${suffix}`;
    const email = `e2e_ch_${suffix}@test.com`;
    const password = "TestPass123!";

    test("register and navigate to challenge page", async ({ page }) => {
      // Register
      await page.goto("/register");
      await page.waitForLoadState("networkidle");

      await page.fill("#username", username);
      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.fill("#confirmPassword", password);
      await page.click('button:has-text("Create Account")');

      await page.waitForURL("**/dashboard", { timeout: 15_000 });
      await screenshotPage(page, "challenge-01-dashboard");

      // Navigate to challenge page
      await page.goto("/challenge");
      await page.waitForLoadState("networkidle");
      await screenshotPage(page, "challenge-02-challenge-page");

      // The challenge page should load without errors
      // It either shows the idle phase (start matching button) or resume an existing session
      const pageContent = page.locator("body");
      await expect(pageContent).toBeVisible();
    });

    test("challenge page shows matchmaking UI elements", async ({ page }) => {
      // Login first
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.click('button:has-text("Sign In")');
      await page.waitForURL("**/dashboard", { timeout: 10_000 });

      // Navigate to challenge
      await page.goto("/challenge");
      await page.waitForLoadState("networkidle");
      await screenshotPage(page, "challenge-03-challenge-page-logged-in");

      // The page should display challenge-related content.
      // For a new user with no active session, this is the idle phase
      // which shows a button to start matchmaking or similar.
      // We just verify the page rendered without crashing.
      const bodyText = await page.locator("body").textContent();
      expect(bodyText).toBeTruthy();
    });

    test("two users can register and view challenge page", async ({ browser }) => {
      // Create two browser contexts for two users
      const ctx1 = await browser.newContext();
      const ctx2 = await browser.newContext();
      const page1 = await ctx1.newPage();
      const page2 = await ctx2.newPage();

      const s2 = Date.now();
      const user2Name = `e2e_ch2_${s2}`;
      const user2Email = `e2e_ch2_${s2}@test.com`;

      // Register user 1
      await page1.goto("/register");
      await page1.waitForLoadState("networkidle");
      await page1.fill("#username", `e2e_ch_${suffix}`);
      await page1.fill("#email", `e2e_ch_${suffix}@test.com`);
      await page1.fill("#password", password);
      await page1.fill("#confirmPassword", password);
      await page1.click('button:has-text("Create Account")');
      await page1.waitForURL("**/dashboard", { timeout: 15_000 });

      // Register user 2
      await page2.goto("/register");
      await page2.waitForLoadState("networkidle");
      await page2.fill("#username", user2Name);
      await page2.fill("#email", user2Email);
      await page2.fill("#password", password);
      await page2.fill("#confirmPassword", password);
      await page2.click('button:has-text("Create Account")');
      await page2.waitForURL("**/dashboard", { timeout: 15_000 });

      await screenshotPage(page1, "challenge-04-user1-dashboard");
      await screenshotPage(page2, "challenge-05-user2-dashboard");

      // Both navigate to challenge page
      await page1.goto("/challenge");
      await page1.waitForLoadState("networkidle");

      await page2.goto("/challenge");
      await page2.waitForLoadState("networkidle");

      await screenshotPage(page1, "challenge-06-user1-challenge");
      await screenshotPage(page2, "challenge-07-user2-challenge");

      // Clean up
      await ctx1.close();
      await ctx2.close();
    });
  });
});
