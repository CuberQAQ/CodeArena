import { expect, type Page } from "@playwright/test";
import { screenshotPage } from "./screenshots";

const DEFAULT_PASSWORD = "TestPass123!";

// ---------------------------------------------------------------------------
// API helpers — register/login via HTTP to avoid needing browser.newContext()
// ---------------------------------------------------------------------------

export interface Player {
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
): Promise<{ accessToken: string }> {
  const res = await fetch("http://localhost:8000/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, email, password }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Register failed (${res.status}): ${text}`);
  }
  const body = await res.json();
  return { accessToken: body.data.tokens.access_token };
}

async function apiLogin(
  email: string,
  password: string,
): Promise<{ accessToken: string }> {
  const res = await fetch("http://localhost:8000/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Login failed (${res.status}): ${text}`);
  }
  const body = await res.json();
  return { accessToken: body.data.tokens.access_token };
}

// ---------------------------------------------------------------------------
// Registration & Login (via API + page)
// ---------------------------------------------------------------------------

/**
 * Register a user via API, then inject the access token into localStorage
 * so the page is "logged in" when navigated.
 */
export async function registerAndSetup(
  page: Page,
  suffix: string,
  index: number,
): Promise<Player> {
  const username = `e2e_pvp_${suffix}_p${index}`;
  const email = `e2e_pvp_${suffix}_p${index}@test.com`;
  const password = DEFAULT_PASSWORD;

  const { accessToken } = await apiRegister(username, email, password);

  // Navigate to the app and inject token into localStorage
  await page.goto("/");
  await page.evaluate((token) => {
    localStorage.setItem("access_token", token);
    localStorage.setItem("refresh_token", "dummy");
    localStorage.setItem("auth_state", JSON.stringify({
      user: null,
      isAuthenticated: true,
      isLoading: false,
    }));
  }, accessToken);

  // Navigate to dashboard — the auth store will fetch user from API
  await page.goto("/dashboard");
  await page.waitForURL("**/dashboard", { timeout: 10_000 });
  await page.waitForLoadState("networkidle");

  return { username, email, password, accessToken, page };
}

/**
 * Login via API, then inject the access token into localStorage.
 */
export async function loginAndSetup(
  page: Page,
  email: string,
  password: string,
): Promise<Player> {
  const { accessToken } = await apiLogin(email, password);

  await page.goto("/");
  await page.evaluate((token) => {
    localStorage.setItem("access_token", token);
    localStorage.setItem("refresh_token", "dummy");
    localStorage.setItem("auth_state", JSON.stringify({
      user: null,
      isAuthenticated: true,
      isLoading: false,
    }));
  }, accessToken);

  await page.goto("/dashboard");
  await page.waitForURL("**/dashboard", { timeout: 10_000 });

  const username = "recovered_user"; // Will be fetched from API
  return { username, email, password, accessToken, page };
}

// ---------------------------------------------------------------------------
// Queue & Match
// ---------------------------------------------------------------------------

export async function joinQueue(
  player: Player,
  prefix: string,
  idx: number,
): Promise<void> {
  await player.page.goto("/challenge");
  await player.page.waitForLoadState("networkidle");
  await screenshotPage(player.page, `pvp-${prefix}-idle-p${idx}`);

  await player.page.click('button:has-text("Find Opponent")');
  await player.page.waitForSelector('text="Finding Opponent..."', { timeout: 10_000 });
  await screenshotPage(player.page, `pvp-${prefix}-queuing-p${idx}`);
}

export async function waitForMatch(
  player: Player,
  prefix: string,
  idx: number,
  timeout = 15_000,
): Promise<string> {
  await player.page.waitForSelector('text="Opponent Found!"', { timeout });
  await screenshotPage(player.page, `pvp-${prefix}-matched-p${idx}`);

  const url = player.page.url();
  const match = url.match(/\/challenge\/([a-f0-9-]+)/i);
  return match ? match[1] : "";
}

// ---------------------------------------------------------------------------
// Challenge Start
// ---------------------------------------------------------------------------

export async function startChallenge(
  player: Player,
  prefix: string,
  idx: number,
): Promise<void> {
  await player.page.click('button:has-text("Start Challenge")');
  await player.page.waitForSelector('text="Open on Codeforces"', { timeout: 15_000 });
  await screenshotPage(player.page, `pvp-${prefix}-in-progress-p${idx}`);
}

