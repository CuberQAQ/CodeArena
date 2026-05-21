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

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({
    user: { id: "u1", username: "testuser", elo: 1200, tokens: 100 },
    isAuthenticated: true,
    isLoading: false,
    fetchUser: vi.fn().mockResolvedValue(undefined),
  })),
}));

vi.mock("@/components/animations/MatchWaiting", () => ({
  MatchWaiting: ({ className }: { className?: string }) => (
    <div data-testid="match-waiting" className={className}>Finding opponent...</div>
  ),
}));

vi.mock("@/components/animations/EloChange", () => ({
  EloChange: ({ value }: { value: number; _triggerKey?: number }) => (
    <div data-testid="elo-change">Elo: {value}</div>
  ),
}));

vi.mock("@/components/animations/AcceptedCelebration", () => ({
  AcceptedCelebration: ({ active }: { active: boolean }) =>
    active ? <div data-testid="celebration">Celebrating!</div> : null,
}));

vi.mock("@/components/animations", () => ({
  AchievementPopup: ({ achievements }: { achievements: Array<{ type: string; title: string }> }) => (
    <div data-testid="achievement-popup">
      {achievements.map((a) => <span key={a.type}>{a.title}</span>)}
    </div>
  ),
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

import ChallengePage from "../ChallengePage";

function renderWithRoutes(initialPath = "/challenge") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/challenge" element={<ChallengePage />} />
        <Route path="/challenge/:sessionId" element={<ChallengePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ChallengePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.resetHandlers();
  });

  // --- IDLE PHASE ---

  // 1. Initial state (idle phase) — renders PvP and PvE buttons
  it("renders idle phase with PvP and PvE buttons by default", async () => {
    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderWithRoutes();
    await waitFor(() => {
      expect(screen.getByText("randomChallenge")).toBeInTheDocument();
    });
    expect(screen.getByText("findOpponent")).toBeInTheDocument();
    expect(screen.getByText("soloChallenge")).toBeInTheDocument();
  });

  // 2. Error state — queue join fails
  it("displays error when joining queue fails", async () => {
    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.post("*/api/v1/challenge/queue", () =>
        HttpResponse.json(
          { success: false, error: { code: "QUEUE_ERROR", message: "Queue is full" } },
          { status: 400 },
        ),
      ),
    );

    renderWithRoutes();
    const user = userEvent.setup();
    await waitFor(() => {
      expect(screen.getByText("findOpponent")).toBeInTheDocument();
    });
    await user.click(screen.getByText("findOpponent"));
    await waitFor(() => {
      expect(screen.getByText("Queue is full")).toBeInTheDocument();
    });
  });

  // --- RESULT PHASE (via resume with completed challenge) ---

  // 3. Normal data — shows result when loading a completed challenge
  it("shows result phase when resuming a completed challenge via URL", async () => {
    const challengeDetail = {
      id: "s1",
      challenger_id: "u1",
      opponent_id: "u2",
      problem_id: "p1",
      problem_rating: 1500,
      problem: { contest_id: 123, index: "A", name: "Two Sum", rating: 1500, tags: ["dp", "math"], url: "https://codeforces.com/123/A" },
      challenger_solved: true,
      opponent_solved: false,
      challenger_submissions: 2,
      opponent_submissions: 3,
      challenger_time: 300,
      opponent_time: 600,
      status: "completed",
      result: "win",
      is_challenger: true,
      elo_change: 15,
      tokens_earned: 25,
      opponent_tokens_earned: 0,
      created_at: new Date(Date.now() - 600000).toISOString(),
      completed_at: new Date().toISOString(),
    };

    server.use(
      http.get("*/api/v1/challenge/s1", () =>
        HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
      ),
    );

    renderWithRoutes("/challenge/s1");

    await waitFor(() => {
      expect(screen.getByText("victory")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(screen.getByText("Two Sum")).toBeInTheDocument();
    expect(screen.getByText("1500")).toBeInTheDocument();
  });

  // 4. Boundary data — result with elo_change=0, tokens_earned=0
  it("shows result phase correctly with zero elo change and zero tokens", async () => {
    const challengeDetail = {
      id: "s2",
      challenger_id: "u1",
      opponent_id: "u2",
      problem_id: "p2",
      problem_rating: 800,
      problem: { contest_id: 100, index: "A", name: "A+B", rating: 800, tags: [], url: "https://codeforces.com/100/A" },
      challenger_solved: true,
      opponent_solved: true,
      challenger_submissions: 1,
      opponent_submissions: 1,
      challenger_time: 120,
      opponent_time: 90,
      status: "completed",
      result: "draw",
      is_challenger: true,
      elo_change: 0,
      tokens_earned: 0,
      opponent_tokens_earned: 0,
      created_at: new Date(Date.now() - 600000).toISOString(),
      completed_at: new Date().toISOString(),
    };

    server.use(
      http.get("*/api/v1/challenge/s2", () =>
        HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
      ),
    );

    renderWithRoutes("/challenge/s2");

    await waitFor(() => {
      expect(screen.getByText("draw")).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  // 5. Boundary data — quit result
  it("shows quit result phase correctly", async () => {
    const challengeDetail = {
      id: "s3",
      challenger_id: "u1",
      opponent_id: "u2",
      problem_id: "p3",
      problem_rating: 2000,
      problem: null,
      challenger_solved: false,
      opponent_solved: false,
      challenger_submissions: 0,
      opponent_submissions: 0,
      challenger_time: null,
      opponent_time: null,
      status: "quit",
      result: "quit",
      is_challenger: true,
      elo_change: -10,
      tokens_earned: null,
      opponent_tokens_earned: null,
      created_at: new Date(Date.now() - 600000).toISOString(),
      completed_at: new Date().toISOString(),
    };

    server.use(
      http.get("*/api/v1/challenge/s3", () =>
        HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
      ),
    );

    renderWithRoutes("/challenge/s3");

    await waitFor(() => {
      expect(screen.getByText("challengeAbandoned")).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  // --- Active challenge resume ---

  // 6. Resumes active challenge (no sessionId in URL, but active challenge exists)
  it("resumes active challenge when no sessionId in URL", async () => {
    const activeInfo = {
      id: "s4",
      problem_id: "p4",
      problem_name: "Active Problem",
      problem_rating: 1300,
      created_at: new Date(Date.now() - 120000).toISOString(),
      is_challenger: true,
      opponent_username: "opponent",
      opponent_elo: 1400,
      status: "active",
    };

    const challengeDetail = {
      id: "s4",
      challenger_id: "u1",
      opponent_id: "u2",
      problem_id: "p4",
      problem_rating: 1300,
      problem: { contest_id: 200, index: "B", name: "Active Problem", rating: 1300, tags: ["greedy"], url: "https://codeforces.com/200/B" },
      challenger_solved: false,
      opponent_solved: false,
      challenger_submissions: 0,
      opponent_submissions: 0,
      challenger_time: null,
      opponent_time: null,
      status: "active",
      result: null,
      is_challenger: true,
      elo_change: null,
      tokens_earned: null,
      opponent_tokens_earned: null,
      created_at: new Date(Date.now() - 120000).toISOString(),
      completed_at: null,
    };

    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: activeInfo, message: "ok" }),
      ),
      http.get("*/api/v1/challenge/s4", () =>
        HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
      ),
    );

    renderWithRoutes();
    await waitFor(() => {
      expect(screen.getByText("challengeInProgress")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(screen.getByText("Active Problem")).toBeInTheDocument();
  });

  // --- PvE navigation ---
  it("has a button to navigate to PvE challenge page", async () => {
    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
    );

    renderWithRoutes();
    await waitFor(() => {
      expect(screen.getByText("soloChallenge")).toBeInTheDocument();
    });
  });

  // --- WAITING_OPPONENT PHASE ---

  // 8. waiting_opponent: shows waiting UI, then transitions to in_progress when opponent confirms
  it("shows waiting phase when start returns waiting_opponent, then polls and transitions to in_progress", async () => {
    const sessionId = "ws1";

    // Track call count to simulate status change after first poll
    let detailCallCount = 0;

    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      // Queue returns matched
      http.post("*/api/v1/challenge/queue", () =>
        HttpResponse.json({
          success: true,
          data: { matched: true, session_id: sessionId, status: "matched" },
          message: "ok",
        }),
      ),
      // Status polling (not needed but just in case)
      http.get("*/api/v1/challenge/status", () =>
        HttpResponse.json({ success: true, data: { matched: true, session_id: sessionId }, message: "ok" }),
      ),
      // Start returns waiting_opponent
      http.post("*/api/v1/challenge/start", () =>
        HttpResponse.json({
          success: true,
          data: {
            session_id: sessionId,
            problem: null,
            status: "waiting_opponent",
          },
          message: "ok",
        }),
      ),
      // Detail: first call returns pending, second returns active
      http.get("*/api/v1/challenge/ws1", () => {
        detailCallCount++;
        if (detailCallCount === 1) {
          return HttpResponse.json({
            success: true,
            data: {
              id: sessionId,
              status: "pending",
              problem: null,
              result: null,
            },
            message: "ok",
          });
        }
        return HttpResponse.json({
          success: true,
          data: {
            id: sessionId,
            status: "active",
            problem: { contest_id: 300, index: "C", name: "Polished Problem", rating: 1600, tags: ["dp"], url: "https://codeforces.com/300/C" },
            result: null,
            is_challenger: true,
            elo_change: null,
            tokens_earned: null,
            created_at: new Date().toISOString(),
          },
          message: "ok",
        });
      }),
    );

    renderWithRoutes();
    const user = userEvent.setup();

    // 1. Click "Find Opponent" -> enters matched phase (queue returns matched immediately)
    await waitFor(() => {
      expect(screen.getByText("findOpponent")).toBeInTheDocument();
    });
    await user.click(screen.getByText("findOpponent"));

    // 2. Wait for matched phase and click "Start Challenge"
    await waitFor(() => {
      expect(screen.getByText("startChallenge")).toBeInTheDocument();
    }, { timeout: 3000 });
    await user.click(screen.getByText("startChallenge"));

    // 3. Should now be in waiting phase (not in_progress)
    await waitFor(() => {
      expect(screen.getByText("waitingForOpponent")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Should NOT show in_progress UI
    expect(screen.queryByText("challengeInProgress")).not.toBeInTheDocument();

    // 4. After polling, should transition to in_progress
    await waitFor(() => {
      expect(screen.getByText("challengeInProgress")).toBeInTheDocument();
    }, { timeout: 10000 });
    expect(screen.getByText("Polished Problem")).toBeInTheDocument();
  });

  // 9. waiting_opponent: Cancel button returns to idle
  it("returns to idle when cancel is clicked during waiting phase", async () => {
    const sessionId = "ws2";

    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.post("*/api/v1/challenge/queue", () =>
        HttpResponse.json({
          success: true,
          data: { matched: true, session_id: sessionId, status: "matched" },
          message: "ok",
        }),
      ),
      http.post("*/api/v1/challenge/start", () =>
        HttpResponse.json({
          success: true,
          data: {
            session_id: sessionId,
            problem: null,
            status: "waiting_opponent",
          },
          message: "ok",
        }),
      ),
      // Keep returning pending so waiting phase persists
      http.get("*/api/v1/challenge/ws2", () =>
        HttpResponse.json({
          success: true,
          data: { id: sessionId, status: "pending", problem: null, result: null },
          message: "ok",
        }),
      ),
    );

    renderWithRoutes();
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByText("findOpponent")).toBeInTheDocument();
    });
    await user.click(screen.getByText("findOpponent"));

    await waitFor(() => {
      expect(screen.getByText("startChallenge")).toBeInTheDocument();
    }, { timeout: 3000 });
    await user.click(screen.getByText("startChallenge"));

    await waitFor(() => {
      expect(screen.getByText("waitingForOpponent")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Click cancel
    await user.click(screen.getByText("common:cancel"));

    // Should be back to idle
    await waitFor(() => {
      expect(screen.getByText("findOpponent")).toBeInTheDocument();
    });
  });

  // 10. waiting_opponent: opponent leaves during wait -> transitions to result
  it("transitions to result when opponent quits during waiting phase", async () => {
    const sessionId = "ws3";
    let detailCallCount = 0;

    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.post("*/api/v1/challenge/queue", () =>
        HttpResponse.json({
          success: true,
          data: { matched: true, session_id: sessionId, status: "matched" },
          message: "ok",
        }),
      ),
      http.post("*/api/v1/challenge/start", () =>
        HttpResponse.json({
          success: true,
          data: {
            session_id: sessionId,
            problem: null,
            status: "waiting_opponent",
          },
          message: "ok",
        }),
      ),
      http.get("*/api/v1/challenge/ws3", () => {
        detailCallCount++;
        if (detailCallCount <= 1) {
          return HttpResponse.json({
            success: true,
            data: { id: sessionId, status: "pending", problem: null, result: null },
            message: "ok",
          });
        }
        return HttpResponse.json({
          success: true,
          data: {
            id: sessionId,
            status: "completed",
            result: "win",
            problem: null,
            is_challenger: true,
            elo_change: 5,
            tokens_earned: 0,
            created_at: new Date().toISOString(),
          },
          message: "ok",
        });
      }),
    );

    renderWithRoutes();
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByText("findOpponent")).toBeInTheDocument();
    });
    await user.click(screen.getByText("findOpponent"));

    await waitFor(() => {
      expect(screen.getByText("startChallenge")).toBeInTheDocument();
    }, { timeout: 3000 });
    await user.click(screen.getByText("startChallenge"));

    await waitFor(() => {
      expect(screen.getByText("waitingForOpponent")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Should eventually transition to result
    await waitFor(() => {
      expect(screen.getByText("victory")).toBeInTheDocument();
    }, { timeout: 10000 });
  });

  // --- IN_PROGRESS PHASE POLLING (Bug 28.2) ---

  // 11. in_progress polling: detects opponent quit and transitions to result
  it("detects opponent quit during in_progress phase and shows result", async () => {
    const sessionId = "ip1";
    let detailCallCount = 0;

    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.post("*/api/v1/challenge/queue", () =>
        HttpResponse.json({
          success: true,
          data: { matched: true, session_id: sessionId, status: "matched" },
          message: "ok",
        }),
      ),
      http.post("*/api/v1/challenge/start", () =>
        HttpResponse.json({
          success: true,
          data: {
            session_id: sessionId,
            problem: { contest_id: 400, index: "D", name: "Opponent Quit Detection", rating: 1400, tags: ["greedy"], url: "https://codeforces.com/400/D" },
            status: "problem_revealed",
          },
          message: "ok",
        }),
      ),
      http.get("*/api/v1/challenge/ip1", () => {
        detailCallCount++;
        // First call is for fetching full details after start
        if (detailCallCount === 1) {
          return HttpResponse.json({
            success: true,
            data: {
              id: sessionId,
              status: "active",
              problem: { contest_id: 400, index: "D", name: "Opponent Quit Detection", rating: 1400, tags: ["greedy"], url: "https://codeforces.com/400/D" },
              result: null,
              is_challenger: true,
              elo_change: null,
              tokens_earned: null,
              created_at: new Date().toISOString(),
            },
            message: "ok",
          });
        }
        // Subsequent calls from in_progress polling: opponent has quit
        return HttpResponse.json({
          success: true,
          data: {
            id: sessionId,
            status: "completed",
            result: "win",
            problem: { contest_id: 400, index: "D", name: "Opponent Quit Detection", rating: 1400, tags: ["greedy"], url: "https://codeforces.com/400/D" },
            is_challenger: true,
            elo_change: 12,
            tokens_earned: 20,
            created_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
          },
          message: "ok",
        });
      }),
    );

    renderWithRoutes();
    const user = userEvent.setup();

    // Join queue -> matched immediately
    await waitFor(() => {
      expect(screen.getByText("findOpponent")).toBeInTheDocument();
    });
    await user.click(screen.getByText("findOpponent"));

    // Wait for matched phase and start
    await waitFor(() => {
      expect(screen.getByText("startChallenge")).toBeInTheDocument();
    }, { timeout: 3000 });
    await user.click(screen.getByText("startChallenge"));

    // Should be in in_progress phase
    await waitFor(() => {
      expect(screen.getByText("challengeInProgress")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(screen.getByText("Opponent Quit Detection")).toBeInTheDocument();

    // in_progress polling should detect opponent quit and transition to result
    await waitFor(() => {
      expect(screen.getByText("victory")).toBeInTheDocument();
    }, { timeout: 10000 });
  });

  // 12. in_progress polling: transient errors are tolerated
  it("continues polling on transient errors during in_progress phase", { timeout: 15000 }, async () => {
    const sessionId = "ip2";
    let detailCallCount = 0;

    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: null, message: "ok" }),
      ),
      http.post("*/api/v1/challenge/queue", () =>
        HttpResponse.json({
          success: true,
          data: { matched: true, session_id: sessionId, status: "matched" },
          message: "ok",
        }),
      ),
      http.post("*/api/v1/challenge/start", () =>
        HttpResponse.json({
          success: true,
          data: {
            session_id: sessionId,
            problem: { contest_id: 500, index: "E", name: "Transient Error Test", rating: 1100, tags: [], url: "https://codeforces.com/500/E" },
            status: "problem_revealed",
          },
          message: "ok",
        }),
      ),
      http.get("*/api/v1/challenge/ip2", () => {
        detailCallCount++;
        if (detailCallCount === 1) {
          // Initial detail fetch
          return HttpResponse.json({
            success: true,
            data: {
              id: sessionId,
              status: "active",
              problem: { contest_id: 500, index: "E", name: "Transient Error Test", rating: 1100, tags: [], url: "https://codeforces.com/500/E" },
              result: null,
              is_challenger: true,
              created_at: new Date().toISOString(),
            },
            message: "ok",
          });
        }
        if (detailCallCount === 2) {
          // Transient error on first poll
          return HttpResponse.json(
            { success: false, error: { code: "INTERNAL", message: "Server error" } },
            { status: 500 },
          );
        }
        // Subsequent polls: session completed
        return HttpResponse.json({
          success: true,
          data: {
            id: sessionId,
            status: "completed",
            result: "loss",
            problem: { contest_id: 500, index: "E", name: "Transient Error Test", rating: 1100, tags: [], url: "https://codeforces.com/500/E" },
            is_challenger: true,
            elo_change: -8,
            tokens_earned: null,
            created_at: new Date().toISOString(),
            completed_at: new Date().toISOString(),
          },
          message: "ok",
        });
      }),
    );

    renderWithRoutes();
    const user = userEvent.setup();

    await waitFor(() => {
      expect(screen.getByText("findOpponent")).toBeInTheDocument();
    });
    await user.click(screen.getByText("findOpponent"));

    await waitFor(() => {
      expect(screen.getByText("startChallenge")).toBeInTheDocument();
    }, { timeout: 3000 });
    await user.click(screen.getByText("startChallenge"));

    await waitFor(() => {
      expect(screen.getByText("challengeInProgress")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Should survive transient error and eventually show result
    await waitFor(() => {
      expect(screen.getByText("defeat")).toBeInTheDocument();
    }, { timeout: 10000 });
  });

  // --- COMPLETED SESSION RESUME VIA /challenge/active (Bug 28.2) ---

  // 13. Resumes completed challenge when navigating back to /challenge
  it("resumes completed challenge when /challenge/active returns completed session", async () => {
    const completedInfo = {
      id: "cs1",
      problem_id: "p5",
      problem_name: "Completed Resume",
      problem_rating: 1700,
      created_at: new Date(Date.now() - 300000).toISOString(),
      is_challenger: true,
      opponent_username: "opponent",
      opponent_elo: 1600,
      status: "completed",
    };

    const challengeDetail = {
      id: "cs1",
      challenger_id: "u1",
      opponent_id: "u2",
      problem_id: "p5",
      problem_rating: 1700,
      problem: { contest_id: 600, index: "F", name: "Completed Resume", rating: 1700, tags: ["graphs"], url: "https://codeforces.com/600/F" },
      challenger_solved: true,
      opponent_solved: false,
      challenger_submissions: 1,
      opponent_submissions: 2,
      challenger_time: 200,
      opponent_time: 400,
      status: "completed",
      result: "win",
      is_challenger: true,
      elo_change: 18,
      tokens_earned: 35,
      opponent_tokens_earned: 0,
      created_at: new Date(Date.now() - 300000).toISOString(),
      completed_at: new Date().toISOString(),
    };

    server.use(
      http.get("*/api/v1/challenge/active", () =>
        HttpResponse.json({ success: true, data: completedInfo, message: "ok" }),
      ),
      http.get("*/api/v1/challenge/cs1", () =>
        HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
      ),
    );

    renderWithRoutes();

    // Should show the result of the completed challenge
    await waitFor(() => {
      expect(screen.getByText("victory")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(screen.getByText("Completed Resume")).toBeInTheDocument();
    expect(screen.getByText("1700")).toBeInTheDocument();
  });
});
