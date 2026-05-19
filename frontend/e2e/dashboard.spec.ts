import { test, expect } from "@playwright/test";

/**
 * Dashboard E2E tests (Elo display, M-Elo radar chart, empty states).
 *
 * Strategy: All API calls are intercepted with mock responses so the tests
 * can run against the Vite dev server alone (no backend required). Tests
 * that truly require a live backend are wrapped with test.skip().
 */

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

/** Mock user object. */
const fakeUser = {
  id: "00000000-0000-0000-0000-000000000001",
  username: "dashboarduser",
  email: "dashboard@example.com",
  cf_handle: null,
  cf_handle_verified: false,
  elo: 1350,
  pp: 42,
  tokens: 250,
  is_active: true,
  is_admin: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
  last_login_at: "2025-06-01T00:00:00Z",
};

/** Inject a fake authenticated user into localStorage so auth guards pass. */
async function mockAuth(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const user = {
      id: "00000000-0000-0000-0000-000000000001",
      username: "dashboarduser",
      email: "dashboard@example.com",
      cf_handle: null,
      cf_handle_verified: false,
      elo: 1350,
      pp: 42,
      tokens: 250,
      is_active: true,
      is_admin: false,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
      last_login_at: "2025-06-01T00:00:00Z",
    };
    localStorage.setItem("access_token", "fake-dashboard-token");
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: {
          user,
          token: "fake-dashboard-token",
          isAuthenticated: true,
          isAdmin: false,
        },
        version: 0,
      }),
    );
  });
}

/** Intercept /auth/me and return the fake user profile. */
async function mockAuthMeAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: fakeUser,
        message: "User profile retrieved",
      }),
    }),
  );
}

/** Set up dashboard API mocks with data (Elo history, M-Elo, transactions). */
async function mockDashboardWithData(page: import("@playwright/test").Page) {
  // Transactions
  await page.route("**/api/v1/economy/transactions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          items: [
            {
              id: "tx-1",
              type: "training_reward",
              amount: 20,
              balance_after: 270,
              description: "Training reward",
              created_at: "2025-06-01T10:00:00Z",
            },
            {
              id: "tx-2",
              type: "challenge_reward",
              amount: 30,
              balance_after: 250,
              description: "Challenge win",
              created_at: "2025-05-30T14:00:00Z",
            },
          ],
          total: 2,
        },
        message: "Transactions retrieved",
      }),
    }),
  );

  // Active contest - none
  await page.route("**/api/v1/contest/active", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: null,
        message: "No active contest",
      }),
    }),
  );

  // M-Elo data with multiple tags
  await page.route("**/api/v1/training/m-elo", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          melos: [
            { tag: "dp", elo: 1400, shield_active: false, total_submissions: 10 },
            { tag: "greedy", elo: 1300, shield_active: false, total_submissions: 8 },
            { tag: "math", elo: 1500, shield_active: false, total_submissions: 12 },
            { tag: "graphs", elo: 1200, shield_active: true, total_submissions: 0 },
            { tag: "strings", elo: 1350, shield_active: false, total_submissions: 6 },
          ],
          global_elo: 1350,
        },
        message: "M-Elo data retrieved",
      }),
    }),
  );

  // Elo history with data points
  await page.route("**/api/v1/auth/elo-history", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: [
          { date: "2025-05-01", elo: 1200, change: 0 },
          { date: "2025-05-05", elo: 1225, change: 25 },
          { date: "2025-05-10", elo: 1250, change: 25 },
          { date: "2025-05-15", elo: 1230, change: -20 },
          { date: "2025-05-20", elo: 1300, change: 70 },
          { date: "2025-05-25", elo: 1350, change: 50 },
        ],
        message: "Elo history retrieved",
      }),
    }),
  );

  // PP contributions
  await page.route("**/api/v1/auth/pp-contributions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: [
          { tag: "dp", contribution: 12.5, solved_count: 10 },
          { tag: "math", contribution: 15.0, solved_count: 12 },
          { tag: "greedy", contribution: 8.5, solved_count: 8 },
        ],
        message: "PP contributions retrieved",
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

