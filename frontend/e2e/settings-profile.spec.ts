import { test, expect } from "@playwright/test";

/**
 * Settings & Profile E2E tests (display mode, profile editing, CF handle binding).
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
  username: "settingsuser",
  email: "settings@example.com",
  cf_handle: null,
  cf_handle_verified: false,
  elo: 1500,
  pp: 55,
  tokens: 300,
  is_active: true,
  is_admin: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
  last_login_at: "2025-06-01T00:00:00Z",
};

const fakeUserWithCF = {
  ...fakeUser,
  username: "settingsuser",
  cf_handle: "testcfhandle",
  cf_handle_verified: true,
};

async function mockAuth(page: import("@playwright/test").Page, user = fakeUser) {
  await page.addInitScript((injectedUser) => {
    localStorage.setItem("access_token", "fake-settings-token");
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: {
          user: injectedUser,
          token: "fake-settings-token",
          isAuthenticated: true,
          isAdmin: false,
        },
        version: 0,
      }),
    );
  }, user);
}

async function mockAuthMeAPI(page: import("@playwright/test").Page, user = fakeUser) {
  await page.route("**/api/v1/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: user,
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

/** Mock /auth/settings returning medal display mode. */
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

/** Mock PUT /auth/settings to accept save. */
async function mockSettingsSaveAPI(page: import("@playwright/test").Page) {
  await page.route(
    (route) => route.request.method() === "PUT" && route.request.url().includes("/api/v1/auth/settings"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: null,
          message: "Settings saved",
        }),
      }),
  );
}

/** Mock profile APIs used by ProfilePage. */
async function mockProfileAPIs(page: import("@playwright/test").Page, user = fakeUser) {
  // Auth me
  await mockAuthMeAPI(page, user);

  // Elo history
  await page.route("**/api/v1/auth/elo-history", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: [
          { date: "2025-05-01", elo: 1400, change: 0 },
          { date: "2025-05-10", elo: 1450, change: 50 },
          { date: "2025-05-20", elo: 1500, change: 50 },
        ],
        message: "Elo history retrieved",
      }),
    }),
  );

  // Settings
  await mockSettingsAPI(page);

  // Medal overall
  await page.route("**/api/v1/medal/overall", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { elo: 1500, medal: { level: "silver", type: "standard" } },
        message: "Medal retrieved",
      }),
    }),
  );

  // Medal stats
  await page.route("**/api/v1/medal/stats", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { stats: { gold: { standard: 2, training: 1 }, silver: { standard: 5 } }, total_medals: 8 },
        message: "Medal stats retrieved",
      }),
    }),
  );

  // Medal skills
  await page.route("**/api/v1/medal/skills", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          skills: [
            { tag: "dp", level: "silver", melo: 1450 },
            { tag: "math", level: "gold", melo: 1600 },
          ],
        },
        message: "Skill medals retrieved",
      }),
    }),
  );

  // M-Elo (for total solved)
  await page.route("**/api/v1/training/melo", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          melos: [
            { tag: "dp", elo: 1450, total_submissions: 15 },
            { tag: "math", elo: 1600, total_submissions: 20 },
          ],
        },
        message: "M-Elo retrieved",
      }),
    }),
  );

  // Check-in status
  await page.route("**/api/v1/checkin/status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          checked_in_today: true,
          streak_days: 5,
          last_checkin_date: "2025-06-01",
          makeup_used_this_week: 0,
          makeup_limit: 2,
          next_reward: 10,
          can_makeup: true,
          checked_dates_this_week: ["2025-06-01"],
        },
        message: "Check-in status retrieved",
      }),
    }),
  );

  // PP rank
  await page.route("**/api/v1/auth/pp-rank", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { rank: 42, total_users: 500, top_percent: 8.4 },
        message: "PP rank retrieved",
      }),
    }),
  );

  // Avatar upload (mock)
  await page.route("**/api/v1/auth/avatar**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { avatar_path: "/uploads/avatars/mock.png" },
        message: "Avatar uploaded",
      }),
    }),
  );
}

