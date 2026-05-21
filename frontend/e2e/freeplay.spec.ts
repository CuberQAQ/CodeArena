import { test, expect } from "@playwright/test";

/**
 * FreePlay flow E2E tests (search, recommend, session, submit, quit).
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
  username: "freeplayuser",
  email: "freeplay@example.com",
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

const mockProblem = {
  contest_id: 1900,
  index: "A",
  name: "Frog Jump",
  rating: 1400,
  tags: ["dp", "greedy"],
  url: "https://codeforces.com/contest/1900/problem/A",
};

async function mockAuth(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const user = {
      id: "00000000-0000-0000-0000-000000000001",
      username: "freeplayuser",
      email: "freeplay@example.com",
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
    localStorage.setItem("access_token", "fake-freeplay-token");
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: {
          user,
          token: "fake-freeplay-token",
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

/** Mock /free-play/search returning a found problem. */
async function mockSearchAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/free-play/search", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          problem: mockProblem,
          found: true,
          message: "Problem found",
        },
        message: "Success",
      }),
    }),
  );
}

/** Mock /free-play/recommend returning a found problem with a recommended tag. */
async function mockRecommendAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/free-play/recommend", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          problem: mockProblem,
          found: true,
          message: "Problem recommended",
          recommended_tag: "dp",
        },
        message: "Success",
      }),
    }),
  );
}

/** Mock /free-play/start returning a session ID. */
async function mockStartAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/free-play/start", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          session_id: "fp-session-001",
          problem: mockProblem,
          status: "active",
        },
        message: "Session started",
      }),
    }),
  );
}

/** Mock /free-play/active (returns null when no active session). */
async function mockActiveAPI_none(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/free-play/active", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: null,
        message: "No active session",
      }),
    }),
  );
}

/** Mock /free-play/active returning an active session. */
async function mockActiveAPI_withSession(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/free-play/active", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          session_id: "fp-session-001",
          problem: mockProblem,
          status: "active",
        },
        message: "Active session found",
      }),
    }),
  );
}

/** Mock /free-play/:id/submit returning AC result. */
async function mockSubmitAPI_ac(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/free-play/fp-session-001/submit", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          session_id: "fp-session-001",
          solved: true,
          status: "completed",
          elo_change: 15,
          pp_change: 2.5,
          s_value: 0.8,
          tokens_earned: 30,
          overkill_multiplier: 1.2,
          achievements: [],
        },
        message: "Submission recorded",
      }),
    }),
  );
}

/** Mock /free-play/:id/submit returning WA result. */
async function mockSubmitAPI_wa(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/free-play/fp-session-001/submit", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          session_id: "fp-session-001",
          solved: false,
          status: "completed",
          elo_change: -5,
          pp_change: 0,
          s_value: 0,
          tokens_earned: 0,
          overkill_multiplier: 1.0,
          achievements: [],
        },
        message: "Submission recorded",
      }),
    }),
  );
}

/** Mock /free-play/:id/quit. */
async function mockQuitAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/free-play/fp-session-001/quit", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          session_id: "fp-session-001",
          status: "abandoned",
          elo_change: -3,
          new_elo: 1347,
          penalty: 3,
        },
        message: "Session quit",
      }),
    }),
  );
}

/** Mock submission-tracking/status to return no match (keeps session active). */
async function mockTrackingIdle(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/submission-tracking/status**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: { status: "waiting" },
        message: "No match",
      }),
    }),
  );
}

/** Mock CF problem page (so ProblemViewer iframe does not error). */
async function mockCFProblemPage(page: import("@playwright/test").Page) {
  await page.route("**/codeforces.com/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/html",
      body: "<html><body>Mock CF Problem</body></html>",
    }),
  );
}

/** Mock /time-factor-prediction (used by SolvingTimeline in session sidebar). */
async function mockTimeFactorPrediction(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/time-factor-prediction**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          expected_time_minutes: 15,
          time_points: [
            { minutes: 5, time_factor: 1.2, elo_change_estimate: 10 },
            { minutes: 15, time_factor: 1.0, elo_change_estimate: 5 },
            { minutes: 30, time_factor: 0.8, elo_change_estimate: -5 },
          ],
        },
        message: "Prediction retrieved",
      }),
    }),
  );
}

// ---------------------------------------------------------------------------
// Tests: FreePlay main page (search & recommend)
// ---------------------------------------------------------------------------