// ---------------------------------------------------------------------------
// Submit Result
// ---------------------------------------------------------------------------

export async function submitResult(
  player: Player,
  solved: boolean,
  prefix: string,
  idx: number,
): Promise<void> {
  await player.page.waitForTimeout(2000);

  const choice = solved ? "Yes" : "No";
  await player.page.click(`button:has-text("${choice}")`);
  await player.page.waitForTimeout(500);
  await screenshotPage(player.page, `pvp-${prefix}-submit-choice-p${idx}`);

  await player.page.click('button:has-text("Submit Result")');
  await screenshotPage(player.page, `pvp-${prefix}-submitted-p${idx}`);
}

// ---------------------------------------------------------------------------
// Wait for & Verify Result
// ---------------------------------------------------------------------------

const RESULT_HEADINGS = ["Victory!", "Defeat", "Draw", "Challenge Abandoned"];
const RESULT_MAP: Record<string, string> = {
  win: "Victory!",
  loss: "Defeat",
  draw: "Draw",
  quit: "Challenge Abandoned",
};

export async function waitForResult(
  player: Player,
  prefix: string,
  idx: number,
  timeout = 20_000,
): Promise<void> {
  await Promise.race(
    RESULT_HEADINGS.map((h) =>
      player.page.waitForSelector(`text="${h}"`, { timeout }),
    ),
  );
  await screenshotPage(player.page, `pvp-${prefix}-result-p${idx}`);
}

export async function verifyResult(
  player: Player,
  expected: "win" | "loss" | "draw" | "quit",
  prefix: string,
  idx: number,
): Promise<void> {
  const heading = RESULT_MAP[expected];
  await expect(player.page.getByText(heading).first()).toBeVisible();

  if (expected === "win") {
    const eloTexts = player.page.locator("text=/\\+\\d+.*Elo|Elo.*\\+\\d+|\\+\\d+/");
    await expect(eloTexts.first()).toBeVisible({ timeout: 5_000 });
  }

  await screenshotPage(player.page, `pvp-${prefix}-verified-p${idx}`);
}

// ---------------------------------------------------------------------------
// Quit Challenge
// ---------------------------------------------------------------------------

export async function quitChallenge(
  player: Player,
  prefix: string,
  idx: number,
): Promise<void> {
  await player.page.click('button:has-text("Quit")');
  await player.page.waitForSelector('text="Challenge Abandoned"', { timeout: 10_000 });
  await screenshotPage(player.page, `pvp-${prefix}-quit-p${idx}`);
}

// ---------------------------------------------------------------------------
// Navigation & Resume
// ---------------------------------------------------------------------------

export async function navigateAway(player: Player): Promise<void> {
  await player.page.goto("/dashboard");
  await player.page.waitForLoadState("networkidle");
}

export async function resumeChallenge(
  player: Player,
  prefix: string,
  idx: number,
): Promise<void> {
  await player.page.goto("/challenge");
  await player.page.waitForLoadState("networkidle");
  await player.page.waitForSelector('text="Challenge in progress"', { timeout: 10_000 });
  await screenshotPage(player.page, `pvp-${prefix}-resumed-p${idx}`);
}

// ---------------------------------------------------------------------------
// Queue Leave
// ---------------------------------------------------------------------------

export async function leaveQueue(
  player: Player,
  prefix: string,
  idx: number,
): Promise<void> {
  await player.page.click('button:has-text("Cancel")');
  await player.page.waitForSelector('text="Find Opponent"', { timeout: 5_000 });
  await screenshotPage(player.page, `pvp-${prefix}-left-queue-p${idx}`);
}

// ---------------------------------------------------------------------------
// New Challenge
// ---------------------------------------------------------------------------

export async function newChallenge(
  player: Player,
  prefix: string,
  idx: number,
): Promise<void> {
  await player.page.click('button:has-text("New Challenge")');
  await player.page.waitForSelector('text="Find Opponent"', { timeout: 5_000 });
  await screenshotPage(player.page, `pvp-${prefix}-new-challenge-p${idx}`);
}
