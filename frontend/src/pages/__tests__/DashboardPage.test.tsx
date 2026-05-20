import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

const baseUser = {
  id: "u1",
  username: "testuser",
  email: "test@example.com",
  cf_handle: null,
  cf_handle_verified: false,
  elo: 1200,
  pp: 50,
  tokens: 100,
  is_active: true,
  is_admin: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: null,
  last_login_at: null,
};

let mockUser = { ...baseUser };
const mockFetchUser = vi.fn().mockImplementation(async () => {
  // Simulate successful fetchUser
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({
    user: mockUser,
    isAuthenticated: true,
    isLoading: false,
    fetchUser: mockFetchUser,
  })),
}));

vi.mock("@/components/charts/DashboardCharts", () => ({
  DashboardCharts: () => <div data-testid="dashboard-charts">Charts</div>,
}));

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import DashboardPage from "../DashboardPage";

function renderPage(initialPath = "/dashboard") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <DashboardPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUser = { ...baseUser };
    server.resetHandlers();
  });

  // 1. Loading state — when user is null
  it("shows loading spinner when user is null", async () => {
    mockUser = null as unknown as typeof baseUser;

    server.use(
      http.get("*/api/v1/economy/transactions*", () =>
        HttpResponse.json({ success: true, data: { items: [] }, message: "ok" }),
      ),
    );

    renderPage();
    expect(screen.getByText("dashboard:loadingDashboard")).toBeInTheDocument();
  });

  // 2. Empty state — no transactions, no active contest/challenge
  it("shows empty activity message when no transactions exist", async () => {
    server.use(
      http.get("*/api/v1/economy/transactions*", () =>
        HttpResponse.json({ success: true, data: { items: [] }, message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("dashboard:welcomeBack")).toBeInTheDocument();
    });
    expect(screen.getByText("dashboard:noRecentActivity")).toBeInTheDocument();
    // No active contest banner
    expect(screen.queryByText("dashboard:activeContest")).not.toBeInTheDocument();
    // No active challenge banner
    expect(screen.queryByText("dashboard:activeChallenge")).not.toBeInTheDocument();
  });

  // 3. Error state — API returns error (gracefully handled)
  it("renders dashboard even when API calls fail", async () => {
    server.use(
      http.get("*/api/v1/economy/transactions*", () =>
        HttpResponse.json({ success: false, error: { code: "ERR", message: "Server error" } }, { status: 500 }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: false, error: { code: "ERR", message: "Server error" } }, { status: 500 }),
      ),
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: false, error: { code: "ERR", message: "Server error" } }, { status: 500 }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("dashboard:welcomeBack")).toBeInTheDocument();
    });
    // Should still render the page with user info, not crash
    expect(screen.getByText("dashboard:eloRating")).toBeInTheDocument();
    expect(screen.getByText("dashboard:performancePoints")).toBeInTheDocument();
    expect(screen.getByText("common:tokens")).toBeInTheDocument();
  });

  // 4. Normal data — typical user data renders correctly
  it("renders user stats and transactions with normal data", async () => {
    server.use(
      http.get("*/api/v1/economy/transactions*", () =>
        HttpResponse.json({
          success: true,
          data: {
            items: [
              { id: "tx1", amount: 10, type: "challenge_reward", reference_type: null, reference_id: null, balance_after: 110, created_at: "2025-06-01T10:00:00Z" },
              { id: "tx2", amount: -3, type: "hint_purchase", reference_type: null, reference_id: null, balance_after: 107, created_at: "2025-06-01T09:00:00Z" },
            ],
          },
          message: "ok",
        }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({
          success: true,
          data: { id: "c1", tier: "beginner", problems: [], total_problems: 4, problems_solved: 2, submissions: 3, time_limit_minutes: 90, started_at: "2025-06-01T08:00:00Z", ended_at: null, remaining_seconds: 3600, end_time: null, status: "active", elo_change: null },
          message: "ok",
        }),
      ),
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({
          success: true,
          data: { id: "ch1", problem_id: "p1", problem_name: "Two Sum", problem_rating: 1200, created_at: "2025-06-01T07:00:00Z", is_challenger: true, opponent_username: "opponent1", opponent_elo: 1300, status: "active" },
          message: "ok",
        }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("dashboard:activeContest")).toBeInTheDocument();
    });
    expect(screen.getByText("dashboard:activeChallenge")).toBeInTheDocument();
    // Transaction amounts
    expect(screen.getByText("+10")).toBeInTheDocument();
    expect(screen.getByText("-3")).toBeInTheDocument();
  });

  // 5. Boundary data — Elo=0, tokens=0
  it("renders correctly with Elo=0 and zero tokens", async () => {
    mockUser = { ...baseUser, elo: 0, tokens: 0, pp: 0 };

    server.use(
      http.get("*/api/v1/economy/transactions*", () =>
        HttpResponse.json({ success: true, data: { items: [] }, message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("dashboard:welcomeBack")).toBeInTheDocument();
    });
    // Verify zero Elo renders — locate by the parent card context
    const eloCard = screen.getByText("dashboard:eloRating").closest(".rounded-xl");
    expect(eloCard).toBeTruthy();
    expect(within(eloCard as HTMLElement).getByText("0")).toBeInTheDocument();
  });

  // 6. Boundary data — Elo=9999 (extreme high)
  it("renders correctly with Elo=9999 (extreme high)", async () => {
    mockUser = { ...baseUser, elo: 9999 };

    server.use(
      http.get("*/api/v1/economy/transactions*", () =>
        HttpResponse.json({ success: true, data: { items: [] }, message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("dashboard:welcomeBack")).toBeInTheDocument();
    });
    // 9999 should render somewhere in the Elo card
    const eloCard = screen.getByText("dashboard:eloRating").closest(".rounded-xl");
    expect(within(eloCard as HTMLElement).getByText("9999")).toBeInTheDocument();
  });

  // 7. CF handle prompt
  it("shows CF handle prompt when user has no linked CF handle", async () => {
    // mockUser already has cf_handle: null
    server.use(
      http.get("*/api/v1/economy/transactions*", () =>
        HttpResponse.json({ success: true, data: { items: [] }, message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("dashboard:linkCF")).toBeInTheDocument();
    });
  });
});