test.describe("FreePlay Main Page", () => {
  test("loads and displays manual filter tab with rating sliders and tags", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);

    await page.goto("/free-play");
    await page.waitForLoadState("networkidle");

    // Verify page heading
    await expect(page.getByRole("heading", { name: "Free Play" })).toBeVisible();

    // Verify tab switcher
    await expect(page.getByText("Manual Filter")).toBeVisible();
    await expect(page.getByText("Adaptive Recommend")).toBeVisible();

    // Verify rating range section
    await expect(page.getByText("Rating Range")).toBeVisible();
    await expect(page.getByText("Min")).toBeVisible();
    await expect(page.getByText("Max")).toBeVisible();

    // Verify tags section
    await expect(page.getByText("Tags")).toBeVisible();

    // Verify some preset tags
    await expect(page.getByText("dp")).toBeVisible();
    await expect(page.getByText("greedy")).toBeVisible();
    await expect(page.getByText("math")).toBeVisible();

    // Verify search button
    await expect(page.getByRole("button", { name: /Search/ })).toBeVisible();
  });

  test("manual search finds a problem and displays ProblemCard", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockSearchAPI(page);

    await page.goto("/free-play");
    await page.waitForLoadState("networkidle");

    // Click Search
    await page.click('button:has-text("Search")');

    // Wait for problem card to appear
    await expect(page.getByText("Frog Jump")).toBeVisible({ timeout: 5000 });

    // Verify problem details are displayed
    await expect(page.getByText("1900A")).toBeVisible();
    await expect(page.getByText("1400")).toBeVisible();
    await expect(page.getByText("dp")).toBeVisible();
    await expect(page.getByText("greedy")).toBeVisible();

    // Verify "Start Problem" button
    await expect(page.getByRole("button", { name: /Start Problem/ })).toBeVisible();

    // Verify "Open on Codeforces" link
    await expect(page.getByText("Open on Codeforces")).toBeVisible();
  });

  test("adaptive recommend finds a problem and shows recommendation reason", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockRecommendAPI(page);

    await page.goto("/free-play");
    await page.waitForLoadState("networkidle");

    // Switch to Adaptive Recommend tab
    await page.click('button:has-text("Adaptive Recommend")');

    // Click recommend button
    await page.click('button:has-text("Recommend")');

    // Wait for problem card
    await expect(page.getByText("Frog Jump")).toBeVisible({ timeout: 5000 });

    // Verify recommendation reason is shown (mentions the tag)
    await expect(page.getByText(/DP/)).toBeVisible();
  });

  test("search returns no problem and shows error message", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);

    await page.route("**/api/v1/free-play/search", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            problem: null,
            found: false,
            message: "No problems match your criteria",
          },
          message: "Success",
        }),
      }),
    );

    await page.goto("/free-play");
    await page.waitForLoadState("networkidle");

    await page.click('button:has-text("Search")');

    // Error message should appear
    await expect(page.getByText("No problems match your criteria")).toBeVisible({ timeout: 5000 });
  });

  test("tag selection toggles tags on and off", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);

    await page.goto("/free-play");
    await page.waitForLoadState("networkidle");

    // Click "dp" tag to select it
    const dpTag = page.locator('button:has-text("dp")').first();
    await dpTag.click();

    // dp tag should now be selected (visual change via class)
    // Click it again to deselect
    await dpTag.click();

    // Verify tag is still present (not removed)
    await expect(dpTag).toBeVisible();
  });

  test("More Tags dialog opens and shows extra tags", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);

    await page.goto("/free-play");
    await page.waitForLoadState("networkidle");

    // Click "More Tags" button
    await page.click('button:has-text("More")');

    // Dialog should open with search input and extra tags
    await expect(page.getByPlaceholder(/search/i)).toBeVisible();
    await expect(page.getByText("trees")).toBeVisible();
    await expect(page.getByText("geometry")).toBeVisible();
    await expect(page.getByText("OK")).toBeVisible();
  });

  test("starts a session and navigates to session page", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockSearchAPI(page);
    await mockStartAPI(page);

    await page.goto("/free-play");
    await page.waitForLoadState("networkidle");

    // Search for a problem
    await page.click('button:has-text("Search")');
    await expect(page.getByText("Frog Jump")).toBeVisible({ timeout: 5000 });

    // Click "Start Problem"
    await page.click('button:has-text("Start Problem")');

    // Should navigate to session page
    await page.waitForURL("**/free-play/session/fp-session-001", { timeout: 5000 });
    await expect(page).toHaveURL(/\/free-play\/session\/fp-session-001/);
  });
});

// ---------------------------------------------------------------------------
// Tests: FreePlay Session page (active session, quit, result)
// ---------------------------------------------------------------------------

