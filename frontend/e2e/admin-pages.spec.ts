import { test, expect } from "@playwright/test";

/**
 * Admin pages screenshot validation.
 *
 * These tests render the Admin Overview and Config pages in a browser,
 * mocking the API responses to simulate an admin session. Screenshots are
 * captured for visual verification.
 */

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Inject a fake admin user + token into localStorage so auth guards pass. */
async function mockAdminAuth(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const fakeUser = {
      id: "00000000-0000-0000-0000-000000000001",
      username: "admin",
      email: "admin@test.com",
      cf_handle: null,
      cf_handle_verified: false,
      elo: 2000,
      pp: 100,
      tokens: 500,
      is_active: true,
      is_admin: true,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
      last_login_at: "2025-06-01T00:00:00Z",
    };
    localStorage.setItem("access_token", "fake-admin-token");
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: {
          user: fakeUser,
          token: "fake-admin-token",
          isAuthenticated: true,
          isAdmin: true,
        },
        version: 0,
      }),
    );
  });
}

/** Intercept admin API calls and return mock data. */
async function mockAdminAPIs(page: import("@playwright/test").Page) {
  // Auth me (needed by hydrate)
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          id: "00000000-0000-0000-0000-000000000001",
          username: "admin",
          email: "admin@test.com",
          cf_handle: null,
          cf_handle_verified: false,
          elo: 2000,
          pp: 100,
          tokens: 500,
          is_active: true,
          is_admin: true,
          created_at: "2025-01-01T00:00:00Z",
          updated_at: "2025-01-01T00:00:00Z",
          last_login_at: "2025-06-01T00:00:00Z",
        },
        message: "User profile retrieved",
      }),
    }),
  );

  // System stats
  await page.route("**/api/v1/admin/stats", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          users: { total: 42, active: 38 },
          challenges: { total: 120, active: 5 },
          training: { total_sessions: 85, active_sessions: 3 },
          contests: { total: 30, active: 2 },
        },
        message: "System statistics retrieved",
      }),
    }),
  );

  // User list
  await page.route("**/api/v1/admin/users**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          items: [
            {
              id: "00000000-0000-0000-0000-000000000001",
              username: "admin",
              email: "admin@test.com",
              elo: 2000,
              pp: 100.0,
              tokens: 500,
              is_active: true,
              is_admin: true,
              created_at: "2025-01-01T00:00:00Z",
              last_login_at: "2025-06-01T00:00:00Z",
            },
            {
              id: "00000000-0000-0000-0000-000000000002",
              username: "alice",
              email: "alice@test.com",
              elo: 1500,
              pp: 50.0,
              tokens: 200,
              is_active: true,
              is_admin: false,
              created_at: "2025-02-01T00:00:00Z",
              last_login_at: "2025-05-01T00:00:00Z",
            },
            {
              id: "00000000-0000-0000-0000-000000000003",
              username: "bob",
              email: "bob@test.com",
              elo: 900,
              pp: 10.0,
              tokens: 30,
              is_active: false,
              is_admin: false,
              created_at: "2025-03-01T00:00:00Z",
              last_login_at: null,
            },
          ],
          total: 3,
          page: 1,
          page_size: 10,
          total_pages: 1,
        },
        message: "User list retrieved",
      }),
    }),
  );

  // Config - full
  await page.route("**/api/v1/admin/config", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          elo: { initial_elo: 1200, k_factor: 32, divisor: 400, quit_penalty_min: 5, quit_penalty_max: 10 },
          pp: { base_formula_coefficient: 10, base_formula_offset: 800, decay_factor: 0.95, max_problems: 100 },
          economy: { daily_token_cap: 120, time_bonus_threshold_minutes: 20 },
          challenge: { weight_within_100: 0.5, weight_challenge_zone: 0.25, weight_consolidation_zone: 0.15, weight_surprise_zone: 0.1 },
          contest: {},
          cf_api: { base_url: "https://codeforces.com/api", request_interval_seconds: 2, max_retries: 3, cache_ttl_seconds: 300 },
        },
        message: "Configuration retrieved",
      }),
    }),
  );

  // Config metadata
  await page.route("**/api/v1/admin/config/metadata", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: [
          {
            key: "elo",
            label: "ELO",
            fields: [
              { key: "elo.initial_elo", label: "initial_elo", type: "int", default: 1200 },
              { key: "elo.k_factor", label: "k_factor", type: "int", default: 32 },
              { key: "elo.divisor", label: "divisor", type: "int", default: 400 },
              { key: "elo.quit_penalty_min", label: "quit_penalty_min", type: "int", default: 5 },
              { key: "elo.quit_penalty_max", label: "quit_penalty_max", type: "int", default: 10 },
            ],
          },
          {
            key: "pp",
            label: "PP",
            fields: [
              { key: "pp.base_formula_coefficient", label: "base_formula_coefficient", type: "int", default: 10 },
              { key: "pp.base_formula_offset", label: "base_formula_offset", type: "int", default: 800 },
              { key: "pp.decay_factor", label: "decay_factor", type: "float", default: 0.95 },
              { key: "pp.max_problems", label: "max_problems", type: "int", default: 100 },
            ],
          },
          {
            key: "economy",
            label: "ECONOMY",
            fields: [
              { key: "economy.daily_token_cap", label: "daily_token_cap", type: "int", default: 120 },
              { key: "economy.time_bonus_threshold_minutes", label: "time_bonus_threshold_minutes", type: "int", default: 20 },
            ],
          },
          {
            key: "challenge",
            label: "CHALLENGE",
            fields: [
              { key: "challenge.weight_within_100", label: "weight_within_100", type: "float", default: 0.5 },
              { key: "challenge.weight_challenge_zone", label: "weight_challenge_zone", type: "float", default: 0.25 },
            ],
          },
          {
            key: "cf_api",
            label: "CF_API",
            fields: [
              { key: "cf_api.base_url", label: "base_url", type: "str", default: "https://codeforces.com/api" },
              { key: "cf_api.request_interval_seconds", label: "request_interval_seconds", type: "int", default: 2 },
              { key: "cf_api.max_retries", label: "max_retries", type: "int", default: 3 },
              { key: "cf_api.cache_ttl_seconds", label: "cache_ttl_seconds", type: "int", default: 300 },
            ],
          },
        ],
        message: "Config metadata retrieved",
      }),
    }),
  );

  // Health check
  await page.route("**/api/v1/health", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, data: { status: "ok", version: "v1" }, message: "Success" }),
    }),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Admin Overview Page", () => {
  test("renders stats cards and user table", async ({ page }) => {
    await mockAdminAuth(page);
    await mockAdminAPIs(page);

    await page.goto("/admin");
    await page.waitForLoadState("networkidle");

    // Verify heading
    await expect(page.getByRole("heading", { name: "Admin Dashboard" })).toBeVisible();

    // Verify stat cards are rendered
    await expect(page.getByText("42")).toBeVisible(); // total users
    await expect(page.getByText("120")).toBeVisible(); // total challenges
    await expect(page.getByText("85")).toBeVisible(); // training sessions
    await expect(page.getByText("30")).toBeVisible(); // contests

    // Verify user table has users
    await expect(page.getByText("admin@test.com")).toBeVisible();
    await expect(page.getByText("alice@test.com")).toBeVisible();
    await expect(page.getByText("bob@test.com")).toBeVisible();

    // Verify admin badge
    await expect(page.getByText("Admin").first()).toBeVisible();

    // Take screenshot
    await page.screenshot({
      path: "e2e/screenshots/admin-overview.png",
      fullPage: true,
    });
  });

  test("disables non-existent user search correctly", async ({ page }) => {
    await mockAdminAuth(page);
    await mockAdminAPIs(page);

    // Override user list for search
    await page.route("**/api/v1/admin/users?**search=nonexistent**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: { items: [], total: 0, page: 1, page_size: 10, total_pages: 1 },
          message: "User list retrieved",
        }),
      }),
    );

    await page.goto("/admin");
    await page.waitForLoadState("networkidle");

    // Search for non-existent user
    await page.fill('input[placeholder="Search users..."]', "nonexistent");
    await page.click('button:has-text("Search")');

    await expect(page.getByText("No users found")).toBeVisible();

    await page.screenshot({
      path: "e2e/screenshots/admin-overview-empty-search.png",
      fullPage: true,
    });
  });
});

