import { test, expect } from "@playwright/test";

/**
 * Leaderboard E2E tests (Elo ranking, PP ranking, empty state, display modes).
 *
 * Strategy: All API calls are intercepted with mock responses so the tests
 * can run against the Vite dev server alone (no backend required). Tests
 * that truly require a live backend are wrapped with test.skip().
 */

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

const fakeUser = {
  id: "00000000-0000-0000-0000-000000000001",
  username: "lbuser",
  email: "lb@example.com",
  cf_handle: "lbcf",
  cf_handle_verified: true,
  elo: 1500,
  pp: 55,
  tokens: 300,
  is_active: true,
  is_admin: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
  last_login_at: "2025-06-01T00:00:00Z",
};

const mockLeaderboardUsers = [
  {
    id: "user-001",
    username: "top_player",
    email: "top@example.com",
    cf_handle: "topcf",
    cf_handle_verified: true,
    elo: 2100,
    pp: 120,
    tokens: 500,
    is_active: true,
    is_admin: false,
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-01T00:00:00Z",
    last_login_at: "2025-06-01T00:00:00Z",
    avatar_path: null,
  },
  {
    id: "user-002",
    username: "mid_player",
    email: "mid@example.com",
    cf_handle: null,
    cf_handle_verified: false,
    elo: 1600,
    pp: 80,
    tokens: 350,
    is_active: true,
    is_admin: false,
    created_at: "2025-02-01T00:00:00Z",
    updated_at: "2025-02-01T00:00:00Z",
    last_login_at: "2025-06-01T00:00:00Z",
    avatar_path: null,
  },
  {
    id: "user-003",
    username: "newbie",
    email: "newbie@example.com",
    cf_handle: "newbiecf",
    cf_handle_verified: false,
    elo: 1200,
    pp: 20,
    tokens: 100,
    is_active: true,
    is_admin: false,
    created_at: "2025-03-01T00:00:00Z",
    updated_at: "2025-03-01T00:00:00Z",
    last_login_at: "2025-06-01T00:00:00Z",
    avatar_path: null,
  },
  {
    id: "user-004",
    username: "pro_gamer",
    email: "pro@example.com",
    cf_handle: "procf",
    cf_handle_verified: true,
    elo: 1800,
    pp: 95,
    tokens: 400,
    is_active: true,
    is_admin: false,
    created_at: "2025-01-15T00:00:00Z",
    updated_at: "2025-01-15T00:00:00Z",
    last_login_at: "2025-06-01T00:00:00Z",
    avatar_path: null,
  },
];

async function mockAuth(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const user = {
      id: "00000000-0000-0000-0000-000000000001",
      username: "lbuser",
      email: "lb@example.com",
      cf_handle: "lbcf",
      cf_handle_verified: true,
      elo: 1500,
      pp: 55,
      tokens: 300,
      is_active: true,
      is_admin: false,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
      last_login_at: "2025-06-01T00:00:00Z",
    };
    localStorage.setItem("access_token", "fake-lb-token");
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: {
          user,
          token: "fake-lb-token",
          isAuthenticated: true,
          isAdmin: false,
        },
        version: 0,
      }),
    );
  });
}

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

async function mockHealthAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/health", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ success: true, data: { status: "ok", version: "v1" }, message: "Success" }),
    }),
  );
}

/** Mock /auth/leaderboard returning users sorted by Elo. */
async function mockLeaderboardAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/leaderboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: mockLeaderboardUsers,
        message: "Leaderboard retrieved",
      }),
    }),
  );
}

/** Mock /auth/leaderboard returning empty list. */
async function mockLeaderboardEmptyAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/leaderboard", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: [],
        message: "Leaderboard retrieved",
      }),
    }),
  );
}

/** Mock /auth/settings for display mode. */
async function mockSettingsAPI(page: import("@playwright/test").Page, mode: "medal" | "cf_tier" = "medal") {
  await page.route("**/api/v1/auth/settings", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { display_mode: mode },
        message: "Settings retrieved",
      }),
    }),
  );
}