/** Set up dashboard API mocks with no data (empty states). */
async function mockDashboardEmpty(page: import("@playwright/test").Page) {
  // Empty transactions
  await page.route("**/api/v1/economy/transactions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { items: [], total: 0 },
        message: "Transactions retrieved",
      }),
    }),
  );

  // No active contest
  await page.route("**/api/v1/contest/active", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: null,
        message: "No active contest",
      }),
    }),
  );

  // Empty M-Elo data
  await page.route("**/api/v1/training/m-elo", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { melos: [], global_elo: 1350 },
        message: "M-Elo data retrieved",
      }),
    }),
  );

  // Empty Elo history
  await page.route("**/api/v1/auth/elo-history", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: [],
        message: "Elo history retrieved",
      }),
    }),
  );

  // Empty PP contributions
  await page.route("**/api/v1/auth/pp-contributions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: [],
        message: "PP contributions retrieved",
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

test.describe("Dashboard", () => {
  test("loads and displays Elo rating value", async ({ page }) => {
    // Precondition: Vite dev server is running. Auth state and API are mocked.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockDashboardWithData(page);

    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Verify welcome message with username
    await expect(page.getByText("Welcome back, dashboarduser")).toBeVisible();

    // Verify Elo rating is displayed (the value 1350)
    await expect(page.getByText("Elo Rating")).toBeVisible();
    await expect(page.getByText("1350")).toBeVisible();

    // Verify PP and Tokens cards
    await expect(page.getByText("Performance Points")).toBeVisible();
    await expect(page.getByText("42")).toBeVisible();
    await expect(page.getByText("Tokens")).toBeVisible();
    await expect(page.getByText("250")).toBeVisible();
  });

  test("renders M-Elo radar chart with data", async ({ page }) => {
    // Precondition: Vite dev server is running. M-Elo API returns multiple tags.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockDashboardWithData(page);

    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Verify "Analytics" section heading
    await expect(page.getByText("Analytics")).toBeVisible();

    // Verify "Skill Radar" chart heading (from RadarChart component)
    await expect(page.getByText("Skill Radar")).toBeVisible();

    // Verify radar chart renders the topic labels on the axes
    // The PolarAngleAxis uses dataKey="topic" which shows tag names
    await expect(page.getByText("dp")).toBeVisible();
    await expect(page.getByText("math")).toBeVisible();
    await expect(page.getByText("greedy")).toBeVisible();
  });

  test("renders Elo trend chart with data points", async ({ page }) => {
    // Precondition: Vite dev server is running. Elo history API returns data.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockDashboardWithData(page);

    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Verify "Elo Trend" heading
    await expect(page.getByText("Elo Trend")).toBeVisible();

    // Verify time range selectors are present
    await expect(page.getByText("7D")).toBeVisible();
    await expect(page.getByText("30D")).toBeVisible();
    await expect(page.getByText("All")).toBeVisible();
  });

  test("shows friendly empty state when no data", async ({ page }) => {
    // Precondition: Vite dev server is running. All analytics APIs return empty data.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockDashboardEmpty(page);

    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Verify welcome message still appears
    await expect(page.getByText("Welcome back, dashboarduser")).toBeVisible();

    // Verify Elo chart empty state message
    await expect(page.getByText("No Elo history yet")).toBeVisible();

    // Verify radar chart empty state message
    await expect(page.getByText("No M-Elo data yet")).toBeVisible();

    // Verify token activity empty state
    await expect(page.getByText("No recent activity")).toBeVisible();
  });

  test("displays quick action links", async ({ page }) => {
    // Precondition: Vite dev server is running. Dashboard loads with mock data.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockDashboardWithData(page);

    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Verify Quick Actions section
    await expect(page.getByText("Quick Actions")).toBeVisible();

    // Verify all four quick action items
    await expect(page.getByText("Random Challenge")).toBeVisible();
    await expect(page.getByText("Topic Training")).toBeVisible();
    await expect(page.getByText("Virtual Contest")).toBeVisible();
    await expect(page.getByText("Leaderboard")).toBeVisible();
  });

  test("displays recent token activity", async ({ page }) => {
    // Precondition: Vite dev server is running. Transactions API returns data.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockDashboardWithData(page);

    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Verify Recent Token Activity section
    await expect(page.getByText("Recent Token Activity")).toBeVisible();

    // Verify transaction items are rendered
    await expect(page.getByText("training reward")).toBeVisible();
    await expect(page.getByText("challenge reward")).toBeVisible();

    // Verify amounts
    await expect(page.getByText("+20")).toBeVisible();
    await expect(page.getByText("+30")).toBeVisible();
  });

  test("shows CF handle binding prompt when user has no CF handle", async ({ page }) => {
    // Precondition: User has no cf_handle set.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockDashboardWithData(page);

    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");

    // Verify CF handle binding prompt
    await expect(page.getByText("Link your Codeforces account")).toBeVisible();
    await expect(page.getByText("Bind Handle")).toBeVisible();
  });

  // This test requires a live backend with real user data.
  // Skip when running without Docker (CI=false, no backend).
  test.skip("dashboard loads against live backend", async ({ page }) => {
    // This test would exercise the full dashboard with real API responses.
    // It is skipped by default because it requires the full Docker environment.
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText(/Welcome back/)).toBeVisible();
  });
});
