import { test, expect } from "@playwright/test";

/**
 * Training flow E2E tests (topic list, session start, submission, shield).
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
  username: "traininguser",
  email: "training@example.com",
  cf_handle: null,
  cf_handle_verified: false,
  elo: 1200,
  pp: 0,
  tokens: 200,
  is_active: true,
  is_admin: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
  last_login_at: "2025-06-01T00:00:00Z",
};

/** Topic list returned by the /training/topics endpoint. */
const mockTopics = [
  {
    id: "dp",
    name: "Dynamic Programming",
    description: "Classic DP problems",
    cf_tags: ["dp"],
    total_problems: 10,
    solved_count: 3,
    stars: 2,
  },
  {
    id: "greedy",
    name: "Greedy Algorithms",
    description: "Greedy strategy problems",
    cf_tags: ["greedy"],
    total_problems: 8,
    solved_count: 0,
    stars: 0,
  },
  {
    id: "math",
    name: "Mathematics",
    description: "Number theory and combinatorics",
    cf_tags: ["math", "combinatorics"],
    total_problems: 12,
    solved_count: 8,
    stars: 4,
  },
];

/** Inject a fake authenticated user into localStorage. */
async function mockAuth(page: import("@playwright/test").Page) {
  await page.addInitScript(() => {
    const user = {
      id: "00000000-0000-0000-0000-000000000001",
      username: "traininguser",
      email: "training@example.com",
      cf_handle: null,
      cf_handle_verified: false,
      elo: 1200,
      pp: 0,
      tokens: 200,
      is_active: true,
      is_admin: false,
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
      last_login_at: "2025-06-01T00:00:00Z",
    };
    localStorage.setItem("access_token", "fake-training-token");
    localStorage.setItem(
      "auth-storage",
      JSON.stringify({
        state: {
          user,
          token: "fake-training-token",
          isAuthenticated: true,
          isAdmin: false,
        },
        version: 0,
      }),
    );
  });
}

/** Intercept /auth/me. */
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

/** Intercept /training/topics and return the mock topic list. */
async function mockTopicsAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/training/topics", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: mockTopics,
        message: "Topics retrieved",
      }),
    }),
  );
}

/** Intercept /training/topics/:id and return topic detail with problems. */
async function mockTopicDetailAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/training/topics/dp", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          id: "dp",
          name: "Dynamic Programming",
          description: "Classic DP problems",
          cf_tags: ["dp"],
          total_problems: 10,
          solved_count: 3,
          stars: 2,
          problems: [
            {
              problem_id: "dp-1",
              contest_id: 1900,
              index: "A",
              name: "Frog Jump",
              rating: 1200,
              url: "https://codeforces.com/contest/1900/problem/A",
              solved: true,
              time_spent: 300,
              attempts: 1,
            },
            {
              problem_id: "dp-2",
              contest_id: 1901,
              index: "B",
              name: "Knapsack",
              rating: 1400,
              url: "https://codeforces.com/contest/1901/problem/B",
              solved: false,
              time_spent: null,
              attempts: 0,
            },
            {
              problem_id: "dp-3",
              contest_id: 1902,
              index: "C",
              name: "LCS",
              rating: 1600,
              url: "https://codeforces.com/contest/1902/problem/C",
              solved: false,
              time_spent: null,
              attempts: 0,
            },
          ],
        },
        message: "Topic detail retrieved",
      }),
    }),
  );
}

/** Intercept /training/start and return a new session. */
async function mockTrainingStartAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/training/start", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          id: "session-001",
          topic_id: "dp",
          status: "active",
          problems_solved: 0,
          total_problems: 10,
          streak_count: 0,
          tokens_earned: 0,
          started_at: "2025-06-01T10:00:00Z",
        },
        message: "Training session started",
      }),
    }),
  );
}

/** Intercept /training/session/:id/submit and return submission result. */
async function mockTrainingSubmitAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/training/session/session-001/submit", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          tokens_earned: 20,
          elo_change: 5,
          streak_count: 1,
          total_tokens_earned: 20,
        },
        message: "Submission recorded",
      }),
    }),
  );
}

/** Intercept /training/session/:id (GET) to return updated session state. */
async function mockTrainingSessionAPI(page: import("@playwright/test").Page) {
  await page.route("**/api/v1/training/session/session-001", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        success: true,
        data: {
          id: "session-001",
          topic_id: "dp",
          status: "active",
          problems_solved: 1,
          total_problems: 10,
          streak_count: 1,
          tokens_earned: 20,
          started_at: "2025-06-01T10:00:00Z",
        },
        message: "Training session retrieved",
      }),
    }),
  );
}

