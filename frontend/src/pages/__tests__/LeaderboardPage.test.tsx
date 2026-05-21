import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      if (params) {
        return Object.entries(params).reduce(
          (acc, [k, v]) => acc.replace(`{{${k}}}`, String(v)),
          key,
        );
      }
      return key;
    },
    i18n: { language: "en" },
  }),
}));

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
}));

vi.mock("@/components/medal", () => ({
  MedalBadge: () => <div data-testid="medal-badge" />,
}));

vi.mock("@/components/Avatar", () => ({
  Avatar: () => <div data-testid="avatar" />,
}));

vi.mock("@/utils", () => ({
  getRatingColor: () => "#000000",
  getDifficultyLabelKey: (elo: number) => "rating.newbie",
  ratingToMedal: () => ({ level: "bronze", type: "arena" }),
}));

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const server = setupServer();

const sampleUsers = [
  { id: "u1", username: "alice", email: "a@b.com", cf_handle: "cf_alice", elo: 2000, pp: 100, tokens: 50, is_active: true, is_admin: false, created_at: "2025-01-01" },
  { id: "u2", username: "bob", email: "b@b.com", cf_handle: null, elo: 1500, pp: 80, tokens: 30, is_active: true, is_admin: false, created_at: "2025-02-01" },
  { id: "u3", username: "charlie", email: "c@b.com", cf_handle: "cf_charlie", elo: 1800, pp: 120, tokens: 70, is_active: true, is_admin: false, created_at: "2025-03-01" },
];

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import LeaderboardPage from "../LeaderboardPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <LeaderboardPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LeaderboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.resetHandlers();
  });

  // 1. Loading state
  it("shows loading spinner initially", () => {
    server.use(
      http.get("*/api/v1/auth/leaderboard", async () => {
        await new Promise(() => {});
      }),
    );
    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  // 2. Renders title and sort tabs
  it("renders title, description, and sort tabs", () => {
    server.use(
      http.get("*/api/v1/auth/leaderboard", () =>
        HttpResponse.json({ success: true, data: sampleUsers, message: "ok" }),
      ),
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "medal" }, message: "ok" }),
      ),
    );
    renderPage();
    expect(screen.getByText("leaderboard")).toBeInTheDocument();
    expect(screen.getByText("leaderboardDesc")).toBeInTheDocument();
    expect(screen.getByText("byElo")).toBeInTheDocument();
    expect(screen.getByText("byPP")).toBeInTheDocument();
  });

  // 3. Renders users sorted by Elo by default
  it("renders users sorted by Elo by default", async () => {
    server.use(
      http.get("*/api/v1/auth/leaderboard", () =>
        HttpResponse.json({ success: true, data: sampleUsers, message: "ok" }),
      ),
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "medal" }, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("alice")).toBeInTheDocument();
    });
    expect(screen.getByText("bob")).toBeInTheDocument();
    expect(screen.getByText("charlie")).toBeInTheDocument();

    // Check header row
    expect(screen.getByText("player")).toBeInTheDocument();
    expect(screen.getByText("elo")).toBeInTheDocument();
  });

  // 4. Sort by PP
  it("sorts by PP when PP tab is clicked", async () => {
    server.use(
      http.get("*/api/v1/auth/leaderboard", () =>
        HttpResponse.json({ success: true, data: sampleUsers, message: "ok" }),
      ),
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "medal" }, message: "ok" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("alice")).toBeInTheDocument();
    });

    await user.click(screen.getByText("byPP"));

    // charlie has highest PP (120), should be first
    const allNames = screen.getAllByText(/alice|bob|charlie/);
    expect(allNames[0]).toHaveTextContent("charlie");
  });

  // 5. Empty state
  it("shows empty state when no users", async () => {
    server.use(
      http.get("*/api/v1/auth/leaderboard", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("noData")).toBeInTheDocument();
    });
  });

  // 6. API error falls back to empty
  it("shows empty state on API error", async () => {
    server.use(
      http.get("*/api/v1/auth/leaderboard", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("noData")).toBeInTheDocument();
    });
  });

  // 7. CF handle display
  it("shows CF handle for users who have one", async () => {
    server.use(
      http.get("*/api/v1/auth/leaderboard", () =>
        HttpResponse.json({ success: true, data: sampleUsers, message: "ok" }),
      ),
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "medal" }, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("alice")).toBeInTheDocument();
    });

    // alice and charlie both have CF handles - rendered as cfHandle text
    const cfHandleTexts = screen.getAllByText("cfHandle");
    expect(cfHandleTexts.length).toBe(2);
  });

  // 8. cf_tier display mode
  it("renders with cf_tier display mode", async () => {
    server.use(
      http.get("*/api/v1/auth/leaderboard", () =>
        HttpResponse.json({ success: true, data: sampleUsers, message: "ok" }),
      ),
      http.get("*/api/v1/auth/settings", () =>
        HttpResponse.json({ success: true, data: { display_mode: "cf_tier" }, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("alice")).toBeInTheDocument();
    });
    // In cf_tier mode, the ratingToMedal is not used, instead difficulty labels are shown
    // All users have getDifficultyLabelKey mock returning "rating.newbie"
    // The Elo column should NOT show medal badges
    expect(screen.queryByTestId("medal-badge")).not.toBeInTheDocument();
  });
});
