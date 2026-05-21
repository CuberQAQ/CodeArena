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

const typicalTiers = [
  { tier: "beginner", name: "Beginner", min_elo: null, max_elo: 1400, duration_minutes: 90, problem_count: 4, rating_range: [800, 1400], eligible: true },
  { tier: "advanced", name: "Advanced", min_elo: 1400, max_elo: 1800, duration_minutes: 120, problem_count: 5, rating_range: [1200, 2000], eligible: true },
  { tier: "master", name: "Master", min_elo: 1800, max_elo: null, duration_minutes: 150, problem_count: 6, rating_range: [1600, 2600], eligible: false },
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

  // 2. Empty state — no tiers, no history
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

  // 3. Error state — API returns errors (graceful fallback)
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

  // 4. Normal data — tiers and history render correctly
  it("renders tier cards and contest history with normal data", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: typicalTiers, message: "ok" }),
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
      expect(screen.getByText("Beginner")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(screen.getByText("Advanced")).toBeInTheDocument();
    expect(screen.getByText("Master")).toBeInTheDocument();
    // History section — wait for it since Promise.all may resolve at different times
    await waitFor(() => {
      expect(screen.getByText("recentContests")).toBeInTheDocument();
    }, { timeout: 3000 });
    // Elo change display (text is like "+12 elo" or "-8 elo" since t() returns key)
    expect(screen.getByText(/\+12/)).toBeInTheDocument();
    expect(screen.getByText(/-8/)).toBeInTheDocument();
  });

  it("shows ineligible message for non-eligible tiers", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: typicalTiers, message: "ok" }),
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
      expect(screen.getByText("Master")).toBeInTheDocument();
    });
    expect(screen.getByText("eloRequired")).toBeInTheDocument();
  });

  // 5. Boundary data — active contest (disables start buttons)
  it("shows active contest banner and disables start buttons", async () => {
    const activeContest = {
      id: "ac1",
      tier: "beginner",
      problems: [],
      total_problems: 4,
      problems_solved: 1,
      submissions: 2,
      time_limit_minutes: 90,
      started_at: "2025-06-01T08:00:00Z",
      ended_at: null,
      remaining_seconds: 3600,
      end_time: null,
      status: "active",
      elo_change: null,
    };

    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: typicalTiers, message: "ok" }),
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
    // All start buttons should show activeContestBtn text
    const activeBtns = screen.getAllByText("activeContestBtn");
    expect(activeBtns.length).toBe(3);
  });

  // 6. Error when starting contest
  it("shows error when contest start fails", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: typicalTiers, message: "ok" }),
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
      expect(screen.getByText("Beginner")).toBeInTheDocument();
    });
    // Click the eligible tier's start button
    const startButtons = screen.getAllByText("startContest");
    await user.click(startButtons[0]);
    await waitFor(() => {
      expect(screen.getByText("Cannot start contest")).toBeInTheDocument();
    });
  });

  // 7. Successful contest start navigates to contest page (covers lines 61-63)
  it("navigates to contest page on successful start", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: typicalTiers, message: "ok" }),
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
      expect(screen.getByText("Beginner")).toBeInTheDocument();
    });

    const startButtons = screen.getAllByText("startContest");
    await user.click(startButtons[0]);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/contest/new-contest-123");
    });
  });

  // 8. Resume active contest navigates to contest page (covers line 111)
  it("navigates to active contest on resume click", async () => {
    const activeContest = {
      id: "active-123",
      tier: "beginner",
      problems: [],
      total_problems: 4,
      problems_solved: 1,
      submissions: 2,
      time_limit_minutes: 90,
      started_at: "2025-06-01T08:00:00Z",
      ended_at: null,
      remaining_seconds: 3600,
      end_time: null,
      status: "active",
      elo_change: null,
    };

    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: typicalTiers, message: "ok" }),
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

  // 9. History item click navigates to contest detail (covers line 204)
  it("navigates to contest detail on history item click", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: typicalTiers, message: "ok" }),
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

    // Click on the history item showing tier "beginner" (capitalize renders "Beginner")
    // The history item shows `item.tier` with capitalize, so "beginner" -> "Beginner"
    // But this is different from the tier card. Find the history item by its solved count.
    await user.click(screen.getByText(/3\/4/));
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/contest/contest1");
    });
  });

  // 10. Starting state shows spinner (covers lines 175-179)
  it("shows loading spinner while contest is starting", async () => {
    server.use(
      http.get("*/api/v1/contest/tiers", () =>
        HttpResponse.json({ success: true, data: typicalTiers, message: "ok" }),
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
      expect(screen.getByText("Beginner")).toBeInTheDocument();
    });

    const startButtons = screen.getAllByText("startContest");
    await user.click(startButtons[0]);

    await waitFor(() => {
      expect(screen.getByText("starting")).toBeInTheDocument();
    });
  });
});
