// @integration
// Prerequisites: Docker Compose must be running with backend + frontend.
// Run: docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
// Then: INTEGRATION_BASE_URL=http://localhost:5173 npx playwright test --project=integration e2e/integration/pvp-challenge-flow.spec.ts --workers=1

import { test, expect, type BrowserContext, type Page } from "@playwright/test";
import { screenshotPage } from "./helpers/screenshots";

const API_BASE = process.env.INTEGRATION_API_URL || "http://localhost:5173";
const DEFAULT_PASSWORD = "TestPass123!";

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

interface Player {
  username: string;
  email: string;
  password: string;
  accessToken: string;
  page: Page;
}

async function apiRegister(
  username: string,
  email: string,
  password: string,
  retries = 5,
): Promise<string> {
  for (let attempt = 0; attempt < retries; attempt++) {
    const res = await fetch(`${API_BASE}/api/v1/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, email, password }),
    });
    if (res.ok) {
      const body = await res.json();
      return body.data.tokens.access_token;
    }
    if (res.status === 429 && attempt < retries - 1) {
      const delay = 2000 * (attempt + 1);
      await new Promise((r) => setTimeout(r, delay));
      continue;
    }
    throw new Error(`Register failed (${res.status}): ${await res.text()}`);
  }
  throw new Error(`Register failed after ${retries} retries`);
}

async function setupPlayerPage(
  page: Page,
  accessToken: string,
): Promise<void> {
  await page.goto("/");
  await page.evaluate((token) => {
    localStorage.setItem("access_token", token);
    localStorage.setItem("refresh_token", "dummy-refresh");
    localStorage.setItem("auth_state", JSON.stringify({
      user: null,
      isAuthenticated: true,
      isLoading: false,
    }));
  }, accessToken);
  await page.goto("/dashboard");
  await page.waitForURL("**/dashboard", { timeout: 10_000 });
  // Wait for auth to settle — the page should show a logged-in element
  const logoutBtn = page.getByRole("button", { name: "Logout" });
  await logoutBtn.waitFor({ timeout: 10_000 });
  // If redirected to login, the setup failed
  if (page.url().includes("/login") || page.url().includes("/register")) {
    throw new Error(`Auth setup failed — redirected to ${page.url()}`);
  }
}

const RESULT_HEADINGS = ["Victory!", "Defeat", "Draw", "Challenge Abandoned"];

async function ss(page: Page, name: string) {
  await screenshotPage(page, name);
}

async function setupTwoPlayers(
  suffix: string,
  scenario: string,
  page: Page,
  browser: any,
): Promise<{ p1: Player; p2: Player; ctx2: BrowserContext }> {
  const u1 = `e2e_pvp_${suffix}_${scenario}_p1`;
  const u2 = `e2e_pvp_${suffix}_${scenario}_p2`;
  const e1 = `${u1}@test.com`;
  const e2 = `${u2}@test.com`;

  const [t1, t2] = await Promise.all([
    apiRegister(u1, e1, DEFAULT_PASSWORD),
    apiRegister(u2, e2, DEFAULT_PASSWORD),
  ]);

  await setupPlayerPage(page, t1);
  const p1: Player = { username: u1, email: e1, password: DEFAULT_PASSWORD, accessToken: t1, page };

  const ctx2 = await browser.newContext();
  const page2 = await ctx2.newPage();
  await setupPlayerPage(page2, t2);
  const p2: Player = { username: u2, email: e2, password: DEFAULT_PASSWORD, accessToken: t2, page: page2 };

  return { p1, p2, ctx2 };
}

async function matchAndStart(p1: Player, p2: Player, prefix: string) {
  // P1 joins queue first
  await p1.page.goto("/challenge");
  await p1.page.waitForLoadState("networkidle");
  await p1.page.getByRole("button", { name: "Find Opponent" }).click();

  // Wait for queuing or immediate match
  await Promise.race([
    p1.page.waitForSelector('text="Finding Opponent..."', { timeout: 10_000 }),
    p1.page.waitForSelector('text="Opponent Found!"', { timeout: 10_000 }),
  ]);
  await ss(p1.page, `${prefix}-queuing-p1`);

  // P2 joins → match
  await p2.page.goto("/challenge");
  await p2.page.waitForLoadState("networkidle");
  await p2.page.getByRole("button", { name: "Find Opponent" }).click();

  await Promise.all([
    p1.page.waitForSelector('text="Opponent Found!"', { timeout: 15_000 }),
    p2.page.waitForSelector('text="Opponent Found!"', { timeout: 15_000 }),
  ]);
  await ss(p1.page, `${prefix}-matched-p1`);
  await ss(p2.page, `${prefix}-matched-p2`);

  // Verify same session
  const url1 = p1.page.url();
  const url2 = p2.page.url();
  const sid1 = url1.match(/\/challenge\/([a-f0-9-]+)/i)?.[1] ?? "";
  const sid2 = url2.match(/\/challenge\/([a-f0-9-]+)/i)?.[1] ?? "";
  expect(sid1).toBeTruthy();
  expect(sid1).toBe(sid2);

  // Both start simultaneously
  await Promise.all([
    p1.page.getByRole("button", { name: "Start Challenge" }).click(),
    p2.page.getByRole("button", { name: "Start Challenge" }).click(),
  ]);

  // Wait for challenge to begin (problem may load async)
  await Promise.all([
    p1.page.waitForSelector('text="Challenge in progress"', { timeout: 20_000 }),
    p2.page.waitForSelector('text="Challenge in progress"', { timeout: 20_000 }),
  ]);
  await ss(p1.page, `${prefix}-in-progress-p1`);
  await ss(p2.page, `${prefix}-in-progress-p2`);
}

// ===========================================================================

test.describe("PvP Challenge Flow (E2E Integration)", () => {
  test.setTimeout(120_000);

  // S1–S4 are two-player scenarios and MUST run serially to avoid cross-match
  test.describe.serial("Two-player scenarios", () => {

  // ========================================================================
  // Scenario 1: Normal PvP — P1 wins
  // ========================================================================
  test("S1: Full normal flow — P1 wins", async ({ page, browser }) => {
    const suffix = Date.now();
    const { p1, p2, ctx2 } = await setupTwoPlayers(suffix, "s1", page, browser);

    try {
      await matchAndStart(p1, p2, "pvp-s1");

      // Wait for timer to advance
      await p1.page.waitForTimeout(2000);

      // P1: Yes → Submit
      await p1.page.getByRole("button", { name: "Yes" }).click();
      await p1.page.waitForTimeout(500);
      await p1.page.getByRole("button", { name: "Submit Result" }).click();

      // P2: No → Submit
      await p2.page.waitForTimeout(1000);
      await p2.page.getByRole("button", { name: "No" }).click();
      await p2.page.waitForTimeout(500);
      await p2.page.getByRole("button", { name: "Submit Result" }).click();

      // Wait for results
      await Promise.all([
        Promise.race(RESULT_HEADINGS.map((h) =>
          p1.page.waitForSelector(`text="${h}"`, { timeout: 25_000 }))),
        Promise.race(RESULT_HEADINGS.map((h) =>
          p2.page.waitForSelector(`text="${h}"`, { timeout: 25_000 }))),
      ]);
      await ss(p1.page, "pvp-s1-result-p1");
      await ss(p2.page, "pvp-s1-result-p2");

      await expect(p1.page.getByText("Victory!").first()).toBeVisible();
      await expect(p2.page.getByText("Defeat").first()).toBeVisible();

      // New Challenge
      await p1.page.getByRole("button", { name: "New Challenge" }).click();
      await p2.page.getByRole("button", { name: "New Challenge" }).click();
      await Promise.all([
        p1.page.waitForSelector('text="Find Opponent"', { timeout: 5_000 }),
        p2.page.waitForSelector('text="Find Opponent"', { timeout: 5_000 }),
      ]);
    } finally {
      await ctx2.close();
    }
  });

  // ========================================================================
  // Scenario 2: Draw — both unsolved
  // ========================================================================
  test("S2: Both unsolved → Draw", async ({ page, browser }) => {
    const suffix = Date.now();
    const { p1, p2, ctx2 } = await setupTwoPlayers(suffix, "s2", page, browser);

    try {
      await matchAndStart(p1, p2, "pvp-s2");

      await p1.page.waitForTimeout(2000);

      // Both: No → Submit
      for (const p of [p1, p2]) {
        await p.page.getByRole("button", { name: "No" }).click();
        await p.page.waitForTimeout(500);
        await p.page.getByRole("button", { name: "Submit Result" }).click();
      }

      await Promise.all([
        p1.page.waitForSelector('text="Draw"', { timeout: 25_000 }),
        p2.page.waitForSelector('text="Draw"', { timeout: 25_000 }),
      ]);
      await ss(p1.page, "pvp-s2-result-p1");
      await ss(p2.page, "pvp-s2-result-p2");

      await expect(p1.page.getByText("Draw").first()).toBeVisible();
      await expect(p2.page.getByText("Draw").first()).toBeVisible();
    } finally {
      await ctx2.close();
    }
  });

  // ========================================================================
  // Scenario 3: Quit penalty
  // ========================================================================
  test("S3: P1 quits → P2 auto-detects Victory via polling", async ({ page, browser }) => {
    const suffix = Date.now();
    const { p1, p2, ctx2 } = await setupTwoPlayers(suffix, "s3", page, browser);

    try {
      await matchAndStart(p1, p2, "pvp-s3");

      // P1 quits
      await p1.page.getByRole("button", { name: "Quit" }).click();
      await p1.page.waitForSelector('text="Challenge Abandoned"', { timeout: 10_000 });
      await ss(p1.page, "pvp-s3-quit-p1");

      // P2 should auto-detect opponent quit via in_progress polling (no reload needed)
      const p2Result = await Promise.race(
        RESULT_HEADINGS.map((h) =>
          p2.page.waitForSelector(`text="${h}"`, { timeout: 20_000 })
            .then(() => h)),
      );
      await ss(p2.page, "pvp-s3-result-p2");
      expect(p2Result).toBe("Victory!");
    } finally {
      await ctx2.close();
    }
  });

  // ========================================================================
  // Scenario 4: Resume active challenge
  // ========================================================================
  test("S4: P1 leaves and resumes challenge", async ({ page, browser }) => {
    const suffix = Date.now();
    const { p1, p2, ctx2 } = await setupTwoPlayers(suffix, "s4", page, browser);

    try {
      await matchAndStart(p1, p2, "pvp-s4");

      // P1 navigates away
      await p1.page.goto("/dashboard");
      await p1.page.waitForLoadState("networkidle");

      // P1 resumes
      await p1.page.goto("/challenge");
      await p1.page.waitForLoadState("networkidle");
      await p1.page.waitForSelector('text="Challenge in progress"', { timeout: 10_000 });
      await ss(p1.page, "pvp-s4-p1-resumed");

      // Complete after resume: P1 solved, P2 unsolved
      await p1.page.getByRole("button", { name: "Yes" }).click();
      await p1.page.waitForTimeout(500);
      await p1.page.getByRole("button", { name: "Submit Result" }).click();

      await p2.page.getByRole("button", { name: "No" }).click();
      await p2.page.waitForTimeout(500);
      await p2.page.getByRole("button", { name: "Submit Result" }).click();

      await Promise.all([
        p1.page.waitForSelector('text="Victory!"', { timeout: 25_000 }),
        p2.page.waitForSelector('text="Defeat"', { timeout: 25_000 }),
      ]);
      await ss(p1.page, "pvp-s4-result-p1");
      await ss(p2.page, "pvp-s4-result-p2");
    } finally {
      await ctx2.close();
    }
  });

  }); // end serial describe

  // ========================================================================
  // Scenario 5: Edge cases
  // ========================================================================
  test("S5a: Re-visit /challenge while in queue", async ({ page }) => {
    const suffix = Date.now();
    const u = `e2e_pvp_${suffix}_s5a`;
    const e = `${u}@test.com`;
    const t = await apiRegister(u, e, DEFAULT_PASSWORD);
    await setupPlayerPage(page, t);

    await page.goto("/challenge");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Find Opponent" }).click();

    // Wait for queuing — if matched, test is not meaningful
    const queuing = await Promise.race([
      page.waitForSelector('text="Finding Opponent..."', { timeout: 10_000 })
        .then(() => true),
      page.waitForSelector('text="Opponent Found!"', { timeout: 10_000 })
        .then(() => false),
    ]);

    if (!queuing) {
      // Got matched unexpectedly — can't test queue revisit
      test.skip();
    }

    // Navigate away and back
    await page.goto("/dashboard");
    await page.waitForLoadState("networkidle");
    await page.goto("/challenge");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3000);

    const bodyText = await page.locator("body").textContent();
    expect(bodyText).toBeTruthy();

    // Clean up — try cancel if visible
    const cancelBtn = page.getByRole("button", { name: "Cancel" });
    if (await cancelBtn.isVisible()) {
      await cancelBtn.click();
    }
  });

  test("S5b: Leave queue before match", async ({ page }) => {
    const suffix = Date.now();
    const u = `e2e_pvp_${suffix}_s5b`;
    const e = `${u}@test.com`;
    const t = await apiRegister(u, e, DEFAULT_PASSWORD);
    await setupPlayerPage(page, t);

    await page.goto("/challenge");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Find Opponent" }).click();

    // Must be in queuing state for this test
    const queuing = await Promise.race([
      page.waitForSelector('text="Finding Opponent..."', { timeout: 10_000 })
        .then(() => true),
      page.waitForSelector('text="Opponent Found!"', { timeout: 10_000 })
        .then(() => false),
    ]);

    if (!queuing) {
      test.skip();
    }
    await ss(page, "pvp-s5b-queuing");

    await page.getByRole("button", { name: "Cancel" }).click();
    await page.waitForSelector('text="Find Opponent"', { timeout: 5_000 });
    await ss(page, "pvp-s5b-back-to-idle");

    await expect(page.getByRole("button", { name: "Find Opponent" })).toBeVisible();
  });

  test("S5c: Single player in queue — UI state", async ({ page }) => {
    const suffix = Date.now();
    const u = `e2e_pvp_${suffix}_s5c`;
    const e = `${u}@test.com`;
    const t = await apiRegister(u, e, DEFAULT_PASSWORD);
    await setupPlayerPage(page, t);

    await page.goto("/challenge");
    await page.waitForLoadState("networkidle");
    await page.getByRole("button", { name: "Find Opponent" }).click();

    const queuing = await Promise.race([
      page.waitForSelector('text="Finding Opponent..."', { timeout: 10_000 })
        .then(() => true),
      page.waitForSelector('text="Opponent Found!"', { timeout: 10_000 })
        .then(() => false),
    ]);

    if (!queuing) {
      test.skip();
    }
    await ss(page, "pvp-s5c-queuing");

    await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();

    // Clean up
    await page.getByRole("button", { name: "Cancel" }).click();
  });
});
