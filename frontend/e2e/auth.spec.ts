import { test, expect } from "@playwright/test";

/**
 * Auth flow E2E tests (register, login, token persistence).
 *
 * Strategy: All API calls are intercepted with mock responses so the tests
 * can run against the Vite dev server alone (no backend required). Tests
 * that truly require a live backend are wrapped with test.skip().
 */

// ---------------------------------------------------------------------------
// Mock helpers
// ---------------------------------------------------------------------------

/** Mock user object returned by /auth/me and stored in auth-storage. */
const fakeUser = {
  id: "00000000-0000-0000-0000-000000000001",
  username: "testuser",
  email: "testuser@example.com",
  cf_handle: null,
  cf_handle_verified: false,
  elo: 1200,
  pp: 0,
  tokens: 100,
  is_active: true,
  is_admin: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
  last_login_at: "2025-06-01T00:00:00Z",
};

/** Intercept /auth/register and return a successful registration response. */
async function mockRegisterAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/register", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          user: fakeUser,
          tokens: {
            access_token: "fake-access-token-123",
            refresh_token: "fake-refresh-token-123",
            token_type: "bearer",
          },
        },
        message: "User registered successfully",
      }),
    }),
  );
}

/** Intercept /auth/login and return a successful login response. */
async function mockLoginAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/auth/login", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          access_token: "fake-access-token-456",
          refresh_token: "fake-refresh-token-456",
          token_type: "bearer",
        },
        message: "Login successful",
      }),
    }),
  );
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

/** Intercept dashboard-related API calls so the post-login page loads. */
async function mockDashboardAPIs(page: import("@playwright/test").Page) {
  // Transactions endpoint (used by DashboardPage)
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

  // Active contest
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

  // M-Elo data (used by DashboardCharts)
  await page.route("**/api/v1/training/m-elo", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { melos: [], global_elo: 1200 },
        message: "M-Elo data retrieved",
      }),
    }),
  );

  // Elo history
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

  // PP contributions
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

