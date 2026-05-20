// @integration
// Prerequisites: Docker Compose must be running with backend + frontend.
// Run: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
// Then: npx playwright test --project=integration e2e/integration/training-flow.spec.ts

import { test, expect } from "@playwright/test";
import { screenshotPage } from "./helpers/screenshots";

test.describe("Training Flow (Integration)", () => {
  test.describe.serial("Register -> Training page -> Topic detail", () => {
    const suffix = Date.now();
    const username = `e2e_tr_${suffix}`;
    const email = `e2e_tr_${suffix}@test.com`;
    const password = "TestPass123!";

    test("register and navigate to training page", async ({ page }) => {
      // Register
      await page.goto("/register");
      await page.waitForLoadState("networkidle");

      await page.fill("#username", username);
      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.fill("#confirmPassword", password);
      await page.click('button:has-text("Create Account")');

      await page.waitForURL("**/dashboard", { timeout: 15_000 });
      await screenshotPage(page, "training-01-dashboard");

      // Navigate to training page
      await page.goto("/training");
      await page.waitForLoadState("networkidle");
      await screenshotPage(page, "training-02-training-page");

      // The training page should display the topic list heading
      await expect(page.getByRole("heading", { name: "Topic Training" })).toBeVisible();
    });

    test("training page displays topic cards", async ({ page }) => {
      // Login
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.click('button:has-text("Sign In")');

      await page.waitForURL("**/dashboard", { timeout: 10_000 });

      // Navigate to training
      await page.goto("/training");
      await page.waitForLoadState("networkidle");
      await screenshotPage(page, "training-03-topics-list");

      // The page should either show topic cards or an empty state
      const hasTopics = await page.locator("a[href^='/training/']").count();

      if (hasTopics > 0) {
        // Verify at least one topic card is present
        const firstTopic = page.locator("a[href^='/training/']").first();
        await expect(firstTopic).toBeVisible();
      } else {
        // If no topics, check for empty state message
        const emptyState = page.getByText("No topics available yet");
        await expect(emptyState).toBeVisible();
      }
    });

    test("clicking a topic navigates to topic detail", async ({ page }) => {
      // Login
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.click('button:has-text("Sign In")');
      await page.waitForURL("**/dashboard", { timeout: 10_000 });

      // Navigate to training
      await page.goto("/training");
      await page.waitForLoadState("networkidle");

      // Find topic links
      const topicLinks = page.locator("a[href^='/training/']");
      const topicCount = await topicLinks.count();

      if (topicCount === 0) {
        // No topics available - skip the rest
        test.skip();
        return;
      }

      // Click the first topic
      const firstTopicHref = await topicLinks.first().getAttribute("href");
      await topicLinks.first().click();

      // Should navigate to the topic detail page
      if (firstTopicHref) {
        await page.waitForURL(`**${firstTopicHref}`, { timeout: 10_000 });
      } else {
        // Wait for any URL change from /training to /training/something
        await page.waitForURL(/\/training\/[a-z]/, { timeout: 10_000 });
      }

      await screenshotPage(page, "training-04-topic-detail");

      // Verify the topic detail page loaded
      // Should have "Back to Topics" link and content
      await expect(page.getByText("Back to Topics")).toBeVisible();
    });
  });
});