test.describe("FreePlay Session Page", () => {
  test("active session displays problem info, timer, and quit button", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockCFProblemPage(page);
    await mockTrackingIdle(page);
    await mockTimeFactorPrediction(page);

    // Navigate directly to session page with problem info in state
    await page.goto("/free-play", { waitUntil: "networkidle" });

    // Use addInitScript to set up navigation state before going to session page
    await page.goto("/free-play/session/fp-session-001", {
      waitUntil: "commit",
    });

    // Since we don't have navigation state, the page will try to load active session
    // We mock it to return the problem so the session page renders
    await mockActiveAPI_withSession(page);
    await page.reload();
    await page.waitForLoadState("networkidle");

    // Verify problem info panel
    await expect(page.getByText("Frog Jump")).toBeVisible();
    await expect(page.getByText("1900A")).toBeVisible();
    await expect(page.getByText("1400")).toBeVisible();

    // Verify timer is displayed
    await expect(page.getByText(/00:00/)).toBeVisible();

    // Verify auto-tracking status
    await expect(page.getByText("Auto Tracking")).toBeVisible();

    // Verify quit button (text is "Give Up" per i18n)
    await expect(page.getByRole("button", { name: /Give Up/ })).toBeVisible();
  });

  test("quit session shows abandoned result view", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockCFProblemPage(page);
    await mockTrackingIdle(page);
    await mockTimeFactorPrediction(page);
    await mockQuitAPI(page);
    await mockActiveAPI_withSession(page);

    await page.goto("/free-play/session/fp-session-001");
    await page.waitForLoadState("networkidle");

    // Wait for page to load
    await expect(page.getByText("Frog Jump")).toBeVisible({ timeout: 10000 });

    // Click "Give Up" button (text per i18n: free_play:session.quit)
    await page.click('button:has-text("Give Up")');

    // Should show abandoned result view (text: "Session Abandoned")
    await expect(page.getByText("Session Abandoned")).toBeVisible({ timeout: 5000 });

    // Verify Elo change is displayed
    await expect(page.getByText("-3")).toBeVisible();

    // Verify "New Free Play" and "Back to Dashboard" buttons
    await expect(page.getByRole("button", { name: /New Free Play/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Back to Dashboard/ })).toBeVisible();
  });

  test("submit with AC shows completed result view with positive Elo change", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockCFProblemPage(page);
    await mockTrackingIdle(page);
    await mockTimeFactorPrediction(page);
    await mockSubmitAPI_ac(page);
    await mockActiveAPI_withSession(page);

    // Navigate to session and trigger submit via tracking match
    await page.route("**/api/v1/submission-tracking/status**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: { status: "settled", verdict: "OK", attempts: 1, error_count: 0 },
          message: "Matched",
        }),
      }),
    );

    await page.goto("/free-play/session/fp-session-001");
    await page.waitForLoadState("networkidle");

    // Wait for auto-tracking to detect the submission and auto-submit
    // This may take up to 5 seconds (polling interval)
    // Text is "Session Complete" per i18n
    await expect(page.getByText("Session Complete")).toBeVisible({ timeout: 15000 });

    // Verify Elo change
    await expect(page.getByText("+15")).toBeVisible();

    // Verify PP change
    await expect(page.getByText("+2.5")).toBeVisible();

    // Verify tokens earned
    await expect(page.getByText("30")).toBeVisible();

    // Verify overkill bonus section
    await expect(page.getByText("Overkill Bonus")).toBeVisible();

    // Verify problem info in result card
    await expect(page.getByText("Frog Jump")).toBeVisible();
    await expect(page.getByText("dp")).toBeVisible();
    await expect(page.getByText("greedy")).toBeVisible();
  });

  test("submit with WA shows not solved result view with negative Elo change", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockCFProblemPage(page);
    await mockTimeFactorPrediction(page);
    await mockSubmitAPI_wa(page);
    await mockActiveAPI_withSession(page);

    await page.route("**/api/v1/submission-tracking/status**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: { status: "settled", verdict: "WRONG_ANSWER", attempts: 1, error_count: 1 },
          message: "Matched",
        }),
      }),
    );

    await page.goto("/free-play/session/fp-session-001");
    await page.waitForLoadState("networkidle");

    // Wait for auto-tracking to detect and auto-submit
    await expect(page.getByText("Not Solved")).toBeVisible({ timeout: 15000 });

    // Verify negative Elo change
    await expect(page.getByText("-5")).toBeVisible();
  });

  test("no active session redirects back to free-play page", async ({ page }) => {
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);
    await mockActiveAPI_none(page);

    await page.goto("/free-play/session/fp-session-001");

    // Should redirect to /free-play
    await page.waitForURL("**/free-play", { timeout: 5000 });
    await expect(page).toHaveURL(/\/free-play$/);
  });
});