test.describe("Admin Config Page", () => {
  test("renders config sections with fields", async ({ page }) => {
    await mockAdminAuth(page);
    await mockAdminAPIs(page);

    await page.goto("/admin/config");
    await page.waitForLoadState("networkidle");

    // Verify heading
    await expect(page.getByRole("heading", { name: "Configuration" })).toBeVisible();

    // First section should be expanded by default
    await expect(page.getByText("initial_elo")).toBeVisible();
    await expect(page.getByText("k_factor")).toBeVisible();

    // Verify config values are loaded
    const inputs = page.locator('input[type="number"]');
    await expect(inputs.first()).toHaveValue("1200");

    // Take screenshot
    await page.screenshot({
      path: "e2e/screenshots/admin-config.png",
      fullPage: true,
    });
  });

  test("can expand and collapse sections", async ({ page }) => {
    await mockAdminAuth(page);
    await mockAdminAPIs(page);

    await page.goto("/admin/config");
    await page.waitForLoadState("networkidle");

    // Click on PP section to expand
    await page.click('button:has-text("PP")');
    await expect(page.getByText("base_formula_coefficient")).toBeVisible();
    await expect(page.getByText("decay_factor")).toBeVisible();

    // Take screenshot with expanded section
    await page.screenshot({
      path: "e2e/screenshots/admin-config-expanded.png",
      fullPage: true,
    });
  });
});