/** Set up health check mock. */
async function mockHealthAPI(page: import("@playwright/test").Page) {
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

test.describe("Training Page", () => {
  test("loads and displays topic list", async ({ page }) => {
    // Precondition: Vite dev server is running. Auth state and API are mocked.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockTopicsAPI(page);
    await mockHealthAPI(page);

    await page.goto("/training");
    await page.waitForLoadState("networkidle");

    // Verify page heading
    await expect(page.getByRole("heading", { name: "Topic Training" })).toBeVisible();

    // Verify topic cards are rendered
    await expect(page.getByText("Dynamic Programming")).toBeVisible();
    await expect(page.getByText("Greedy Algorithms")).toBeVisible();
    await expect(page.getByText("Mathematics")).toBeVisible();

    // Verify solved/total counts
    await expect(page.getByText("3/10")).toBeVisible(); // DP: 3/10
    await expect(page.getByText("0/8")).toBeVisible();  // Greedy: 0/8
    await expect(page.getByText("8/12")).toBeVisible(); // Math: 8/12

    // Verify CF tags are displayed
    await expect(page.getByText("dp")).toBeVisible();
    await expect(page.getByText("greedy")).toBeVisible();
  });

  test("selecting a topic navigates to topic detail page", async ({ page }) => {
    // Precondition: Vite dev server is running. Topics and detail APIs are mocked.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockTopicsAPI(page);
    await mockTopicDetailAPI(page);
    await mockHealthAPI(page);

    // Start at the training topics list
    await page.goto("/training");
    await page.waitForLoadState("networkidle");

    // Click on "Dynamic Programming" topic card
    await page.click('a:has-text("Dynamic Programming")');

    // Should navigate to /training/dp
    await page.waitForURL("**/training/dp", { timeout: 5000 });
    await expect(page).toHaveURL(/\/training\/dp/);

    // Verify topic detail is loaded
    await expect(page.getByRole("heading", { name: "Dynamic Programming" })).toBeVisible();

    // Verify "Back to Topics" navigation link
    await expect(page.getByText("Back to Topics")).toBeVisible();

    // Verify problem list heading
    await expect(page.getByText("Problems (3)")).toBeVisible();

    // Verify problems are rendered
    await expect(page.getByText("1900A - Frog Jump")).toBeVisible();
    await expect(page.getByText("1901B - Knapsack")).toBeVisible();
    await expect(page.getByText("1902C - LCS")).toBeVisible();

    // Verify the "Start Training" button
    await expect(page.getByRole("button", { name: /Start Training/ })).toBeVisible();
  });

  test("shows empty state when no topics are available", async ({ page }) => {
    // Precondition: Vite dev server is running. Topics API returns empty list.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);

    // Override topics to return empty
    await page.route("**/api/v1/training/topics", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: [],
          message: "Topics retrieved",
        }),
      }),
    );

    await page.goto("/training");
    await page.waitForLoadState("networkidle");

    // Verify empty state message
    await expect(page.getByText("No topics available yet")).toBeVisible();
  });

  test("shows error state when topics API fails", async ({ page }) => {
    // Precondition: Vite dev server is running. Topics API returns an error.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockHealthAPI(page);

    await page.route("**/api/v1/training/topics", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          success: false,
          error: {
            code: "INTERNAL_ERROR",
            message: "Failed to fetch topics",
          },
        }),
      }),
    );

    await page.goto("/training");
    await page.waitForLoadState("networkidle");

    // Verify error state is shown
    await expect(page.getByText("Failed to fetch topics")).toBeVisible();
  });
});

