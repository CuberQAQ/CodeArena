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
      if (typeof key === "string" && params) {
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

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({
    user: { id: "u1", username: "testuser", elo: 1500, tokens: 100 },
    isAuthenticated: true,
    isLoading: false,
    fetchUser: vi.fn().mockResolvedValue(undefined),
  })),
}));

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
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

import ContestPage from "../ContestPage";

function renderPage(initialPath = "/contest") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <ContestPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const fiveTiers = [
  { tier: "beginner", name: "Beginner Contest", div: 4, min_elo: null, max_elo: 1399, duration_minutes: 120, problem_count: 7, rating_range: [800, 1400], eligible: true, is_rated: true },
  { tier: "pupil", name: "Pupil Contest", div: 3, min_elo: null, max_elo: 1599, duration_minutes: 120, problem_count: 7, rating_range: [800, 1600], eligible: true, is_rated: true },
  { tier: "advanced", name: "Advanced Contest", div: 2, min_elo: null, max_elo: 2099, duration_minutes: 120, problem_count: 6, rating_range: [1200, 2200], eligible: true, is_rated: true },
  { tier: "master", name: "Master Contest", div: 1, min_elo: 1900, max_elo: null, duration_minutes: 120, problem_count: 6, rating_range: [1600, 3000], eligible: false, is_rated: false },
  { tier: "blitz", name: "Blitz Contest", div: null, min_elo: null, max_elo: null, duration_minutes: 60, problem_count: 4, rating_range: null, eligible: true, is_rated: true },
];