/** Mock PUT /auth/profile to accept profile save. */
async function mockProfileSaveAPI(page: import("@playwright/test").Page) {
  await page.route(
    (route) => route.request.method() === "PUT" && route.request.url().includes("/api/v1/auth/profile"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: null,
          message: "Profile updated",
        }),
      }),
  );
}

/** Mock CF handle bind API. */
async function mockCFBindAPI(page: import("@playwright/test").Page) {
  await page.route(
    (route) => route.request.method() === "POST" && route.request.url().includes("/api/v1/cf-handle/bind"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: { verification_code: "ABC123XYZ" },
          message: "CF handle binding initiated",
        }),
      }),
  );
}

/** Mock CF handle verify API. */
async function mockCFVerifyAPI(page: import("@playwright/test").Page) {
  await page.route(
    (route) => route.request.method() === "POST" && route.request.url().includes("/api/v1/cf-handle/verify"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: null,
          message: "CF handle verified",
        }),
      }),
  );
}

/** Mock CF handle unbind API. */
async function mockCFUnbindAPI(page: import("@playwright/test").Page) {
  await page.route(
    (route) => route.request.method() === "DELETE" && route.request.url().includes("/api/v1/cf-handle/unbind"),
    (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: null,
          message: "CF handle unbound",
        }),
      }),
  );
}

// ---------------------------------------------------------------------------
// Tests: Settings page
// ---------------------------------------------------------------------------

test.describe("Settings Page", () => {
  test("loads and displays display mode settings", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockSettingsAPI(page, "medal");

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Verify page heading
    await expect(page.getByText("Settings")).toBeVisible();

    // Verify display mode section
    await expect(page.getByText("Display Mode")).toBeVisible();

    // Verify medal mode option
    await expect(page.getByText("Medal Mode")).toBeVisible();

    // Verify CF tier mode option
    await expect(page.getByText("CF Tier Mode")).toBeVisible();

    // Medal mode should be selected by default
    const medalRadio = page.locator('input[value="medal"]');
    await expect(medalRadio).toBeChecked();

    // Verify Save button
    await expect(page.getByRole("button", { name: /Save/ })).toBeVisible();
  });

  test("switches display mode from medal to cf_tier and saves", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockSettingsAPI(page, "medal");
    await mockSettingsSaveAPI(page);

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Initially medal mode is selected
    await expect(page.locator('input[value="medal"]')).toBeChecked();

    // Click CF Tier mode radio
    await page.click('input[value="cf_tier"]');

    // CF Tier should now be checked
    await expect(page.locator('input[value="cf_tier"]')).toBeChecked();
    await expect(page.locator('input[value="medal"]')).not.toBeChecked();

    // Click Save
    await page.click('button:has-text("Save")');

    // Verify success message
    await expect(page.getByText(/saved/i)).toBeVisible({ timeout: 5000 });
  });

  test("shows error when save API fails", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockSettingsAPI(page, "medal");

    // Mock save to fail
    await page.route(
      (route) => route.request.method() === "PUT" && route.request.url().includes("/api/v1/auth/settings"),
      (route) =>
        route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            error: { code: "INTERNAL_ERROR", message: "Failed to save settings" },
          }),
        }),
    );

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // Change mode and try to save
    await page.click('input[value="cf_tier"]');
    await page.click('button:has-text("Save")');

    // Error message should be displayed
    await expect(page.getByText(/failed/i)).toBeVisible({ timeout: 5000 });
  });

  test("loads with cf_tier mode pre-selected when settings return cf_tier", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockSettingsAPI(page, "cf_tier");

    await page.goto("/settings");
    await page.waitForLoadState("networkidle");

    // CF Tier mode should be pre-selected
    await expect(page.locator('input[value="cf_tier"]')).toBeChecked();
  });
});

// ---------------------------------------------------------------------------
// Tests: Profile page
// ---------------------------------------------------------------------------