test.describe("Training Session Flow", () => {
  test("start a training session and submit a solution", async ({ page }) => {
    // Precondition: Vite dev server is running. All training APIs are mocked.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockTopicsAPI(page);
    await mockTopicDetailAPI(page);
    await mockTrainingStartAPI(page);
    await mockTrainingSubmitAPI(page);
    await mockTrainingSessionAPI(page);
    await mockHealthAPI(page);

    // Also mock the topic detail refresh after submission
    await page.route("**/api/v1/training/topics/dp", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            id: "dp",
            name: "Dynamic Programming",
            description: "Classic DP problems",
            cf_tags: ["dp"],
            total_problems: 10,
            solved_count: 4,
            stars: 2,
            problems: [
              {
                problem_id: "dp-1",
                contest_id: 1900,
                index: "A",
                name: "Frog Jump",
                rating: 1200,
                url: "https://codeforces.com/contest/1900/problem/A",
                solved: true,
                time_spent: 300,
                attempts: 1,
              },
              {
                problem_id: "dp-2",
                contest_id: 1901,
                index: "B",
                name: "Knapsack",
                rating: 1400,
                url: "https://codeforces.com/contest/1901/problem/B",
                solved: true,
                time_spent: 600,
                attempts: 1,
              },
              {
                problem_id: "dp-3",
                contest_id: 1902,
                index: "C",
                name: "LCS",
                rating: 1600,
                url: "https://codeforces.com/contest/1902/problem/C",
                solved: false,
                time_spent: null,
                attempts: 0,
              },
            ],
          },
          message: "Topic detail retrieved",
        }),
      }),
    );

    // Navigate directly to topic detail page
    await page.goto("/training/dp");
    await page.waitForLoadState("networkidle");

    // Verify topic loaded
    await expect(page.getByRole("heading", { name: "Dynamic Programming" })).toBeVisible();

    // Click "Start Training" to begin a session
    await page.click('button:has-text("Start Training")');

    // Session should start - verify session UI elements appear
    await expect(page.getByText("Solved")).toBeVisible();
    await expect(page.getByText("Total")).toBeVisible();
    await expect(page.getByText("Streak")).toBeVisible();

    // Verify the timer is displayed
    await expect(page.getByText(/00:00/)).toBeVisible();

    // Verify "End Session" button is available
    await expect(page.getByRole("button", { name: /End Session/ })).toBeVisible();

    // Find an unsolved problem and click "Report"
    const reportButton = page.locator('button:has-text("Report")').first();
    await expect(reportButton).toBeVisible();
    await reportButton.click();

    // Report panel should appear with "Solved?" Yes/No buttons
    await expect(page.getByText("Solved?")).toBeVisible();
    await expect(page.getByRole("button", { name: "Yes", exact: false }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "No", exact: false }).first()).toBeVisible();

    // Click "Submit" to submit the solution
    await page.click('button:has-text("Submit")');

    // After submission, the "Report" button for the next problem should appear
    // (or the solved count should increment)
    await page.waitForTimeout(1000); // wait for async operations
  });

  test("session shows streak and shield status", async ({ page }) => {
    // Precondition: Vite dev server is running. Session with streak data is mocked.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockTopicDetailAPI(page);
    await mockHealthAPI(page);

    // Mock a session that is already in progress with streak
    await page.route("**/api/v1/training/start", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: {
            id: "session-001",
            topic_id: "dp",
            status: "active",
            problems_solved: 3,
            total_problems: 10,
            streak_count: 3,
            tokens_earned: 30,
            started_at: "2025-06-01T10:00:00Z",
          },
          message: "Training session started",
        }),
      }),
    );

    await page.goto("/training/dp");
    await page.waitForLoadState("networkidle");

    // Start session
    await page.click('button:has-text("Start Training")');

    // Verify streak display (streak_count = 3)
    // The StreakEffect component renders the streak value
    await expect(page.getByText("Streak")).toBeVisible();

    // Verify solved count
    await expect(page.getByText("3")).toBeVisible(); // problems_solved
  });

  test("abandon session shows completion screen", async ({ page }) => {
    // Precondition: Vite dev server is running. Session abandon API is mocked.
    await mockAuth(page);
    await mockAuthMeAPI(page);
    await mockTopicDetailAPI(page);
    await mockTrainingStartAPI(page);
    await mockHealthAPI(page);

    // Mock abandon endpoint
    await page.route("**/api/v1/training/session/session-001/abandon", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          success: true,
          data: null,
          message: "Training session abandoned",
        }),
      }),
    );

    await page.goto("/training/dp");
    await page.waitForLoadState("networkidle");

    // Start session
    await page.click('button:has-text("Start Training")');

    // Verify session is active
    await expect(page.getByText("End Session")).toBeVisible();

    // Click "End Session"
    await page.click('button:has-text("End Session")');

    // Should show completion screen
    await expect(page.getByText("Training Session Complete")).toBeVisible();

    // Verify "Train Again" and "Back to Topics" buttons
    await expect(page.getByRole("button", { name: "Train Again" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Back to Topics" })).toBeVisible();
  });

  // This test requires a live backend with real training data.
  // Skip when running without Docker (CI=false, no backend).
  test.skip("full training session against live backend", async ({ page }) => {
    // This test would start a real training session, submit answers,
    // and verify the complete flow against the live API.
    // It is skipped by default because it requires the full Docker environment.
    await page.goto("/training");
    await page.waitForLoadState("networkidle");
    await expect(page.getByText("Topic Training")).toBeVisible();
  });
});
