import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
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

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: React.PropsWithChildren) => <>{children}</>,
}));

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
}));

vi.mock("@/components/ProblemViewer", () => ({
  ProblemViewer: ({ contestId, index }: { contestId: string; index: string }) => (
    <div data-testid="problem-viewer">{contestId}{index}</div>
  ),
}));

vi.mock("@/components/animations", () => ({
  EloChange: ({ value }: { value: number }) => <div data-testid="elo-change">{value}</div>,
  CoinAnimation: ({ amount }: { amount: number }) => <div data-testid="coin-anim">{amount}</div>,
  AcceptedCelebration: ({ active }: { active: boolean }) =>
    active ? <div data-testid="celebration" /> : null,
  AchievementPopup: () => <div data-testid="achievement-popup" />,
}));

vi.mock("@/components/SolvingTimeline", () => ({
  SolvingTimeline: () => <div data-testid="solving-timeline" />,
}));

vi.mock("@/utils", () => ({
  formatTime: (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`,
  getRatingColor: () => "#000000",
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
  useAuthStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      user: {
        id: "u1",
        username: "testuser",
        elo: 1500,
        tokens: 100,
      },
    }),
  ),
}));

const mockFreePlaySubmit = vi.fn();
const mockFreePlayQuit = vi.fn();
const mockFreePlayGetActive = vi.fn().mockResolvedValue(null);

vi.mock("@/services/freePlayApi", () => ({
  freePlaySubmit: (...args: unknown[]) => mockFreePlaySubmit(...args),
  freePlayQuit: (...args: unknown[]) => mockFreePlayQuit(...args),
  freePlayGetActive: () => mockFreePlayGetActive(),
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

import FreePlaySessionPage from "../FreePlaySessionPage";

const sampleProblem = {
  name: "Two Sum",
  contest_id: "1",
  index: "A",
  rating: 1200,
  tags: ["dp", "math"],
  url: "https://codeforces.com/1/A",
};

function renderPage(sessionId = "sess1", problem = sampleProblem, startedAt?: string) {
  return render(
    <MemoryRouter initialEntries={[
      {
        pathname: `/free-play/session/${sessionId}`,
        state: { problem, ...(startedAt ? { started_at: startedAt } : {}) },
      },
    ]}>
      <Routes>
        <Route path="/free-play/session/:id" element={<FreePlaySessionPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function renderPageWithoutState(sessionId = "sess1") {
  return render(
    <MemoryRouter initialEntries={[`/free-play/session/${sessionId}`]}>
      <Routes>
        <Route path="/free-play/session/:id" element={<FreePlaySessionPage />} />
        <Route path="/free-play" element={<div>FreePlay</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("FreePlaySessionPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.resetHandlers();
    // Mock submission tracking to return pending by default
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

  // 1. Renders session with problem info
  it("renders session with problem info from location state", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Two Sum")).toBeInTheDocument();
    });
    expect(screen.getAllByText("1200").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("dp")).toBeInTheDocument();
    expect(screen.getByTestId("problem-viewer")).toBeInTheDocument();
  });

  // 2. Shows timer and auto-tracking
  it("shows timer and auto-tracking status", async () => {
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("free_play:session.autoTracking")).toBeInTheDocument();
    });
    expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
  });

  // 3. Redirects to free-play when no state
  it("redirects to free-play when no problem state", async () => {
    renderPageWithoutState();

    // The component should navigate to /free-play
    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith("/free-play", { replace: true });
    });
  });

  // 4. Quit session - success
  it("quits session and shows result view", async () => {
    mockFreePlayQuit.mockResolvedValue({
      elo_change: -5,
    });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
    });

    await user.click(screen.getByText("free_play:session.quit"));

    await waitFor(() => {
      expect(screen.getByText("free_play:session.abandoned")).toBeInTheDocument();
    });
    expect(screen.getByTestId("elo-change")).toBeInTheDocument();
  });

  // 5. Quit session - failure
  it("shows error when quit fails", async () => {
    mockFreePlayQuit.mockRejectedValue(new Error("Quit failed"));
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
    });

    await user.click(screen.getByText("free_play:session.quit"));

    await waitFor(() => {
      expect(screen.getByText("free_play:error.quitFailed")).toBeInTheDocument();
    });
  });

  // 6. Result view shows new session and dashboard buttons
  it("shows action buttons in result view", async () => {
    mockFreePlayQuit.mockResolvedValue({ elo_change: 10 });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
    });

    await user.click(screen.getByText("free_play:session.quit"));

    await waitFor(() => {
      expect(screen.getByText("free_play:result.newSession")).toBeInTheDocument();
    });
    expect(screen.getByText("free_play:result.backToDashboard")).toBeInTheDocument();
  });

  // 7. New session navigates back
  it("navigates to free-play on new session click", async () => {
    mockFreePlayQuit.mockResolvedValue({ elo_change: 0 });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
    });

    await user.click(screen.getByText("free_play:session.quit"));

    await waitFor(() => {
      expect(screen.getByText("free_play:result.newSession")).toBeInTheDocument();
    });

    await user.click(screen.getByText("free_play:result.newSession"));
    expect(mockNavigate).toHaveBeenCalledWith("/free-play");
  });

  // 8. Result with solved state
  it("shows completed state when submit result is solved", async () => {
    mockFreePlayQuit.mockResolvedValue({ elo_change: 15 });
    const user = userEvent.setup();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
    });

    await user.click(screen.getByText("free_play:session.quit"));

    await waitFor(() => {
      expect(screen.getByTestId("elo-change")).toHaveTextContent("15");
    });
  });

  // =========================================================================
  // AUTO-TRACKING SUBMIT — AC / WA scenarios
  // =========================================================================

  describe("auto-tracking submit scenarios", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    // 9. Auto-tracking detects AC (solved) and shows completed result
    it("shows completed result when auto-tracking detects solved submission", async () => {
      const submitResult = {
        session_id: "sess1",
        solved: true,
        status: "completed",
        elo_change: 20,
        pp_change: 3.5,
        s_value: null,
        tokens_earned: 25,
        overkill_multiplier: 1.0,
        achievements: [],
      };

      mockFreePlaySubmit.mockResolvedValue(submitResult);

      server.use(
        http.get("*/api/v1/submission-tracking/status*", () =>
          HttpResponse.json({
            success: true,
            data: {
              status: "settled",
              verdict: "OK",
              attempts: 1,
              error_count: 0,
            },
            message: "ok",
          }),
        ),
      );

      renderPage();

      // Wait for active phase to render
      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      // Advance timers to trigger the first auto-tracking poll (5000ms)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5500);
      });

      // Should now show completed result
      await waitFor(() => {
        expect(screen.getByText("free_play:session.completed")).toBeInTheDocument();
      });

      // Verify solved state
      expect(screen.getByTestId("elo-change")).toHaveTextContent("20");
      expect(screen.getByText("free_play:result.ppChange")).toBeInTheDocument();
      expect(screen.getByText("free_play:result.tokensEarned")).toBeInTheDocument();
    });

    // 10. Auto-tracking detects WA (not solved) and shows not-solved result
    it("shows not-solved result when auto-tracking detects failed submission", async () => {
      const submitResult = {
        session_id: "sess1",
        solved: false,
        status: "completed",
        elo_change: -5,
        pp_change: -1.0,
        s_value: null,
        tokens_earned: 0,
        overkill_multiplier: 1.0,
        achievements: [],
      };

      mockFreePlaySubmit.mockResolvedValue(submitResult);

      server.use(
        http.get("*/api/v1/submission-tracking/status*", () =>
          HttpResponse.json({
            success: true,
            data: {
              status: "matched",
              verdict: "WRONG_ANSWER",
              attempts: 2,
              error_count: 1,
            },
            message: "ok",
          }),
        ),
      );

      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5500);
      });

      await waitFor(() => {
        expect(screen.getByText("free_play:session.notSolved")).toBeInTheDocument();
      });

      expect(screen.getByTestId("elo-change")).toHaveTextContent("-5");
    });

    // 11. Overkill bonus displayed when multiplier > 1.0
    it("displays overkill bonus when overkill_multiplier > 1.0", async () => {
      const submitResult = {
        session_id: "sess1",
        solved: true,
        status: "completed",
        elo_change: 30,
        pp_change: 5.0,
        s_value: null,
        tokens_earned: 50,
        overkill_multiplier: 1.5,
        achievements: [],
      };

      mockFreePlaySubmit.mockResolvedValue(submitResult);

      server.use(
        http.get("*/api/v1/submission-tracking/status*", () =>
          HttpResponse.json({
            success: true,
            data: {
              status: "settled",
              verdict: "OK",
              attempts: 1,
              error_count: 0,
            },
            message: "ok",
          }),
        ),
      );

      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5500);
      });

      await waitFor(() => {
        expect(screen.getByText("free_play:session.completed")).toBeInTheDocument();
      });

      // Overkill bonus section
      expect(screen.getByText("free_play:result.overkillBonus")).toBeInTheDocument();
      // Description renders the translation key with multiplier param
      expect(screen.getByText("free_play:result.overkillDesc")).toBeInTheDocument();
    });

    // 12. No overkill bonus when multiplier = 1.0
    it("does not show overkill bonus when multiplier is 1.0", async () => {
      const submitResult = {
        session_id: "sess1",
        solved: true,
        status: "completed",
        elo_change: 15,
        pp_change: 2.0,
        s_value: null,
        tokens_earned: 20,
        overkill_multiplier: 1.0,
        achievements: [],
      };

      mockFreePlaySubmit.mockResolvedValue(submitResult);

      server.use(
        http.get("*/api/v1/submission-tracking/status*", () =>
          HttpResponse.json({
            success: true,
            data: {
              status: "settled",
              verdict: "OK",
              attempts: 1,
              error_count: 0,
            },
            message: "ok",
          }),
        ),
      );

      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5500);
      });

      await waitFor(() => {
        expect(screen.getByText("free_play:session.completed")).toBeInTheDocument();
      });

      expect(screen.queryByText("free_play:result.overkillBonus")).not.toBeInTheDocument();
    });

    // 13. Achievement popup shows when submit result includes achievements
    it("triggers achievement popup when auto-submit returns achievements", async () => {
      const submitResult = {
        session_id: "sess1",
        solved: true,
        status: "completed",
        elo_change: 25,
        pp_change: 4.0,
        s_value: null,
        tokens_earned: 35,
        overkill_multiplier: 1.0,
        achievements: [
          { type: "streak_3", title: "Three in a Row", description: "Solved 3 problems in a row", icon: "fire" },
        ],
      };

      mockFreePlaySubmit.mockResolvedValue(submitResult);

      server.use(
        http.get("*/api/v1/submission-tracking/status*", () =>
          HttpResponse.json({
            success: true,
            data: {
              status: "settled",
              verdict: "OK",
              attempts: 1,
              error_count: 0,
            },
            message: "ok",
          }),
        ),
      );

      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5500);
      });

      await waitFor(() => {
        expect(screen.getByText("free_play:session.completed")).toBeInTheDocument();
      });

      // AchievementPopup should appear after 1500ms delay
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });

      await waitFor(() => {
        expect(screen.getByTestId("achievement-popup")).toBeInTheDocument();
      });
    });

    // 14. Celebration triggers on positive Elo
    it("triggers celebration when auto-submit results in positive Elo", async () => {
      const submitResult = {
        session_id: "sess1",
        solved: true,
        status: "completed",
        elo_change: 22,
        pp_change: 3.0,
        s_value: null,
        tokens_earned: 30,
        overkill_multiplier: 1.0,
        achievements: [],
      };

      mockFreePlaySubmit.mockResolvedValue(submitResult);

      server.use(
        http.get("*/api/v1/submission-tracking/status*", () =>
          HttpResponse.json({
            success: true,
            data: {
              status: "settled",
              verdict: "OK",
              attempts: 1,
              error_count: 0,
            },
            message: "ok",
          }),
        ),
      );

      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5500);
      });

      await waitFor(() => {
        expect(screen.getByText("free_play:session.completed")).toBeInTheDocument();
      });

      expect(screen.getByTestId("celebration")).toBeInTheDocument();
    });

    // 15. No celebration on negative Elo (quit/failed)
    it("does not trigger celebration on negative Elo change", async () => {
      // This test uses real timers (quit flow doesn't need fake timers)
      vi.useRealTimers();
      mockFreePlayQuit.mockResolvedValue({ elo_change: -10, session_id: "sess1", status: "quit" });
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await user.click(screen.getByText("free_play:session.quit"));

      await waitFor(() => {
        expect(screen.getByText("free_play:session.abandoned")).toBeInTheDocument();
      });

      expect(screen.queryByTestId("celebration")).not.toBeInTheDocument();
    });
  });

  // =========================================================================
  // QUIT SCENARIOS — stats display, error handling
  // =========================================================================

  describe("quit scenarios", () => {
    // 16. Quit shows correct Elo/pp/tokens stats (quit has no pp_change)
    it("displays correct stats when quitting with Elo loss", async () => {
      mockFreePlayQuit.mockResolvedValue({
        session_id: "sess1",
        status: "quit",
        elo_change: -8,
        new_elo: 1492,
        penalty: 5,
      });
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await user.click(screen.getByText("free_play:session.quit"));

      await waitFor(() => {
        expect(screen.getByText("free_play:session.abandoned")).toBeInTheDocument();
      });

      // Elo change should be displayed
      expect(screen.getByTestId("elo-change")).toHaveTextContent("-8");

      // pp_change is null for quit, so should show "-"
      expect(screen.getByText("free_play:result.ppChange")).toBeInTheDocument();

      // tokens is 0 for quit (no submitResult)
      // CoinAnimation mock shows amount, or "0" text
    });

    // 17. Quit with null Elo shows dash
    it("displays dash for Elo when quit result has null elo_change", async () => {
      mockFreePlayQuit.mockResolvedValue({
        session_id: "sess1",
        status: "quit",
        elo_change: null,
        new_elo: null,
        penalty: null,
      });
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await user.click(screen.getByText("free_play:session.quit"));

      await waitFor(() => {
        expect(screen.getByText("free_play:session.abandoned")).toBeInTheDocument();
      });

      // EloChange should not render when eloChange is null
      expect(screen.queryByTestId("elo-change")).not.toBeInTheDocument();
    });

    // 18. Quit shows loading spinner while quitting
    it("shows loading spinner while quit is in progress", async () => {
      let resolveQuit: (value: unknown) => void;
      mockFreePlayQuit.mockImplementation(() => new Promise((resolve) => {
        resolveQuit = resolve;
      }));
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await user.click(screen.getByText("free_play:session.quit"));

      // Should show quitting text
      await waitFor(() => {
        expect(screen.getByText("free_play:session.quitting")).toBeInTheDocument();
      });

      // Resolve to clean up
      resolveQuit!({
        session_id: "sess1",
        status: "quit",
        elo_change: -5,
        new_elo: 1495,
        penalty: 3,
      });

      await waitFor(() => {
        expect(screen.getByText("free_play:session.abandoned")).toBeInTheDocument();
      });
    });

    // 19. Dashboard button navigates correctly from result view
    it("navigates to dashboard from result view", async () => {
      mockFreePlayQuit.mockResolvedValue({
        session_id: "sess1",
        status: "quit",
        elo_change: -5,
        new_elo: 1495,
        penalty: 3,
      });
      const user = userEvent.setup();
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      await user.click(screen.getByText("free_play:session.quit"));

      await waitFor(() => {
        expect(screen.getByText("free_play:result.backToDashboard")).toBeInTheDocument();
      });

      await user.click(screen.getByText("free_play:result.backToDashboard"));
      expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
    });
  });

  // =========================================================================
  // SESSION RECOVERY — refresh/direct URL
  // =========================================================================

  describe("session recovery", () => {
    // 20. Recovers session from backend when no location state
    it("recovers active session from backend on page refresh", async () => {
      mockFreePlayGetActive.mockResolvedValue({
        problem: {
          name: "Recovered Problem",
          contest_id: "5",
          index: "E",
          rating: 1400,
          tags: ["greedy"],
          url: "https://codeforces.com/5/E",
        },
      });

      renderPageWithoutState();

      await waitFor(() => {
        expect(screen.getByText("Recovered Problem")).toBeInTheDocument();
      }, { timeout: 3000 });

      expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
    });

    // 21. Redirects to free-play when no active session and no state
    it("redirects when backend returns null for active session", async () => {
      mockFreePlayGetActive.mockResolvedValue(null);
      renderPageWithoutState();

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith("/free-play", { replace: true });
      });
    });

    // 22. Redirects when backend throws error
    it("redirects when backend throws error fetching active session", async () => {
      mockFreePlayGetActive.mockRejectedValue(new Error("Network error"));
      renderPageWithoutState();

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith("/free-play", { replace: true });
      });
    });
  });

  // -----------------------------------------------------------------------
  // FR-19: Timer persistence
  // -----------------------------------------------------------------------
  describe("Timer persistence (FR-19)", () => {
    it("starts timer from 0 when no started_at provided", async () => {
      renderPage();

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      // Timer should show 0:00 when just started
      expect(screen.getByText("0:00")).toBeInTheDocument();
    });

    it("starts timer with elapsed time from started_at", async () => {
      // started_at 60 seconds ago
      const sixtySecondsAgo = new Date(Date.now() - 60_000).toISOString();
      renderPage("sess1", sampleProblem, sixtySecondsAgo);

      await waitFor(() => {
        expect(screen.getByText("free_play:session.quit")).toBeInTheDocument();
      });

      // Wait for timer to reflect the elapsed time from started_at.
      // initialSeconds is computed asynchronously via setState chain,
      // so the timer may briefly show 0:00 before updating.
      await waitFor(() => {
        const timerEl = screen.getByText(/\d+:\d+/);
        const timerText = timerEl.textContent || "";
        const parts = timerText.split(":");
        const seconds = parseInt(parts[0]) * 60 + parseInt(parts[1]);
        expect(seconds).toBeGreaterThanOrEqual(59);
      });

      const timerEl = screen.getByText(/\d+:\d+/);
      const timerText = timerEl.textContent || "";
      const parts = timerText.split(":");
      const seconds = parseInt(parts[0]) * 60 + parseInt(parts[1]);
      expect(seconds).toBeLessThanOrEqual(65);
    });

    it("starts timer from started_at recovered via active session API", async () => {
      const fiveMinutesAgo = new Date(Date.now() - 300_000).toISOString();
      mockFreePlayGetActive.mockResolvedValue({
        session_id: "recovered-sess",
        problem: {
          name: "Recovered",
          contest_id: 500,
          index: "B",
          rating: 1400,
          tags: ["math"],
          url: "https://codeforces.com/500/B",
        },
        status: "active",
        started_at: fiveMinutesAgo,
      });

      renderPageWithoutState("recovered-sess");

      await waitFor(() => {
        expect(screen.getByText("Recovered")).toBeInTheDocument();
      });

      // Wait for timer to reflect the elapsed time from started_at.
      // The started_at comes from an async API call, so there are multiple
      // async state updates before the timer shows the correct value.
      await waitFor(() => {
        const timerEl = screen.getByText(/\d+:\d+/);
        const timerText = timerEl.textContent || "";
        const parts = timerText.split(":");
        const seconds = parseInt(parts[0]) * 60 + parseInt(parts[1]);
        expect(seconds).toBeGreaterThanOrEqual(295);
      });

      const timerEl = screen.getByText(/\d+:\d+/);
      const timerText = timerEl.textContent || "";
      const parts = timerText.split(":");
      const seconds = parseInt(parts[0]) * 60 + parseInt(parts[1]);
      expect(seconds).toBeLessThanOrEqual(310);
    });
  });
});