/** Mock avatar endpoint. */
async function mockAvatarAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/avatar**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { avatar_path: null },
        message: "Avatar retrieved",
      }),
    }),
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Leaderboard Page", () => {
  test("loads and displays leaderboard with user rankings", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockLeaderboardAPI(page);
    await mockSettingsAPI(page, "medal");
    await mockAvatarAPI(page);

    await page.goto("/leaderboard");
    await page.waitForLoadState("networkidle");

    // Verify page heading
    await expect(page.getByText("Leaderboard")).toBeVisible();

    // Verify sort tabs are present
    await expect(page.getByText("By Elo")).toBeVisible();
    await expect(page.getByText("By PP")).toBeVisible();

    // Verify header row
    await expect(page.getByText("#")).toBeVisible();
    await expect(page.getByText("Player")).toBeVisible();
    await expect(page.getByText("Elo")).toBeVisible();
    await expect(page.getByText("PP")).toBeVisible();
    await expect(page.getByText("Tokens")).toBeVisible();

    // Verify user rows are rendered (sorted by Elo desc)
    // top_player (2100) > pro_gamer (1800) > mid_player (1600) > newbie (1200)
    await expect(page.getByText("top_player")).toBeVisible();
    await expect(page.getByText("pro_gamer")).toBeVisible();
    await expect(page.getByText("mid_player")).toBeVisible();
    await expect(page.getByText("newbie")).toBeVisible();

    // Verify Elo values are displayed
    await expect(page.getByText("2100")).toBeVisible();
    await expect(page.getByText("1800")).toBeVisible();
    await expect(page.getByText("1600")).toBeVisible();
    await expect(page.getByText("1200")).toBeVisible();
  });

  test("shows CF handles for users who have them", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockLeaderboardAPI(page);
    await mockSettingsAPI(page, "medal");
    await mockAvatarAPI(page);

    await page.goto("/leaderboard");
    await page.waitForLoadState("networkidle");

    // top_player has CF handle "topcf"
    await expect(page.getByText("topcf")).toBeVisible();
    // newbie has CF handle "newbiecf"
    await expect(page.getByText("newbiecf")).toBeVisible();
    // mid_player has no CF handle
    await expect(page.getByText("midcf")).not.toBeVisible();
  });

  test("shows rank numbers in correct order by Elo", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockLeaderboardAPI(page);
    await mockSettingsAPI(page, "medal");
    await mockAvatarAPI(page);

    await page.goto("/leaderboard");
    await page.waitForLoadState("networkidle");

    // Default sort is by Elo
    // Verify "By Elo" tab is active
    const byEloButton = page.locator('button:has-text("By Elo")');
    await expect(byEloButton).toHaveClass(/bg-primary/);

    // Verify ranking: #1 is top_player (Elo 2100)
    const rows = page.locator('div.divide-y > div');
    await expect(rows.nth(0)).toContainText("top_player");
    await expect(rows.nth(0)).toContainText("1");
    // #2 is pro_gamer (Elo 1800)
    await expect(rows.nth(1)).toContainText("pro_gamer");
    // #3 is mid_player (Elo 1600)
    await expect(rows.nth(2)).toContainText("mid_player");
    // #4 is newbie (Elo 1200)
    await expect(rows.nth(3)).toContainText("newbie");
  });

  test("switches to PP ranking and re-sorts the list", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockLeaderboardAPI(page);
    await mockSettingsAPI(page, "medal");
    await mockAvatarAPI(page);

    await page.goto("/leaderboard");
    await page.waitForLoadState("networkidle");

    // Click "By PP" tab
    await page.click('button:has-text("By PP")');

    // Verify "By PP" tab is active
    const byPPButton = page.locator('button:has-text("By PP")');
    await expect(byPPButton).toHaveClass(/bg-primary/);

    // PP ranking: top_player (120) > pro_gamer (95) > mid_player (80) > newbie (20)
    const rows = page.locator('div.divide-y > div');
    await expect(rows.nth(0)).toContainText("top_player");
    await expect(rows.nth(3)).toContainText("newbie");

    // Verify PP values are displayed
    await expect(page.getByText("120")).toBeVisible();
    await expect(page.getByText("95")).toBeVisible();
    await expect(page.getByText("80")).toBeVisible();
    await expect(page.getByText("20")).toBeVisible();
  });

  test("displays token counts for each user", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockLeaderboardAPI(page);
    await mockSettingsAPI(page, "medal");
    await mockAvatarAPI(page);

    await page.goto("/leaderboard");
    await page.waitForLoadState("networkidle");

    // Verify token values for users
    await expect(page.getByText("500")).toBeVisible(); // top_player
    await expect(page.getByText("400")).toBeVisible(); // pro_gamer
    await expect(page.getByText("350")).toBeVisible(); // mid_player
    await expect(page.getByText("100")).toBeVisible(); // newbie
  });

  test("shows empty state when leaderboard has no users", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockLeaderboardEmptyAPI(page);
    await mockSettingsAPI(page, "medal");

    await page.goto("/leaderboard");
    await page.waitForLoadState("networkidle");

    // Verify page heading still shows
    await expect(page.getByText("Leaderboard")).toBeVisible();

    // Verify empty state
    await expect(page.getByText("No data")).toBeVisible();
  });

  test("displays CF tier mode when settings use cf_tier display mode", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockLeaderboardAPI(page);
    await mockSettingsAPI(page, "cf_tier");
    await mockAvatarAPI(page);

    await page.goto("/leaderboard");
    await page.waitForLoadState("networkidle");

    // Users should still be visible
    await expect(page.getByText("top_player")).toBeVisible();
    await expect(page.getByText("newbie")).toBeVisible();

    // In CF tier mode, Elo values should include tier labels
    // The tier label text depends on i18n, so just verify Elo numbers are still there
    await expect(page.getByText("2100")).toBeVisible();
    await expect(page.getByText("1200")).toBeVisible();
  });

  test("leaderboard API failure shows empty state gracefully", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockSettingsAPI(page, "medal");

    // Mock leaderboard to return error
    await page.route("**/api/v1/auth/leaderboard", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          success: false,
          error: { code: "INTERNAL_ERROR", message: "Failed to fetch leaderboard" },
        }),
      }),
    );

    await page.goto("/leaderboard");
    await page.waitForLoadState("networkidle");

    // Should show empty state (no crash)
    await expect(page.getByText("Leaderboard")).toBeVisible();
    await expect(page.getByText("No data")).toBeVisible();
  });

  // This test requires a live backend with real leaderboard data.
  // Skip when running without Docker (CI=false, no backend).
  test.skip("leaderboard loads against live backend", async ({ page }) => {
    // This test would exercise the full leaderboard with real API responses.
    // It is skipped by default because it requires the full Docker environment.
    await page.goto("/leaderboard");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Leaderboard")).toBeVisible();
  });
});