test.describe("Profile Page", () => {
  test("loads and displays user profile information", async ({ page }) => {
    await mockAuth(page);
    await mockProfileAPIs(page);
    await mockHealthAPI(page);

    await page.goto("/profile");
    await page.waitForLoadState("networkidle");

    // Verify profile heading
    await expect(page.getByText("Profile")).toBeVisible();

    // Verify username
    await expect(page.getByText("settingsuser")).toBeVisible();

    // Verify email
    await expect(page.getByText("settings@example.com")).toBeVisible();

    // Verify stats cards
    await expect(page.getByText("Elo Rating")).toBeVisible();
    await expect(page.getByText("1500")).toBeVisible();
    await expect(page.getByText("Performance Points")).toBeVisible();
    await expect(page.getByText("Tokens")).toBeVisible();
    await expect(page.getByText("300")).toBeVisible();
  });

  test("shows Elo trend chart with data", async ({ page }) => {
    await mockAuth(page);
    await mockProfileAPIs(page);
    await mockHealthAPI(page);

    await page.goto("/profile");
    await page.waitForLoadState("networkidle");

    // Verify Elo Trend section
    await expect(page.getByText("Elo Trend")).toBeVisible();
  });

  test("shows CF handle binding section when no CF handle", async ({ page }) => {
    await mockAuth(page);
    await mockProfileAPIs(page);
    await mockHealthAPI(page);

    await page.goto("/profile");
    await page.waitForLoadState("networkidle");

    // Verify CF handle binding prompt
    await expect(page.getByText("Link your Codeforces account")).toBeVisible();
    await expect(page.getByText("Bind Handle")).toBeVisible();
  });

  test("shows CF handle info when already bound", async ({ page }) => {
    await mockAuth(page, fakeUserWithCF);
    await mockProfileAPIs(page, fakeUserWithCF);
    await mockHealthAPI(page);

    await page.goto("/profile");
    await page.waitForLoadState("networkidle");

    // CF handle should be displayed
    await expect(page.getByText("testcfhandle")).toBeVisible();
    // Verified badge should appear
    await expect(page.getByText("Verified")).toBeVisible();

    // No "Link your Codeforces account" prompt
    await expect(page.getByText("Link your Codeforces account")).not.toBeVisible();
  });

  test("edit profile allows changing username and email", async ({ page }) => {
    await mockAuth(page);
    await mockProfileAPIs(page);
    await mockProfileSaveAPI(page);
    await mockHealthAPI(page);

    await page.goto("/profile");
    await page.waitForLoadState("networkidle");

    // Click "Edit Profile" button
    await page.click('button:has-text("Edit Profile")');

    // Verify editable fields appear
    await expect(page.getByText("Username")).toBeVisible();
    await expect(page.getByText("Email")).toBeVisible();

    // Change username
    const usernameInput = page.locator('input[value="settingsuser"]');
    await usernameInput.clear();
    await usernameInput.fill("newusername");

    // Click Save
    await page.click('button:has-text("Save")');

    // Success message should appear
    await expect(page.getByText(/updated/i)).toBeVisible({ timeout: 5000 });
  });

  test("shows PP Global Ranking section", async ({ page }) => {
    await mockAuth(page);
    await mockProfileAPIs(page);
    await mockHealthAPI(page);

    await page.goto("/profile");
    await page.waitForLoadState("networkidle");

    // PP Global Ranking section
    await expect(page.getByText("PP Global Ranking")).toBeVisible();
    await expect(page.getByText("View Leaderboard")).toBeVisible();
  });

  test("navigates to CF bind page from profile", async ({ page }) => {
    await mockAuth(page);
    await mockProfileAPIs(page);
    await mockHealthAPI(page);

    await page.goto("/profile");
    await page.waitForLoadState("networkidle");

    // Click "Bind Handle" button
    await page.click('button:has-text("Bind Handle")');

    // Should navigate to CF bind page
    await page.waitForURL("**/profile/cf-bind", { timeout: 5000 });
    await expect(page).toHaveURL(/\/profile\/cf-bind/);
  });
});

// ---------------------------------------------------------------------------
// Tests: CF Handle Binding page
// ---------------------------------------------------------------------------

