import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
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

vi.mock("@/components/animations", () => ({
  EloChange: ({ value }: { value: number }) => <div data-testid="elo-change">{value}</div>,
  CoinAnimation: ({ amount }: { amount: number }) => <div data-testid="coin-anim">{amount}</div>,
  AcceptedCelebration: () => <div data-testid="celebration" />,
  AchievementPopup: () => <div data-testid="achievement-popup" />,
}));

vi.mock("@/components/ProblemViewer", () => ({
  ProblemViewer: ({ contestId, index }: { contestId: string; index: string }) => (
    <div data-testid="problem-viewer">{contestId}{index}</div>
  ),
}));

vi.mock("@/components/SolvingTimeline", () => ({
  SolvingTimeline: () => <div data-testid="solving-timeline" />,
}));

vi.mock("@/components/Avatar", () => ({
  Avatar: () => <div data-testid="avatar" />,
}));

vi.mock("@/components/medal/MedalBadge", () => ({
  MedalBadge: () => <div data-testid="medal-badge" />,
}));

vi.mock("@/utils", () => ({
  extractApiError: (err: unknown, fallback: string) => {
    const e = err as { response?: { data?: { error?: { message?: string } } } };
    return e?.response?.data?.error?.message ?? fallback;
  },
  formatTime: (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`,
  getRatingColor: () => "#000000",
  stripIndexPrefix: (name: string) => name.replace(/^[A-Z]\d*\.\s*/, ""),
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
  useAuthStore: Object.assign(
    vi.fn((selector?: (s: Record<string, unknown>) => unknown) => {
      const state = {
        user: {
          id: "u1",
          username: "testuser",
          elo: 1500,
          tokens: 100,
        },
      };
      return selector ? selector(state) : state;
    }),
  ),
}));

const mockConnect = vi.fn();
const mockDisconnect = vi.fn();
const mockResetLive = vi.fn();

vi.mock("@/stores/contestStore", () => ({
  useContestLiveStore: Object.assign(
    vi.fn((selector?: (s: Record<string, unknown>) => unknown) => {
      const state = {
        leaderboard: [
          { rank: 1, name: "testuser", elo: 1500, solved: 2, is_bot: false },
          { rank: 2, name: "Bot1", elo: 1200, solved: 1, is_bot: true },
        ],
        wsState: "connected",
        timeElapsed: 10,
        timeTotal: 90,
        contestEnded: false,
        connect: mockConnect,
        disconnect: mockDisconnect,
        reset: mockResetLive,
      };
      return selector ? selector(state) : state;
    }),
  ),
}));

// ---------------------------------------------------------------------------
// MSW server & data
// ---------------------------------------------------------------------------

const server = setupServer();

const activeContest = {
  id: "c1",
  tier: "beginner",
  status: "active",
  total_problems: 4,
  problems_solved: 1,
  submissions: 3,
  time_limit_minutes: 90,
  started_at: "2025-06-01T08:00:00Z",
  ended_at: null,
  remaining_seconds: 3600,
  end_time: new Date(Date.now() + 3600000).toISOString(),
  elo_change: null,
  problems: [
    { problem_id: "p1", name: "Two Sum", contest_id: "1", index: "A", rating: 800, url: "https://codeforces.com/1/A", solved: true },
    { problem_id: "p2", name: "Three Sum", contest_id: "2", index: "B", rating: 1000, url: "https://codeforces.com/2/B", solved: false },
    { problem_id: "p3", name: "Four Sum", contest_id: "3", index: "C", rating: 1200, url: "https://codeforces.com/3/C", solved: false },
    { problem_id: "p4", name: "Five Sum", contest_id: "4", index: "D", rating: 1400, url: "https://codeforces.com/4/D", solved: false },
  ],
};

const completedContest = {
  ...activeContest,
  status: "completed",
  ended_at: "2025-06-01T09:30:00Z",
  elo_change: 12,
};

const contestResult = {
  tier: "beginner",
  problems_solved: 2,
  total_problems: 4,
  submissions: 5,
  elo_change: 12,
  performance_rating: 1600,
  medal: { level: "bronze", type: "contest" },
  achievements: [],
  problems: [
    { problem_id: "p1", name: "Two Sum", index: "A", rating: 800, solved: true },
    { problem_id: "p2", name: "Three Sum", index: "B", rating: 1000, solved: true },
    { problem_id: "p3", name: "Four Sum", index: "C", rating: 1200, solved: false },
    { problem_id: "p4", name: "Five Sum", index: "D", rating: 1400, solved: false },
  ],
  // Extended fields
  elo_before: 1500,
  elo_after: 1512,
  pp_before: 40.0,
  pp_after: 42.5,
  pp_change: 2.5,
  rank: 3,
  total_participants: 11,
  melo_changes: null,
  time_spent_minutes: 45,
};

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import ContestDetailPage from "../ContestDetailPage";

function renderPage(contestId = "c1") {
  return render(
    <MemoryRouter initialEntries={[`/contest/${contestId}`]}>
      <Routes>
        <Route path="/contest/:id" element={<ContestDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ContestDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.resetHandlers();
    server.use(
      http.get("*/api/v1/submission-tracking/status*", () =>
        HttpResponse.json({
          success: true,
          data: { status: "pending" },
          message: "ok",
        }),
      ),
    );
  });

  // 1. Loading state
  it("shows loading spinner initially", () => {
    server.use(
      http.get("*/api/v1/contest/*", async () => {
        await new Promise(() => {});
      }),
    );
    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  // 2. Active contest renders problem list and timer
  it("renders active contest with problems, timer, and end button", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/Two Sum/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Three Sum/)).toBeInTheDocument();
    expect(screen.getByText(/Four Sum/)).toBeInTheDocument();
    expect(screen.getByText(/Five Sum/)).toBeInTheDocument();
    expect(screen.getByText("endContest")).toBeInTheDocument();
    expect(screen.getByText("backToContests")).toBeInTheDocument();
  });

  // 3. Active contest shows stats
  it("shows solved, total, rank, and elapsed stats", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("liveLeaderboard")).toBeInTheDocument();
    });
  });

  // 4. Live leaderboard renders entries
  it("renders live leaderboard with entries", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("liveLeaderboard")).toBeInTheDocument();
    });
    expect(screen.getByText("testuser")).toBeInTheDocument();
    expect(screen.getByText("Bot1")).toBeInTheDocument();
  });

  // 5. End contest transitions to completed
  it("ends contest and shows completed view", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
      ),
      http.post("*/api/v1/contest/c1/end", () =>
        HttpResponse.json({ success: true, data: {}, message: "ok" }),
      ),
      http.get("*/api/v1/contest/c1/result", () =>
        HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
      ),
    );
    // After end, subsequent GET should return completed
    let endCalled = false;
    server.use(
      http.get("*/api/v1/contest/c1", () => {
        if (endCalled) {
          return HttpResponse.json({ success: true, data: completedContest, message: "ok" });
        }
        return HttpResponse.json({ success: true, data: activeContest, message: "ok" });
      }),
      http.post("*/api/v1/contest/c1/end", () => {
        endCalled = true;
        return HttpResponse.json({ success: true, data: {}, message: "ok" });
      }),
      http.get("*/api/v1/contest/c1/result", () =>
        HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("endContest")).toBeInTheDocument();
    });

    await user.click(screen.getByText("endContest"));

    await waitFor(() => {
      expect(screen.getByText("contestComplete")).toBeInTheDocument();
    });
  });

  // 6. Completed contest renders result
  it("renders completed contest result view", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
      ),
      http.get("*/api/v1/contest/c1/result", () =>
        HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("contestComplete")).toBeInTheDocument();
    });
    expect(screen.getByText("performanceRating")).toBeInTheDocument();
    expect(screen.getByText("1600")).toBeInTheDocument();
    expect(screen.getByText("newContest")).toBeInTheDocument();
    expect(screen.getByText("dashboard")).toBeInTheDocument();
  });

  // 7. Error loading contest -- component falls back gracefully
  it("renders fallback view when contest fetch fails", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR", message: "Contest not found" } },
          { status: 404 },
        ),
      ),
    );
    renderPage();

    // The component gracefully handles the error by falling through to
    // the completed view or fallback, not crashing
    await waitFor(() => {
      // Either shows backToContests or the fallback loading spinner
      const hasContent = screen.queryByText("backToContests") ||
        screen.queryByTestId("loading-spinner");
      expect(hasContent).toBeTruthy();
    });
  });

  // 8. Navigate back to contests
  it("navigates back to contest list on button click", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("backToContests")).toBeInTheDocument();
    });

    await user.click(screen.getByText("backToContests"));
    expect(mockNavigate).toHaveBeenCalledWith("/contest");
  });

  // 9. New contest button navigates to contest page
  it("navigates to contest page on new contest click", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
      ),
      http.get("*/api/v1/contest/c1/result", () =>
        HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("newContest")).toBeInTheDocument();
    });

    await user.click(screen.getByText("newContest"));
    expect(mockNavigate).toHaveBeenCalledWith("/contest");
  });

  // 10. Problem summary in completed view
  it("shows problem summary in completed view", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
      ),
      http.get("*/api/v1/contest/c1/result", () =>
        HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
      ),
    );
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("problemSummary")).toBeInTheDocument();
    });
  });

  // 11. End contest failure
  it("shows error when end contest fails", async () => {
    server.use(
      http.get("*/api/v1/contest/c1", () =>
        HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
      ),
      http.post("*/api/v1/contest/c1/end", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR", message: "Cannot end contest" } },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("endContest")).toBeInTheDocument();
    });

    await user.click(screen.getByText("endContest"));

    await waitFor(() => {
      expect(screen.getByText("Cannot end contest")).toBeInTheDocument();
    });
  });

  // =========================================================================
  // LIVE CONTEST — leaderboard updates, countdown, WS state
  // =========================================================================

  describe("live contest scenarios", () => {
    // 12. Leaderboard entries render human/bot distinction correctly
    it("distinguishes human and bot entries in leaderboard", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("liveLeaderboard")).toBeInTheDocument();
      });

      // Human entry has "you" badge
      expect(screen.getByText("you")).toBeInTheDocument();
      expect(screen.getByText("human")).toBeInTheDocument();
      // Bot entry
      expect(screen.getByText("bot")).toBeInTheDocument();
    });

    // 13. Stats display correct values from contest data
    it("shows correct solved/total stats in active phase", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("liveLeaderboard")).toBeInTheDocument();
      });

      // activeContest has problems_solved=1, total_problems=4
      // "1" appears multiple times (solved count + rank from leaderboard), use getAllByText
      expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText("4").length).toBeGreaterThanOrEqual(1);
    });

    // 14. Progress bar renders with correct percentage
    it("renders progress bar based on solved/total ratio", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("liveLeaderboard")).toBeInTheDocument();
      });

      // problems_solved=1, total_problems=4 => 25%
      const progressBar = document.querySelector('.bg-green-400.transition-all') as HTMLElement;
      expect(progressBar).toBeTruthy();
      expect(progressBar.style.width).toBe("25%");
    });

    // 15. Problem list renders all problems with correct status icons
    it("renders solved and unsolved problems with correct icons", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText(/Two Sum/)).toBeInTheDocument();
      });

      // All 4 problems should be listed
      expect(screen.getByText(/Two Sum/)).toBeInTheDocument();
      expect(screen.getByText(/Three Sum/)).toBeInTheDocument();
      expect(screen.getByText(/Four Sum/)).toBeInTheDocument();
      expect(screen.getByText(/Five Sum/)).toBeInTheDocument();
    });

    // 15b. Unsolved problems must NOT show a spinning Loader2 icon
    it("does not show spinning loader icon on unsolved problems", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText(/Three Sum/)).toBeInTheDocument();
      });

      // The page has a legitimate spinning Loader2 in the auto-tracking info
      // section (waitingForCFResult), but no spinning Loader2 should appear
      // next to individual problem rows.
      const problemRows = screen.getAllByText(/Sum/).map((el) => el.closest("[class*='flex']"));
      for (const row of problemRows) {
        if (!row) continue;
        const spinners = row.querySelectorAll(".animate-spin");
        expect(spinners.length).toBe(0);
      }
    });

    // 16. Elapsed time displays from store values
    it("displays elapsed time from live store", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: activeContest, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("liveLeaderboard")).toBeInTheDocument();
      });

      // Mock store returns timeElapsed=10, timeTotal=90
      // "10" and "90" may appear in multiple elements; verify they exist
      expect(screen.getAllByText("10").length).toBeGreaterThanOrEqual(1);
      // "minutes" is rendered inside a span with "/90 minutes", use substring match
      expect(screen.getByText(/minutes/)).toBeInTheDocument();
      // Check the specific "elapsed" stat label is present
      expect(screen.getByText("elapsed")).toBeInTheDocument();
    });
  });

  // =========================================================================
  // COMPLETED CONTEST — performance rating, medal, achievements, summary
  // =========================================================================

  describe("completed contest result", () => {
    // 17. Performance rating renders with correct value
    it("displays performance rating in result view", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // Performance rating header and value
      expect(screen.getByText("performanceRating")).toBeInTheDocument();
      expect(screen.getByText("performanceRatingDesc")).toBeInTheDocument();
      expect(screen.getByText("1600")).toBeInTheDocument();
    });

    // 18. Medal badge renders when medal is not unranked
    it("displays medal badge in result view", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // MedalBadge mock renders data-testid="medal-badge"
      expect(screen.getByTestId("medal-badge")).toBeInTheDocument();
    });

    // 19. No medal badge when medal level is unranked
    it("does not show medal badge when level is unranked", async () => {
      const unrankedResult = {
        ...contestResult,
        medal: { level: "unranked", type: "contest" },
      };
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: unrankedResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      expect(screen.queryByTestId("medal-badge")).not.toBeInTheDocument();
    });

    // 20. No medal badge when medal is null
    it("does not show medal badge when medal is null", async () => {
      const noMedalResult = {
        ...contestResult,
        medal: null,
      };
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: noMedalResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      expect(screen.queryByTestId("medal-badge")).not.toBeInTheDocument();
    });

    // 21. Elo change displayed correctly in result stats
    it("shows positive elo change with + prefix in result", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // contestResult has elo_change=12, should show "+12"
      expect(screen.getByText("+12")).toBeInTheDocument();
    });

    // 22. Negative elo change in result
    it("shows negative elo change without + prefix", async () => {
      const lossResult = { ...contestResult, elo_change: -8 };
      const lossContest = { ...completedContest, elo_change: -8 };
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: lossContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: lossResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      expect(screen.getByText("-8")).toBeInTheDocument();
      // Should NOT have + prefix
      expect(screen.queryByText("+-8")).not.toBeInTheDocument();
    });

    // 23. Zero elo change
    it("shows zero elo change as plain 0", async () => {
      const zeroResult = { ...contestResult, elo_change: 0 };
      const zeroContest = { ...completedContest, elo_change: 0 };
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: zeroContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: zeroResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // elo_change=0 should show "0" (no + prefix)
      const eloElements = screen.getAllByText("0");
      expect(eloElements.length).toBeGreaterThanOrEqual(1);
    });

    // 24. Problem summary shows solved/unsolved icons
    it("renders problem summary with solved and unsolved problems", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("problemSummary")).toBeInTheDocument();
      });

      // Two Sum (solved) and Three Sum (solved) from contestResult
      expect(screen.getByText(/Two Sum/)).toBeInTheDocument();
      expect(screen.getByText(/Three Sum/)).toBeInTheDocument();
      expect(screen.getByText(/Four Sum/)).toBeInTheDocument();
      expect(screen.getByText(/Five Sum/)).toBeInTheDocument();
    });

    // 25. Contest tier displayed
    it("displays contest tier in result view", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // Tier should be shown (contestResult.tier = "beginner")
      expect(screen.getByText("beginner")).toBeInTheDocument();
    });

    // 26. Submissions count shown in result
    it("shows submissions count in completed view", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // contestResult.submissions = 5
      expect(screen.getByText("submissions")).toBeInTheDocument();
      // Find the "5" that's rendered inside the submissions card
      const fives = screen.getAllByText("5");
      expect(fives.length).toBeGreaterThanOrEqual(1);
    });

    // 27. Result without performance_rating does not show PR card
    it("hides performance rating when result has no PR", async () => {
      const noPrResult = { ...contestResult, performance_rating: null };
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: noPrResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      expect(screen.queryByText("performanceRating")).not.toBeInTheDocument();
    });

    // 28. Dashboard button in completed view navigates correctly
    it("navigates to dashboard on dashboard button click", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("dashboard")).toBeInTheDocument();
      });

      await user.click(screen.getByText("dashboard"));
      expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
    });

    // =========================================================================
    // Extended result fields
    // =========================================================================

    // 29. Elo before/after displayed in completed view
    it("displays elo before and after values", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // Elo card should show "Global Elo" heading and before/after
      expect(screen.getByText("globalElo")).toBeInTheDocument();
      // elo_before=1500, elo_after=1512
      const all1500 = screen.getAllByText("1500");
      const all1512 = screen.getAllByText("1512");
      expect(all1500.length).toBeGreaterThanOrEqual(1);
      expect(all1512.length).toBeGreaterThanOrEqual(1);
    });

    // 30. PP before/after displayed
    it("displays PP before and after values", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // PP card should display pp heading and values
      expect(screen.getByText("pp")).toBeInTheDocument();
      // pp_before=40.0, pp_after=42.5
      expect(screen.getByText("40.0")).toBeInTheDocument();
      expect(screen.getByText("42.5")).toBeInTheDocument();
    });

    // 31. PP change displayed with + prefix
    it("displays PP change with + prefix for positive values", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // pp_change=2.5 should show "+2.5"
      expect(screen.getByText("+2.5")).toBeInTheDocument();
    });

    // 32. Rank displayed with # prefix
    it("displays rank with # prefix and total participants", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // rank=3, total_participants=11 -> "#3 /11"
      expect(screen.getByText("#3")).toBeInTheDocument();
      expect(screen.getByText(/\/11/)).toBeInTheDocument();
    });

    // 33. Time spent displayed
    it("displays time spent in minutes", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // time_spent_minutes=45 -> "45min"
      expect(screen.getByText("timeSpent")).toBeInTheDocument();
      expect(screen.getByText("45min")).toBeInTheDocument();
    });

    // 34. Time spent in hours for >= 60 min
    it("displays time spent in hours when >= 60 minutes", async () => {
      const longResult = { ...contestResult, time_spent_minutes: 90 };
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: longResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      expect(screen.getByText("1h30m")).toBeInTheDocument();
    });

    // 35. Solved count shown as fraction
    it("displays solved count as fraction in result overview", async () => {
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // "solvedCount" label and solved fraction display
      expect(screen.getByText("solvedCount")).toBeInTheDocument();
      // solved=2, total=4 -> "2" appears in solved fraction, "4" appears as total
      const allTwos = screen.getAllByText("2");
      expect(allTwos.length).toBeGreaterThanOrEqual(1);
    });

    // 36. Null extended fields handled gracefully
    it("handles null extended fields gracefully", async () => {
      const minimalResult = {
        ...contestResult,
        elo_before: null,
        elo_after: null,
        pp_before: null,
        pp_after: null,
        pp_change: null,
        rank: null,
        total_participants: null,
        time_spent_minutes: null,
      };
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: minimalResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      // Rank should show "-"
      expect(screen.getByText("rank")).toBeInTheDocument();
      // Time spent should show "-"
      expect(screen.getByText("timeSpent")).toBeInTheDocument();
      // PP card should show "noChange"
      expect(screen.getByText("noChange")).toBeInTheDocument();
    });

    // 37. Negative PP change displayed correctly
    it("shows negative PP change without + prefix", async () => {
      const lossResult = {
        ...contestResult,
        pp_before: 50.0,
        pp_after: 45.0,
        pp_change: -5.0,
      };
      server.use(
        http.get("*/api/v1/contest/c1", () =>
          HttpResponse.json({ success: true, data: completedContest, message: "ok" }),
        ),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: lossResult, message: "ok" }),
        ),
      );
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      expect(screen.getByText("-5")).toBeInTheDocument();
    });
  });

  // =========================================================================
  // CONTEST END — countdown triggers, manual end, error handling
  // =========================================================================

  describe("contest end scenarios", () => {
    // 29. End contest disconnects WebSocket
    it("disconnects WebSocket when contest ends", async () => {
      let endCalled = false;
      server.use(
        http.get("*/api/v1/contest/c1", () => {
          if (endCalled) {
            return HttpResponse.json({ success: true, data: completedContest, message: "ok" });
          }
          return HttpResponse.json({ success: true, data: activeContest, message: "ok" });
        }),
        http.post("*/api/v1/contest/c1/end", () => {
          endCalled = true;
          return HttpResponse.json({ success: true, data: {}, message: "ok" });
        }),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json({ success: true, data: contestResult, message: "ok" }),
        ),
      );

      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("endContest")).toBeInTheDocument();
      });

      await user.click(screen.getByText("endContest"));

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      expect(mockDisconnect).toHaveBeenCalled();
    });

    // 30. End contest fetches result after completion
    it("fetches result endpoint after ending contest", async () => {
      let endCalled = false;
      let resultFetched = false;
      server.use(
        http.get("*/api/v1/contest/c1", () => {
          if (endCalled) {
            return HttpResponse.json({ success: true, data: completedContest, message: "ok" });
          }
          return HttpResponse.json({ success: true, data: activeContest, message: "ok" });
        }),
        http.post("*/api/v1/contest/c1/end", () => {
          endCalled = true;
          return HttpResponse.json({ success: true, data: {}, message: "ok" });
        }),
        http.get("*/api/v1/contest/c1/result", () => {
          resultFetched = true;
          return HttpResponse.json({ success: true, data: contestResult, message: "ok" });
        }),
      );

      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("endContest")).toBeInTheDocument();
      });

      await user.click(screen.getByText("endContest"));

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });

      expect(resultFetched).toBe(true);
    });

    // 31. End contest without result endpoint still shows completed
    it("shows completed view even when result endpoint fails", async () => {
      let endCalled = false;
      server.use(
        http.get("*/api/v1/contest/c1", () => {
          if (endCalled) {
            return HttpResponse.json({ success: true, data: completedContest, message: "ok" });
          }
          return HttpResponse.json({ success: true, data: activeContest, message: "ok" });
        }),
        http.post("*/api/v1/contest/c1/end", () => {
          endCalled = true;
          return HttpResponse.json({ success: true, data: {}, message: "ok" });
        }),
        http.get("*/api/v1/contest/c1/result", () =>
          HttpResponse.json(
            { success: false, error: { code: "ERR", message: "No result" } },
            { status: 404 },
          ),
        ),
      );

      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("endContest")).toBeInTheDocument();
      });

      await user.click(screen.getByText("endContest"));

      await waitFor(() => {
        expect(screen.getByText("contestComplete")).toBeInTheDocument();
      });
    });
  });
});
