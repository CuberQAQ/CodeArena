import { test, expect } from "@playwright/test";

/**
 * RankingPage title switching E2E verification (FR-20.1, FR-21.3).
 *
 * Uses mocked API endpoints to verify the title switching behavior
 * against the Vite dev server (no backend required).
 * Run: npx playwright test e2e/ranking-title.spec.ts --project=chromium
 */

const SCREENSHOTS_DIR = "e2e/screenshots";

// Mock data
const globalItems = [
  { name: "tourist", pp: 400, country: "BY", verified: true, cf_rating: 3800 },
  { name: "Petr_CF", pp: 350, country: null, verified: false, cf_rating: 3200 },
  { name: "ecnidan", pp: 300, country: "CN", verified: true, cf_rating: 2800 },
];

const arenaItems = [
  { name: "player1", pp: 250, country: "US", verified: true, elo: 2100 },
  { name: "player2", pp: 200, country: "JP", verified: true, elo: 1800 },
];

// Auth mock
async function mockAuth(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const user = {
      id: "00000000-0000-0000-0000-000000000001",
      username: "rankingtest",
      email: "rt@test.com",
      cf_handle: "rtcf",
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
    localStorage.setItem("access_token", "fake-ranking-token");
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: {
          user,
          token: "fake-ranking-token",
          isAuthenticated: true,
          isAdmin: false,
        },
        version: 0,
      }),
    );
  });
}

// Unified mock for all ranking and auth APIs
async function mockAllAPIs(page: import("@playwright/test").Page) {
  // Use wildcard pattern to ensure query params are matched
  await page.route("**/api/v1/ranking/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/ranking/global")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: { items: globalItems, total: 3, page: 1, page_size: 50 },
          message: "ok",
        }),
      });
    } else if (url.includes("/ranking/arena")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: { items: arenaItems, total: 2, page: 1, page_size: 50 },
          message: "ok",
        }),
      });
    } else {
      await route.continue();
    }
  });

  // Mock auth endpoints
  await page.route("**/api/v1/auth/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          id: "00000000-0000-0000-0000-000000000001",
          username: "rankingtest",
          email: "rt@test.com",
          cf_handle: "rtcf",
          cf_handle_verified: true,
          elo: 1500,
          pp: 55,
          tokens: 300,
          is_active: true,
          is_admin: false,
          created_at: "2025-01-01T00:00:00Z",
          updated_at: "2025-01-01T00:00:00Z",
          last_login_at: "2025-06-01T00:00:00Z",
        },
        message: "User profile retrieved",
      }),
    }),
  );
}

test.describe("RankingPage title switching", () => {
  test("global tab shows 'Global Ranking' title and description", async ({ page }) => {
    await mockAuth(page);
    await mockAllAPIs(page);

    await page.goto("/ranking");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1500);

    // Verify heading shows "Global Ranking"
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toContainText("Global Ranking");

    // Verify description mentions "CodeArena users and Codeforces"
    await expect(page.getByText(/CodeArena users and Codeforces/)).toBeVisible();

    // Screenshot
    await page.screenshot({
      path: `${SCREENSHOTS_DIR}/ranking-global-tab.png`,
      fullPage: true,
    });
  });

  test("arena tab shows 'Arena Ranking' title and description", async ({ page }) => {
    await mockAuth(page);
    await mockAllAPIs(page);

    await page.goto("/ranking");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);

    // Click the Arena tab
    await page.locator('button:has-text("Arena")').click();
    await page.waitForTimeout(1500);

    // Verify heading shows "Arena Ranking"
    const heading = page.getByRole("heading", { level: 1 });
    await expect(heading).toContainText("Arena Ranking");

    // Verify PageHeader description mentions "CodeArena users only"
    // Note: both PageHeader description and tab description paragraph may match,
    // so we check the first one (PageHeader description inside the header area)
    await expect(page.getByText(/CodeArena users only/).first()).toBeVisible();

    // Screenshot
    await page.screenshot({
      path: `${SCREENSHOTS_DIR}/ranking-arena-tab.png`,
      fullPage: true,
    });
  });

  test("title updates correctly when switching tabs back and forth", async ({ page }) => {
    await mockAuth(page);
    await mockAllAPIs(page);

    await page.goto("/ranking");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(1000);

    const heading = page.getByRole("heading", { level: 1 });

    // Initially on global tab
    await expect(heading).toContainText("Global Ranking");

    // Switch to Arena tab
    await page.locator('button:has-text("Arena")').click();
    await page.waitForTimeout(1500);
    await expect(heading).toContainText("Arena Ranking");
    await expect(heading).not.toContainText("Global Ranking");

    // Switch back to Global tab
    await page.locator('button:has-text("Global")').click();
    await page.waitForTimeout(1500);
    await expect(heading).toContainText("Global Ranking");
    await expect(heading).not.toContainText("Arena Ranking");

    // Screenshot of the switched-back state
    await page.screenshot({
      path: `${SCREENSHOTS_DIR}/ranking-tab-switch-roundtrip.png`,
      fullPage: true,
    });
  });

  test("ranking data still displays correctly (regression check)", async ({ page }) => {
    await mockAuth(page);
    await mockAllAPIs(page);

    await page.goto("/ranking");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3000);

    // Verify data is displayed
    await expect(page.getByText("tourist")).toBeVisible({ timeout: 5000 });
    await expect(page.getByText("Petr_CF")).toBeVisible();

    // Screenshot showing full page with data
    await page.screenshot({
      path: `${SCREENSHOTS_DIR}/ranking-global-with-data.png`,
      fullPage: true,
    });
  });
});