test.describe("Auth Flow", () => {
  test("new user registration - redirects to dashboard on success", async ({ page }) => {
    // Precondition: Vite dev server is running. API calls are mocked.
    await mockRegisterAPI(page);
    await mockAuthMeAPI(page);
    await mockDashboardAPIs(page);

    // Navigate to register page
    await page.goto("/register");
    await page.waitForLoadState("networkidle");

    // Verify we are on the register page
    await expect(page.getByRole("heading", { name: "Create Account" })).toBeVisible();

    // Fill out the registration form
    await page.fill("#username", "testuser");
    await page.fill("#email", "testuser@example.com");
    await page.fill("#password", "Password123");
    await page.fill("#confirmPassword", "Password123");

    // Submit the form
    await page.click('button:has-text("Create Account")');

    // Should redirect to /dashboard
    await page.waitForURL("**/dashboard", { timeout: 5000 });
    await expect(page).toHaveURL(/\/dashboard/);

    // Dashboard heading should be visible
    await expect(page.getByText("Welcome back, testuser")).toBeVisible();
  });

  test("login with existing account - redirects to dashboard", async ({ page }) => {
    // Precondition: Vite dev server is running. API calls are mocked.
    await mockLoginAPI(page);
    await mockAuthMeAPI(page);
    await mockDashboardAPIs(page);

    // Navigate to login page (root path)
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Verify we are on the login page
    await expect(page.getByRole("heading", { name: "Welcome Back" })).toBeVisible();

    // Fill out the login form
    await page.fill("#email", "testuser@example.com");
    await page.fill("#password", "Password123");

    // Submit the form
    await page.click('button:has-text("Sign In")');

    // Should redirect to /dashboard
    await page.waitForURL("**/dashboard", { timeout: 5000 });
    await expect(page).toHaveURL(/\/dashboard/);

    // Dashboard should show the user's info
    await expect(page.getByText("Welcome back, testuser")).toBeVisible();
  });

  test("token persists in localStorage after login", async ({ page }) => {
    // Precondition: Vite dev server is running. API calls are mocked.
    await mockLoginAPI(page);
    await mockAuthMeAPI(page);
    await mockDashboardAPIs(page);

    // Navigate to login page
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Login
    await page.fill("#email", "testuser@example.com");
    await page.fill("#password", "Password123");
    await page.click('button:has-text("Sign In")');

    // Wait for dashboard to load
    await page.waitForURL("**/dashboard", { timeout: 5000 });

    // Verify tokens are persisted in localStorage
    const accessToken = await page.evaluate(() => localStorage.getItem("access_token"));
    const refreshToken = await page.evaluate(() => localStorage.getItem("refresh_token"));

    expect(accessToken).toBe("fake-access-token-456");
    expect(refreshToken).toBe("fake-refresh-token-456");

    // Verify auth-storage state contains user data
    const authStorage = await page.evaluate(() => localStorage.getItem("auth-storage"));
    expect(authStorage).toBeTruthy();
    const parsed = JSON.parse(authStorage!);
    expect(parsed.state.isAuthenticated).toBe(true);
    expect(parsed.state.user.username).toBe("testuser");
  });

  test("login shows error message on invalid credentials", async ({ page }) => {
    // Precondition: Vite dev server is running. API calls are mocked.
    // Override the login endpoint to return an error
    await page.route("**/api/v1/auth/login", (route) =>
      route.fulfill({
        status: 401,
        contentType: "application/json",
        body: JSON.stringify({
          success: false,
          error: {
            code: "INVALID_CREDENTIALS",
            message: "Invalid email or password",
          },
        }),
      }),
    );

    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Fill out the login form with wrong credentials
    await page.fill("#email", "wrong@example.com");
    await page.fill("#password", "WrongPassword1");
    await page.click('button:has-text("Sign In")');

    // Error message should be visible
    await expect(page.getByText(/invalid/i)).toBeVisible();

    // Should still be on the login page
    await expect(page).toHaveURL(/\//);
  });

  test("register shows error on password mismatch", async ({ page }) => {
    // Precondition: Vite dev server is running. No API mock needed
    // because the frontend validates password match before sending the request.
    await page.goto("/register");
    await page.waitForLoadState("networkidle");

    // Fill passwords that don't match
    await page.fill("#username", "testuser");
    await page.fill("#email", "testuser@example.com");
    await page.fill("#password", "Password123");
    await page.fill("#confirmPassword", "DifferentPassword");
    await page.click('button:has-text("Create Account")');

    // Client-side error should be displayed
    await expect(page.getByText("Passwords do not match")).toBeVisible();

    // Should still be on the register page
    await expect(page).toHaveURL(/\/register/);
  });

  test("navigation between login and register pages", async ({ page }) => {
    // Precondition: Vite dev server is running.
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Verify we start on login page
    await expect(page.getByRole("heading", { name: "Welcome Back" })).toBeVisible();

    // Click the "Create one" link to navigate to register
    await page.click('a:has-text("Create one")');
    await page.waitForLoadState("networkidle");

    // Verify we are on register page
    await expect(page.getByRole("heading", { name: "Create Account" })).toBeVisible();
    await expect(page).toHaveURL(/\/register/);

    // Click "Sign In" link to navigate back to login
    await page.click('a:has-text("Sign In")');
    await page.waitForLoadState("networkidle");

    // Verify we are back on login page
    await expect(page.getByRole("heading", { name: "Welcome Back" })).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
  });

  // This test requires a live backend to exercise the real auth flow.
  // Skip when running without Docker (CI=false, no backend).
  test.skip("full registration + login round-trip against live backend", async ({ page }) => {
    // This test would register a new user, log out, then log back in
    // using the real backend API. It is skipped by default because it
    // requires the full Docker environment to be running.
    const uniqueSuffix = Date.now();
    await page.goto("/register");
    await page.fill("#username", `e2e_user_${uniqueSuffix}`);
    await page.fill("#email", `e2e_${uniqueSuffix}@test.com`);
    await page.fill("#password", "TestPass123");
    await page.fill("#confirmPassword", "TestPass123");
    await page.click('button:has-text("Create Account")');
    await page.waitForURL("**/dashboard", { timeout: 10000 });
    await expect(page.getByText(/Welcome back/)).toBeVisible();
  });
});