test.describe("CF Bind Page", () => {
  test("displays CF handle binding form when no handle bound", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);

    await page.goto("/profile/cf-bind");
    await page.waitForLoadState("networkidle");

    // Verify bind page heading (text: "Bind Codeforces Handle" per i18n)
    await expect(page.getByText("Bind Codeforces Handle")).toBeVisible();

    // Verify input field
    await expect(page.locator("#cfHandle")).toBeVisible();

    // Verify bind button
    await expect(page.getByRole("button", { name: /Bind/ })).toBeVisible();

    // Verify back link
    await expect(page.getByText("Back to Profile")).toBeVisible();
  });

  test("bind CF handle shows verification code", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockCFBindAPI(page);

    // After binding, fetchUser is called - mock it to return user with cf_handle
    await page.route("**/api/v1/auth/me", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            ...fakeUser,
            cf_handle: "testcf",
            cf_handle_verified: false,
          },
          message: "User profile retrieved",
        }),
      }),
    );

    await page.goto("/profile/cf-bind");
    await page.waitForLoadState("networkidle");

    // Enter CF handle
    await page.fill("#cfHandle", "testcf");

    // Click bind
    await page.click('button:has-text("Bind")');

    // Should show verification code
    await expect(page.getByText("ABC123XYZ")).toBeVisible({ timeout: 5000 });

    // Should show verify button
    await expect(page.getByRole("button", { name: /Verify/ })).toBeVisible();
  });

  test("shows verified state when CF handle is already verified", async ({ page }) => {
    await mockAuth(page, fakeUserWithCF);
    await mockAuthMeAPI(page, fakeUserWithCF);
    await mockHealthAPI(page);

    await page.goto("/profile/cf-bind");
    await page.waitForLoadState("networkidle");

    // Should show verified state (text: "Codeforces Handle Bound" per i18n)
    await expect(page.getByText("Codeforces Handle Bound")).toBeVisible();
    await expect(page.getByText("testcfhandle")).toBeVisible();

    // Should show unbind button
    await expect(page.getByRole("button", { name: /Unbind/ })).toBeVisible();
  });

  test("unbind CF handle returns to idle state", async ({ page }) => {
    await mockAuth(page, fakeUserWithCF);
    await mockAuthMeAPI(page, fakeUserWithCF);
    await mockHealthAPI(page);
    await mockCFUnbindAPI(page);

    // After unbinding, fetchUser returns user without cf_handle
    let unbindCalled = false;
    await page.route("**/api/v1/auth/me", (route) => {
      if (unbindCalled) {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            success: true,
            data: fakeUser,
            message: "User profile retrieved",
          }),
        });
      } else {
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            success: true,
            data: fakeUserWithCF,
            message: "User profile retrieved",
          }),
        });
      }
    });

    await page.goto("/profile/cf-bind");
    await page.waitForLoadState("networkidle");

    // Click unbind
    unbindCalled = true;
    await page.click('button:has-text("Unbind")');

    // Should return to idle state (binding form visible)
    await expect(page.locator("#cfHandle")).toBeVisible({ timeout: 5000 });
  });

  test("shows error when bind API fails", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);

    await page.route(
      (route) => route.request.method() === "POST" && route.request.url().includes("/api/v1/cf-handle/bind"),
      (route) =>
        route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({
            success: false,
            error: { code: "HANDLE_TAKEN", message: "CF handle already bound to another account" },
          }),
        }),
    );

    await page.goto("/profile/cf-bind");
    await page.waitForLoadState("networkidle");

    await page.fill("#cfHandle", "takenhandle");
    await page.click('button:has-text("Bind")');

    // Error should be displayed
    await expect(page.getByText(/already bound/i)).toBeVisible({ timeout: 5000 });
  });

  test("navigates back to profile page", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);

    await page.goto("/profile/cf-bind");
    await page.waitForLoadState("networkidle");

    // Click "Back to Profile"
    await page.click('button:has-text("Back to Profile")');

    await page.waitForURL("**/profile", { timeout: 5000 });
    await expect(page).toHaveURL(/\/profile$/);
  });
});