const typicalHistory = [
  { id: "contest1", tier: "beginner", total_problems: 4, problems_solved: 3, submissions: 5, time_limit_minutes: 90, started_at: "2025-06-01T08:00:00Z", ended_at: "2025-06-01T09:30:00Z", status: "completed", elo_change: 12 },
  { id: "contest2", tier: "advanced", total_problems: 5, problems_solved: 2, submissions: 4, time_limit_minutes: 120, started_at: "2025-05-30T10:00:00Z", ended_at: "2025-05-30T12:00:00Z", status: "completed", elo_change: -8 },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ContestPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.resetHandlers();
  });

  // 1. Loading state
  it("shows loading spinner initially", () => {
    server.use(
      http.get("*/api/v1/contest/tiers", async () => {
        await new Promise(() => {}); // Never resolves
      }),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
    expect(screen.getByText("loadingContests")).toBeInTheDocument();
  });

  // 2. Empty state -- no tiers, no history
  it("shows empty tier message when no tiers available", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("noTiers")).toBeInTheDocument();
    });
    // No history section
    expect(screen.queryByText("recentContests")).not.toBeInTheDocument();
  });

  // 3. Error state -- API returns errors (graceful fallback)
  it("renders page with empty tiers when API errors occur", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: false, error: { code: "ERR", message: "Server error" } }, { status: 500 }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: false, error: { code: "ERR", message: "Server error" } }, { status: 500 }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: false, error: { code: "ERR", message: "Server error" } }, { status: 500 }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("virtualContest")).toBeInTheDocument();
    });
    // Falls back to empty data gracefully
    expect(screen.getByText("noTiers")).toBeInTheDocument();
  });

  // 4. Normal data -- all 5 tiers and history render correctly
  it("renders all 5 tier cards and contest history with normal data", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: typicalHistory, message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Beginner Contest")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(screen.getByText("Pupil Contest")).toBeInTheDocument();
    expect(screen.getByText("Advanced Contest")).toBeInTheDocument();
    expect(screen.getByText("Master Contest")).toBeInTheDocument();
    expect(screen.getByText("Blitz Contest")).toBeInTheDocument();
    // History section
    await waitFor(() => {
      expect(screen.getByText("recentContests")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(screen.getByText(/\+12/)).toBeInTheDocument();
    expect(screen.getByText(/-8/)).toBeInTheDocument();
  });

  // 5. Div badges display correctly for tiers with div numbers
  it("renders Div badges for tiers with div numbers", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Beginner Contest")).toBeInTheDocument();
    });
    // The mock t() returns the key "divLabel" since the template string
    // "divLabel" does not contain {{div}}, so it stays as-is.
    // 4 tiers have div numbers (beginner=4, pupil=3, advanced=2, master=1)
    // blitz has div=null so no badge
    const divBadges = screen.getAllByText("divLabel");
    expect(divBadges.length).toBe(4);
  });

  // 6. Rated/Unrated badges display correctly
  it("renders rated and unrated badges", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Beginner Contest")).toBeInTheDocument();
    });
    // Most tiers are rated (is_rated=true), master is unrated for this user
    const ratedBadges = screen.getAllByText("rated");
    expect(ratedBadges.length).toBeGreaterThanOrEqual(3); // beginner, pupil, advanced, blitz
    expect(screen.getByText("unrated")).toBeInTheDocument(); // master is unrated
  });

  // 7. Blitz card shows special styling and dynamic rating range
  it("shows allRatings for blitz tier with null rating_range", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Blitz Contest")).toBeInTheDocument();
    });
    // Blitz card should show "allRatings" instead of a numeric range
    expect(screen.getByText("allRatings")).toBeInTheDocument();
    // Blitz card should show blitzDescription
    expect(screen.getByText("blitzDescription")).toBeInTheDocument();
    // Blitz card shows 60 min duration and 4 problems
    expect(screen.getByText("60 min")).toBeInTheDocument();
  });

  // 8. Ineligible tier shows Elo required button
  it("shows ineligible message for non-eligible tiers", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Master Contest")).toBeInTheDocument();
    });
    expect(screen.getByText("eloRequired")).toBeInTheDocument();
  });

  // 9. Active contest banner disables all start buttons
  it("shows active contest banner and disables start buttons", async () => {
    const activeContest = {
      id: "ac1",
      tier: "beginner",
      problems: [],
      total_problems: 7,
      problems_solved: 1,
      submissions: 2,
      time_limit_minutes: 120,
      started_at: "2025-06-01T08:00:00Z",
      ended_at: null,
      remaining_seconds: 3600,
      end_time: null,
      status: "active",
      elo_change: null,
    };

    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("activeContestRunning")).toBeInTheDocument();
    });
    // All 5 start buttons should show activeContestBtn text
    const activeBtns = screen.getAllByText("activeContestBtn");
    expect(activeBtns.length).toBe(5);
  });

  // 10. Error when starting contest
  it("shows error when contest start fails", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.post("*/api/v1/contest/start", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR", message: "Cannot start contest" } },
          { status: 400 },
        ),
      ),
    );

    renderPage();
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("Beginner Contest")).toBeInTheDocument();
    });
    // Click the eligible tier's start button
    const startButtons = screen.getAllByText("startContest");
    await user.click(startButtons[0]);
    await waitFor(() => {
      expect(screen.getByText("Cannot start contest")).toBeInTheDocument();
    });
  });

  // 11. Successful contest start navigates to contest page
  it("navigates to contest page on successful start", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.post("*/api/v1/contest/start", () =>
        HttpResponse.json({
          success: true,
          data: { id: "new-contest-123" },
          message: "ok",
        }),
      ),
    );

    renderPage();
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("Beginner Contest")).toBeInTheDocument();
    });

    const startButtons = screen.getAllByText("startContest");
    await user.click(startButtons[0]);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/contest/new-contest-123");
    });
  });

  // 12. Resume active contest navigates to contest page
  it("navigates to active contest on resume click", async () => {
    const activeContest = {
      id: "active-123",
      tier: "beginner",
      problems: [],
      total_problems: 7,
      problems_solved: 1,
      submissions: 2,
      time_limit_minutes: 120,
      started_at: "2025-06-01T08:00:00Z",
      ended_at: null,
      remaining_seconds: 3600,
      end_time: null,
      status: "active",
      elo_change: null,
    };

    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
      ),
    );

    renderPage();
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("resumeContest")).toBeInTheDocument();
    });

    await user.click(screen.getByText("resumeContest"));
    expect(mockNavigate).toHaveBeenCalledWith("/contest/active-123");
  });

  // 13. History item click navigates to contest detail
  it("navigates to contest detail on history item click", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: typicalHistory, message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("recentContests")).toBeInTheDocument();
    });

    await user.click(screen.getByText(/3\/4/));
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/contest/contest1");
    });
  });

  // 14. Starting state shows spinner
  it("shows loading spinner while contest is starting", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.post("*/api/v1/contest/start", async () => {
        await new Promise(() => {}); // Never resolves
      }),
    );

    renderPage();
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("Beginner Contest")).toBeInTheDocument();
    });

    const startButtons = screen.getAllByText("startContest");
    await user.click(startButtons[0]);

    await waitFor(() => {
      expect(screen.getByText("starting")).toBeInTheDocument();
    });
  });

  // 15. Starting a blitz contest works correctly
  it("can start a blitz contest successfully", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.post("*/api/v1/contest/start", () =>
        HttpResponse.json({
          success: true,
          data: { id: "blitz-contest-456" },
          message: "ok",
        }),
      ),
    );

    renderPage();
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("Blitz Contest")).toBeInTheDocument();
    });

    // Find the start button within the blitz card (4th eligible button)
    const startButtons = screen.getAllByText("startContest");
    // blitz is the 4th eligible tier (after beginner, pupil, advanced)
    await user.click(startButtons[3]);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/contest/blitz-contest-456");
    });
  });

  // 16. Rating range displays correctly for tiers with numeric ranges
  it("renders numeric rating ranges correctly", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: fiveTiers, message: "ok" }),
      ),
      http.get("*/api/v1/contest/history*", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/contest/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Beginner Contest")).toBeInTheDocument();
    });
    // Numeric ranges
    expect(screen.getByText("800 - 1400")).toBeInTheDocument();
    expect(screen.getByText("800 - 1600")).toBeInTheDocument();
    expect(screen.getByText("1200 - 2200")).toBeInTheDocument();
    expect(screen.getByText("1600 - 3000")).toBeInTheDocument();
    // Blitz shows "allRatings" not a numeric range
    expect(screen.getByText("allRatings")).toBeInTheDocument();
  });
});
