// @integration
// Prerequisites: Docker Compose must be running with backend + frontend.
// Run: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
// Then: npx playwright test --project=integration e2e/integration/auth-flow.spec.ts

import { test, expect } from "@playwright/test";
import { screenshotPage } from "./helpers/screenshots";

test.describe("Auth Flow (Integration)", () => {
  test.describe.serial("Register -> Dashboard -> Logout -> Re-login", () => {
    const suffix = Date.now();
    const username = `e2e_auth_${suffix}`;
    const email = `e2e_auth_${suffix}@test.com`;
    const password = "TestPass123!";
    let capturedUsername = "";

    test("register a new user and land on dashboard", async ({ page }) => {
      await page.goto("/register");
      await page.waitForLoadState("networkidle");
      await screenshotPage(page, "auth-01-register-page");

      // Verify we are on the register page
      await expect(page.getByRole("heading", { name: "Create Account" })).toBeVisible();

      // Fill the registration form
      await page.fill("#username", username);
      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.fill("#confirmPassword", password);

      await screenshotPage(page, "auth-02-register-filled");

      // Submit
      await page.click('button:has-text("Create Account")');

      // Should redirect to /dashboard
      await page.waitForURL("**/dashboard", { timeout: 15_000 });
      await expect(page).toHaveURL(/\/dashboard/);
      await screenshotPage(page, "auth-03-dashboard-after-register");

      // Dashboard should display the username
      await expect(page.getByText(new RegExp(`Welcome back.*${username}`))).toBeVisible();

      capturedUsername = username;
    });

    test("logout and return to login page", async ({ page }) => {
      // First login with the registered user
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await page.click('button:has-text("Sign In")');

      await page.waitForURL("**/dashboard", { timeout: 10_000 });
      await screenshotPage(page, "auth-04-dashboard-before-logout");

      // Click logout button in the sidebar/nav
      await page.click('button:has-text("Logout")');

      // Should return to login page
      await page.waitForURL(/\/$|\/login/, { timeout: 10_000 });
      await expect(page.getByRole("heading", { name: "Welcome Back" })).toBeVisible();
      await screenshotPage(page, "auth-05-after-logout");
    });

    test("re-login with the registered user", async ({ page }) => {
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      await page.fill("#email", email);
      await page.fill("#password", password);
      await screenshotPage(page, "auth-06-relogin-filled");

      await page.click('button:has-text("Sign In")');

      await page.waitForURL("**/dashboard", { timeout: 10_000 });
      await expect(page).toHaveURL(/\/dashboard/);
      await screenshotPage(page, "auth-07-dashboard-after-relogin");

      // Verify the username is displayed
      await expect(page.getByText(new RegExp(`Welcome back.*${username}`))).toBeVisible();
    });
  });
});
