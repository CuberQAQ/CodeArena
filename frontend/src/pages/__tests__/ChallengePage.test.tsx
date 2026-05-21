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

  // --- SUBMIT FIRST (settled=false) -- Bug 28.4 fix verification ---

  // 14. Submitting first (settled=false) does NOT show Defeat -- stays in in_progress with waiting UI
  it("shows waiting UI instead of result when player submits first (settled=false)", { timeout: 15000 }, async () => {
    const sessionId = "sf1";
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
            problem: { contest_id: 700, index: "G", name: "First Submit Test", rating: 1200, tags: ["math"], url: "https://codeforces.com/700/G" },
            status: "problem_revealed",
          },
          message: "ok",
        }),
      ),
      // Submit returns settled=false (opponent hasn't submitted yet)
      http.post("*/api/v1/challenge/sf1/submit", () =>
        HttpResponse.json({
          success: true,
          data: {
            session_id: sessionId,
            solved: true,
            status: "active",
            settled: false,
            result: null,
            elo_change: null,
            tokens_earned: null,
            achievements: [],
          },
          message: "ok",
        }),
      ),
      // Detail: always returns active (no completion yet)
      http.get("*/api/v1/challenge/sf1", () => {
        detailCallCount++;
        if (detailCallCount === 1) {
          // Initial detail fetch after start
          return HttpResponse.json({
            success: true,
            data: {
              id: sessionId,
              status: "active",
              problem: { contest_id: 700, index: "G", name: "First Submit Test", rating: 1200, tags: ["math"], url: "https://codeforces.com/700/G" },
              result: null,
              is_challenger: true,
              elo_change: null,
              tokens_earned: null,
              created_at: new Date().toISOString(),
            },
            message: "ok",
          });
        }
        // All subsequent polls: still active (opponent hasn't submitted)
        return HttpResponse.json({
          success: true,
          data: {
            id: sessionId,
            status: "active",
            problem: { contest_id: 700, index: "G", name: "First Submit Test", rating: 1200, tags: ["math"], url: "https://codeforces.com/700/G" },
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

    // Join queue -> matched immediately
    await waitFor(() => {
      expect(screen.getByText("findOpponent")).toBeInTheDocument();
    });
    await user.click(screen.getByText("findOpponent"));

    await waitFor(() => {
      expect(screen.getByText("startChallenge")).toBeInTheDocument();
    }, { timeout: 3000 });
    await user.click(screen.getByText("startChallenge"));

    // Should be in in_progress phase
    await waitFor(() => {
      expect(screen.getByText("challengeInProgress")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Click "Yes" (solved) and submit
    await user.click(screen.getByText("common:yes"));
    await user.click(screen.getByText("submitResult"));

    // After submitting with settled=false:
    // - Should show waiting UI (waitingForOpponentResult key)
    // - Should NOT show result phase (no victory/defeat/draw)
    await waitFor(() => {
      expect(screen.getByText("waitingForOpponentResult")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Confirm result phase elements are NOT present
    expect(screen.queryByText("defeat")).not.toBeInTheDocument();
    expect(screen.queryByText("victory")).not.toBeInTheDocument();
    expect(screen.queryByText("draw")).not.toBeInTheDocument();
    expect(screen.queryByText("newChallenge")).not.toBeInTheDocument();

    // Loader2 spinner should be visible (within the waiting card)
    const spinners = document.querySelectorAll(".animate-spin");
    expect(spinners.length).toBeGreaterThanOrEqual(1);

    // Problem info should still be visible
    expect(screen.getByText("First Submit Test")).toBeInTheDocument();
  });

  // 15. Submit first (settled=false), then poll detects completion -> shows result
  it("transitions to result after submit-first polling detects opponent completed", { timeout: 20000 }, async () => {
    const sessionId = "sf2";
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
            problem: { contest_id: 800, index: "H", name: "Poll Completion Test", rating: 1300, tags: [], url: "https://codeforces.com/800/H" },
            status: "problem_revealed",
          },
          message: "ok",
        }),
      ),
      http.post("*/api/v1/challenge/sf2/submit", () =>
        HttpResponse.json({
          success: true,
          data: {
            session_id: sessionId,
            solved: true,
            status: "active",
            settled: false,
            result: null,
            elo_change: null,
            tokens_earned: null,
            achievements: [],
          },
          message: "ok",
        }),
      ),
      http.get("*/api/v1/challenge/sf2", () => {
        detailCallCount++;
        if (detailCallCount <= 2) {
          // First call: initial detail; second: still active
          return HttpResponse.json({
            success: true,
            data: {
              id: sessionId,
              status: "active",
              problem: { contest_id: 800, index: "H", name: "Poll Completion Test", rating: 1300, tags: [], url: "https://codeforces.com/800/H" },
              result: null,
              is_challenger: true,
              elo_change: null,
              tokens_earned: null,
              created_at: new Date().toISOString(),
            },
            message: "ok",
          });
        }
        // Subsequent calls: opponent submitted, settled
        return HttpResponse.json({
          success: true,
          data: {
            id: sessionId,
            status: "completed",
            result: "win",
            problem: { contest_id: 800, index: "H", name: "Poll Completion Test", rating: 1300, tags: [], url: "https://codeforces.com/800/H" },
            is_challenger: true,
            elo_change: 20,
            tokens_earned: 30,
            created_at: new Date(Date.now() - 300000).toISOString(),
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

    // Submit result
    await user.click(screen.getByText("common:yes"));
    await user.click(screen.getByText("submitResult"));

    // First: should show waiting UI
    await waitFor(() => {
      expect(screen.getByText("waitingForOpponentResult")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Then: polling should detect completion and transition to result
    await waitFor(() => {
      expect(screen.getByText("victory")).toBeInTheDocument();
    }, { timeout: 10000 });
  });

  // 16. settled=true path still works (both submit simultaneously)
  it("shows result immediately when both players submit simultaneously (settled=true)", { timeout: 15000 }, async () => {
    const sessionId = "st1";

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
            problem: { contest_id: 900, index: "I", name: "Simultaneous Submit", rating: 1000, tags: ["implementation"], url: "https://codeforces.com/900/I" },
            status: "problem_revealed",
          },
          message: "ok",
        }),
      ),
      http.post("*/api/v1/challenge/st1/submit", () =>
        HttpResponse.json({
          success: true,
          data: {
            session_id: sessionId,
            solved: true,
            status: "completed",
            settled: true,
            result: "win",
            elo_change: 15,
            tokens_earned: 25,
            achievements: [],
          },
          message: "ok",
        }),
      ),
      http.get("*/api/v1/challenge/st1", () =>
        HttpResponse.json({
          success: true,
          data: {
            id: sessionId,
            status: "completed",
            result: "win",
            problem: { contest_id: 900, index: "I", name: "Simultaneous Submit", rating: 1000, tags: ["implementation"], url: "https://codeforces.com/900/I" },
            is_challenger: true,
            elo_change: 15,
            tokens_earned: 25,
            created_at: new Date(Date.now() - 300000).toISOString(),
            completed_at: new Date().toISOString(),
          },
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
      expect(screen.getByText("challengeInProgress")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Submit result
    await user.click(screen.getByText("common:yes"));
    await user.click(screen.getByText("submitResult"));

    // Should immediately go to result (settled=true), NOT show waiting UI
    await waitFor(() => {
      expect(screen.getByText("victory")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Waiting UI should NOT appear
    expect(screen.queryByText("waitingForOpponentResult")).not.toBeInTheDocument();
  });

  // 17. New Challenge resets hasSubmitted state
  it("resets hasSubmitted and returns to idle on New Challenge click", { timeout: 15000 }, async () => {
    const sessionId = "nr1";

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
            problem: { contest_id: 1000, index: "J", name: "Reset Test", rating: 1100, tags: [], url: "https://codeforces.com/1000/J" },
            status: "problem_revealed",
          },
          message: "ok",
        }),
      ),
      http.post("*/api/v1/challenge/nr1/submit", () =>
        HttpResponse.json({
          success: true,
          data: {
            session_id: sessionId,
            solved: true,
            status: "active",
            settled: false,
            result: null,
            elo_change: null,
            tokens_earned: null,
            achievements: [],
          },
          message: "ok",
        }),
      ),
      // Complete immediately on detail to speed up test
      http.get("*/api/v1/challenge/nr1", () =>
        HttpResponse.json({
          success: true,
          data: {
            id: sessionId,
            status: "completed",
            result: "win",
            problem: { contest_id: 1000, index: "J", name: "Reset Test", rating: 1100, tags: [], url: "https://codeforces.com/1000/J" },
            is_challenger: true,
            elo_change: 10,
            tokens_earned: 15,
            created_at: new Date(Date.now() - 300000).toISOString(),
            completed_at: new Date().toISOString(),
          },
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
      expect(screen.getByText("challengeInProgress")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Submit (settled=false)
    await user.click(screen.getByText("common:yes"));
    await user.click(screen.getByText("submitResult"));

    // Wait for waiting UI then completion
    await waitFor(() => {
      expect(screen.getByText("victory")).toBeInTheDocument();
    }, { timeout: 10000 });

    // Click "New Challenge" to reset
    await user.click(screen.getByText("newChallenge"));

    // Should be back to idle
    await waitFor(() => {
      expect(screen.getByText("findOpponent")).toBeInTheDocument();
    }, { timeout: 3000 });
    expect(screen.queryByText("waitingForOpponentResult")).not.toBeInTheDocument();
    expect(screen.queryByText("victory")).not.toBeInTheDocument();
  });

  // =========================================================================
  // RESULT PHASE — Elo, tokens, achievements, settlement, opponent quit
  // =========================================================================

  describe("result phase display", () => {
    // 18. Elo change value rendered correctly in result
    it("displays the correct Elo change value from challenge detail", async () => {
      const challengeDetail = {
        id: "elo-test-1",
        challenger_id: "u1",
        opponent_id: "u2",
        problem_id: "p1",
        problem_rating: 1500,
        problem: { contest_id: 100, index: "A", name: "Elo Test", rating: 1500, tags: [], url: "https://codeforces.com/100/A" },
        challenger_solved: true,
        opponent_solved: false,
        challenger_submissions: 1,
        opponent_submissions: 2,
        challenger_time: 300,
        opponent_time: 500,
        status: "completed",
        result: "win",
        is_challenger: true,
        elo_change: 23,
        tokens_earned: 30,
        opponent_tokens_earned: 0,
        created_at: new Date(Date.now() - 600000).toISOString(),
        completed_at: new Date().toISOString(),
      };

      server.use(
        http.get("*/api/v1/challenge/elo-test-1", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
      );

      renderWithRoutes("/challenge/elo-test-1");

      await waitFor(() => {
        expect(screen.getByText("victory")).toBeInTheDocument();
      }, { timeout: 3000 });

      // The EloChange mock renders the value in a div with data-testid="elo-change"
      expect(screen.getByTestId("elo-change")).toHaveTextContent("23");
    });

    // 19. Defeat result shows defeat UI with negative Elo
    it("displays defeat UI with negative Elo change", async () => {
      const challengeDetail = {
        id: "defeat-test",
        challenger_id: "u1",
        opponent_id: "u2",
        problem_id: "p1",
        problem_rating: 1600,
        problem: { contest_id: 200, index: "B", name: "Defeat Problem", rating: 1600, tags: ["greedy"], url: "https://codeforces.com/200/B" },
        challenger_solved: false,
        opponent_solved: true,
        challenger_submissions: 3,
        opponent_submissions: 1,
        challenger_time: 600,
        opponent_time: 200,
        status: "completed",
        result: "loss",
        is_challenger: true,
        elo_change: -15,
        tokens_earned: 0,
        opponent_tokens_earned: 25,
        created_at: new Date(Date.now() - 900000).toISOString(),
        completed_at: new Date().toISOString(),
      };

      server.use(
        http.get("*/api/v1/challenge/defeat-test", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
      );

      renderWithRoutes("/challenge/defeat-test");

      await waitFor(() => {
        expect(screen.getByText("defeat")).toBeInTheDocument();
      }, { timeout: 3000 });

      // Defeat should show Swords icon (not Trophy or X)
      expect(screen.queryByText("victory")).not.toBeInTheDocument();
      expect(screen.queryByText("challengeAbandoned")).not.toBeInTheDocument();

      // Negative Elo should be rendered
      expect(screen.getByTestId("elo-change")).toHaveTextContent("-15");
    });

    // 20. Tokens earned display
    it("displays tokens earned in result when tokens_earned > 0", async () => {
      const challengeDetail = {
        id: "tokens-test",
        challenger_id: "u1",
        opponent_id: "u2",
        problem_id: "p1",
        problem_rating: 1300,
        problem: { contest_id: 300, index: "C", name: "Tokens Test", rating: 1300, tags: [], url: "https://codeforces.com/300/C" },
        challenger_solved: true,
        opponent_solved: false,
        challenger_submissions: 2,
        opponent_submissions: 3,
        challenger_time: 250,
        opponent_time: 400,
        status: "completed",
        result: "win",
        is_challenger: true,
        elo_change: 10,
        tokens_earned: 42,
        opponent_tokens_earned: 0,
        created_at: new Date(Date.now() - 500000).toISOString(),
        completed_at: new Date().toISOString(),
      };

      server.use(
        http.get("*/api/v1/challenge/tokens-test", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
      );

      renderWithRoutes("/challenge/tokens-test");

      await waitFor(() => {
        expect(screen.getByText("victory")).toBeInTheDocument();
      }, { timeout: 3000 });

      // tokens_earned display: shows "tokensEarned" label and "+42"
      expect(screen.getByText("tokensEarned")).toBeInTheDocument();
      expect(screen.getByText("+42")).toBeInTheDocument();
    });

    // 21. No tokens display when tokens_earned is 0 or null
    it("does not display tokens section when tokens_earned is 0", async () => {
      const challengeDetail = {
        id: "no-tokens-test",
        challenger_id: "u1",
        opponent_id: "u2",
        problem_id: "p1",
        problem_rating: 1200,
        problem: { contest_id: 400, index: "D", name: "No Tokens", rating: 1200, tags: [], url: "https://codeforces.com/400/D" },
        challenger_solved: true,
        opponent_solved: true,
        challenger_submissions: 1,
        opponent_submissions: 1,
        challenger_time: 200,
        opponent_time: 180,
        status: "completed",
        result: "draw",
        is_challenger: true,
        elo_change: 0,
        tokens_earned: 0,
        opponent_tokens_earned: 0,
        created_at: new Date(Date.now() - 500000).toISOString(),
        completed_at: new Date().toISOString(),
      };

      server.use(
        http.get("*/api/v1/challenge/no-tokens-test", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
      );

      renderWithRoutes("/challenge/no-tokens-test");

      await waitFor(() => {
        expect(screen.getByText("draw")).toBeInTheDocument();
      }, { timeout: 3000 });

      // tokensEarned section should NOT appear when tokens_earned is 0
      expect(screen.queryByText("tokensEarned")).not.toBeInTheDocument();
    });

    // 22. No tokens display when tokens_earned is null
    it("does not display tokens section when tokens_earned is null", async () => {
      const challengeDetail = {
        id: "null-tokens-test",
        challenger_id: "u1",
        opponent_id: "u2",
        problem_id: "p1",
        problem_rating: 1200,
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
        created_at: new Date(Date.now() - 300000).toISOString(),
        completed_at: new Date().toISOString(),
      };

      server.use(
        http.get("*/api/v1/challenge/null-tokens-test", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
      );

      renderWithRoutes("/challenge/null-tokens-test");

      await waitFor(() => {
        expect(screen.getByText("challengeAbandoned")).toBeInTheDocument();
      }, { timeout: 3000 });

      expect(screen.queryByText("tokensEarned")).not.toBeInTheDocument();
    });

    // 23. Settlement loading state when result is null but phase is result
    it("shows settling spinner when result data is not yet available", async () => {
      // Use status="completed" but result=null to trigger settling UI
      // The resume logic checks `data.status === "completed" || data.result`
      const challengeDetail = {
        id: "settling-test",
        challenger_id: "u1",
        opponent_id: "u2",
        problem_id: "p1",
        problem_rating: 1200,
        problem: null,
        challenger_solved: false,
        opponent_solved: false,
        challenger_submissions: 0,
        opponent_submissions: 0,
        challenger_time: null,
        opponent_time: null,
        status: "completed",
        result: null,
        is_challenger: true,
        elo_change: null,
        tokens_earned: null,
        opponent_tokens_earned: null,
        created_at: new Date(Date.now() - 300000).toISOString(),
        completed_at: null,
      };

      server.use(
        http.get("*/api/v1/challenge/settling-test", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
      );

      renderWithRoutes("/challenge/settling-test");

      await waitFor(() => {
        expect(screen.getByText("settling")).toBeInTheDocument();
      }, { timeout: 3000 });
      expect(screen.getByText("settlingDesc")).toBeInTheDocument();
    });

    // 24. Achievement popup triggers when submit response includes achievements
    it("shows achievement popup when submit returns achievements with settled=true win", { timeout: 15000 }, async () => {
      const sessionId = "ach-test";
      const achievement = { type: "first_win", title: "First Victory", description: "Won your first challenge", icon: "trophy" };

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
              problem: { contest_id: 500, index: "E", name: "Achievement Test", rating: 1400, tags: ["dp"], url: "https://codeforces.com/500/E" },
              status: "problem_revealed",
            },
            message: "ok",
          }),
        ),
        http.post("*/api/v1/challenge/ach-test/submit", () =>
          HttpResponse.json({
            success: true,
            data: {
              session_id: sessionId,
              solved: true,
              status: "completed",
              settled: true,
              result: "win",
              elo_change: 20,
              tokens_earned: 30,
              achievements: [achievement],
            },
            message: "ok",
          }),
        ),
        http.get("*/api/v1/challenge/ach-test", () =>
          HttpResponse.json({
            success: true,
            data: {
              id: sessionId,
              status: "completed",
              result: "win",
              problem: { contest_id: 500, index: "E", name: "Achievement Test", rating: 1400, tags: ["dp"], url: "https://codeforces.com/500/E" },
              is_challenger: true,
              elo_change: 20,
              tokens_earned: 30,
              created_at: new Date(Date.now() - 300000).toISOString(),
              completed_at: new Date().toISOString(),
            },
            message: "ok",
          }),
        ),
      );

      renderWithRoutes();
      const user = userEvent.setup();

      await waitFor(() => expect(screen.getByText("findOpponent")).toBeInTheDocument());
      await user.click(screen.getByText("findOpponent"));
      await waitFor(() => expect(screen.getByText("startChallenge")).toBeInTheDocument(), { timeout: 3000 });
      await user.click(screen.getByText("startChallenge"));
      await waitFor(() => expect(screen.getByText("challengeInProgress")).toBeInTheDocument(), { timeout: 3000 });

      await user.click(screen.getByText("common:yes"));
      await user.click(screen.getByText("submitResult"));

      // Should go to result with victory
      await waitFor(() => expect(screen.getByText("victory")).toBeInTheDocument(), { timeout: 3000 });

      // Achievement popup should show (after 1500ms delay, but mock renders immediately when state is set)
      // The AchievementPopup mock renders when showAchievements=true
      // Since achievements are set from submit response, after 1500ms timeout showAchievements becomes true
      await waitFor(() => {
        expect(screen.getByTestId("achievement-popup")).toBeInTheDocument();
      }, { timeout: 5000 });
    });

    // 25. Celebration triggers when elo_change > 0 and result is win (settled path)
    it("triggers celebration animation when winning with positive Elo", { timeout: 15000 }, async () => {
      const sessionId = "celeb-test";

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
              problem: { contest_id: 600, index: "F", name: "Celeb Test", rating: 1100, tags: [], url: "https://codeforces.com/600/F" },
              status: "problem_revealed",
            },
            message: "ok",
          }),
        ),
        http.post("*/api/v1/challenge/celeb-test/submit", () =>
          HttpResponse.json({
            success: true,
            data: {
              session_id: sessionId,
              solved: true,
              status: "completed",
              settled: true,
              result: "win",
              elo_change: 25,
              tokens_earned: 35,
              achievements: [],
            },
            message: "ok",
          }),
        ),
        http.get("*/api/v1/challenge/celeb-test", () =>
          HttpResponse.json({
            success: true,
            data: {
              id: sessionId,
              status: "completed",
              result: "win",
              problem: { contest_id: 600, index: "F", name: "Celeb Test", rating: 1100, tags: [], url: "https://codeforces.com/600/F" },
              is_challenger: true,
              elo_change: 25,
              tokens_earned: 35,
              created_at: new Date(Date.now() - 300000).toISOString(),
              completed_at: new Date().toISOString(),
            },
            message: "ok",
          }),
        ),
      );

      renderWithRoutes();
      const user = userEvent.setup();

      await waitFor(() => expect(screen.getByText("findOpponent")).toBeInTheDocument());
      await user.click(screen.getByText("findOpponent"));
      await waitFor(() => expect(screen.getByText("startChallenge")).toBeInTheDocument(), { timeout: 3000 });
      await user.click(screen.getByText("startChallenge"));
      await waitFor(() => expect(screen.getByText("challengeInProgress")).toBeInTheDocument(), { timeout: 3000 });

      await user.click(screen.getByText("common:yes"));
      await user.click(screen.getByText("submitResult"));

      await waitFor(() => expect(screen.getByText("victory")).toBeInTheDocument(), { timeout: 3000 });

      // The AcceptedCelebration mock renders data-testid="celebration" when active=true
      expect(screen.getByTestId("celebration")).toBeInTheDocument();
    });

    // 26. No celebration on loss (elo_change <= 0 or result != win)
    it("does not trigger celebration on defeat", { timeout: 15000 }, async () => {
      const sessionId = "no-celeb";

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
              problem: { contest_id: 700, index: "G", name: "No Celeb", rating: 1200, tags: [], url: "https://codeforces.com/700/G" },
              status: "problem_revealed",
            },
            message: "ok",
          }),
        ),
        http.post("*/api/v1/challenge/no-celeb/submit", () =>
          HttpResponse.json({
            success: true,
            data: {
              session_id: sessionId,
              solved: false,
              status: "completed",
              settled: true,
              result: "loss",
              elo_change: -12,
              tokens_earned: null,
              achievements: [],
            },
            message: "ok",
          }),
        ),
        http.get("*/api/v1/challenge/no-celeb", () =>
          HttpResponse.json({
            success: true,
            data: {
              id: sessionId,
              status: "completed",
              result: "loss",
              problem: { contest_id: 700, index: "G", name: "No Celeb", rating: 1200, tags: [], url: "https://codeforces.com/700/G" },
              is_challenger: true,
              elo_change: -12,
              tokens_earned: null,
              created_at: new Date(Date.now() - 300000).toISOString(),
              completed_at: new Date().toISOString(),
            },
            message: "ok",
          }),
        ),
      );

      renderWithRoutes();
      const user = userEvent.setup();

      await waitFor(() => expect(screen.getByText("findOpponent")).toBeInTheDocument());
      await user.click(screen.getByText("findOpponent"));
      await waitFor(() => expect(screen.getByText("startChallenge")).toBeInTheDocument(), { timeout: 3000 });
      await user.click(screen.getByText("startChallenge"));
      await waitFor(() => expect(screen.getByText("challengeInProgress")).toBeInTheDocument(), { timeout: 3000 });

      await user.click(screen.getByText("common:no"));
      await user.click(screen.getByText("submitResult"));

      await waitFor(() => expect(screen.getByText("defeat")).toBeInTheDocument(), { timeout: 3000 });

      // No celebration
      expect(screen.queryByTestId("celebration")).not.toBeInTheDocument();
    });

    // 27. Opponent quit during in_progress shows win with opponent_quit semantics
    it("handles opponent quit result as win result with correct UI", async () => {
      const challengeDetail = {
        id: "opp-quit",
        challenger_id: "u1",
        opponent_id: "u2",
        problem_id: "p1",
        problem_rating: 1500,
        problem: { contest_id: 800, index: "H", name: "Opp Quit Problem", rating: 1500, tags: ["math"], url: "https://codeforces.com/800/H" },
        challenger_solved: false,
        opponent_solved: false,
        challenger_submissions: 0,
        opponent_submissions: 0,
        challenger_time: 120,
        opponent_time: null,
        status: "completed",
        result: "win",
        is_challenger: true,
        elo_change: 8,
        tokens_earned: 10,
        opponent_tokens_earned: 0,
        created_at: new Date(Date.now() - 300000).toISOString(),
        completed_at: new Date().toISOString(),
      };

      server.use(
        http.get("*/api/v1/challenge/opp-quit", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
      );

      renderWithRoutes("/challenge/opp-quit");

      await waitFor(() => {
        expect(screen.getByText("victory")).toBeInTheDocument();
      }, { timeout: 3000 });

      // When result is "win", the UI shows victory with Trophy icon
      expect(screen.getByTestId("elo-change")).toHaveTextContent("8");
      expect(screen.getByText("+10")).toBeInTheDocument(); // tokens earned
    });

    // 28. Challenger time displayed correctly when is_challenger=true
    it("displays challenger time when user is challenger", async () => {
      // formatTime(300) = "5:00"
      const challengeDetail = {
        id: "time-test",
        challenger_id: "u1",
        opponent_id: "u2",
        problem_id: "p1",
        problem_rating: 1500,
        problem: { contest_id: 900, index: "I", name: "Time Test", rating: 1500, tags: [], url: "https://codeforces.com/900/I" },
        challenger_solved: true,
        opponent_solved: false,
        challenger_submissions: 2,
        opponent_submissions: 3,
        challenger_time: 300,
        opponent_time: 500,
        status: "completed",
        result: "win",
        is_challenger: true,
        elo_change: 15,
        tokens_earned: 20,
        opponent_tokens_earned: 0,
        created_at: new Date(Date.now() - 600000).toISOString(),
        completed_at: new Date().toISOString(),
      };

      server.use(
        http.get("*/api/v1/challenge/time-test", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
      );

      renderWithRoutes("/challenge/time-test");

      await waitFor(() => {
        expect(screen.getByText("victory")).toBeInTheDocument();
      }, { timeout: 3000 });

      // The "yourTime" stat should show formatted challenger_time (300s = 05:00)
      // Real formatTime: `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}` => "05:00"
      expect(screen.getByText("05:00")).toBeInTheDocument();
    });

    // 29. Opponent time displayed when is_challenger=false
    it("displays opponent time when user is not challenger", async () => {
      const challengeDetail = {
        id: "opp-time-test",
        challenger_id: "u2",
        opponent_id: "u1",
        problem_id: "p1",
        problem_rating: 1400,
        problem: { contest_id: 950, index: "J", name: "Opp Time Test", rating: 1400, tags: [], url: "https://codeforces.com/950/J" },
        challenger_solved: false,
        opponent_solved: true,
        challenger_submissions: 3,
        opponent_submissions: 1,
        challenger_time: 500,
        opponent_time: 250,
        status: "completed",
        result: "win",
        is_challenger: false,
        elo_change: 18,
        tokens_earned: 25,
        opponent_tokens_earned: 0,
        created_at: new Date(Date.now() - 600000).toISOString(),
        completed_at: new Date().toISOString(),
      };

      server.use(
        http.get("*/api/v1/challenge/opp-time-test", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
      );

      renderWithRoutes("/challenge/opp-time-test");

      await waitFor(() => {
        expect(screen.getByText("victory")).toBeInTheDocument();
      }, { timeout: 3000 });

      // When is_challenger=false, "yourTime" should show opponent_time (250s = 04:10)
      expect(screen.getByText("04:10")).toBeInTheDocument();
    });

    // 30. Quit challenge flow shows correct result
    it("shows abandoned result when player quits during in_progress", { timeout: 15000 }, async () => {
      const sessionId = "quit-flow-test";

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
              problem: { contest_id: 1000, index: "K", name: "Quit Flow Test", rating: 1300, tags: [], url: "https://codeforces.com/1000/K" },
              status: "problem_revealed",
            },
            message: "ok",
          }),
        ),
        http.post("*/api/v1/challenge/quit-flow-test/quit", () =>
          HttpResponse.json({
            success: true,
            data: { session_id: sessionId, status: "quit", elo_change: -10, penalty: 5 },
            message: "ok",
          }),
        ),
        http.get("*/api/v1/challenge/quit-flow-test", () => {
          return HttpResponse.json({
            success: true,
            data: {
              id: sessionId,
              status: "quit",
              result: "quit",
              problem: { contest_id: 1000, index: "K", name: "Quit Flow Test", rating: 1300, tags: [], url: "https://codeforces.com/1000/K" },
              is_challenger: true,
              elo_change: -10,
              tokens_earned: null,
              created_at: new Date(Date.now() - 300000).toISOString(),
              completed_at: new Date().toISOString(),
            },
            message: "ok",
          });
        }),
      );

      renderWithRoutes();
      const user = userEvent.setup();

      await waitFor(() => expect(screen.getByText("findOpponent")).toBeInTheDocument());
      await user.click(screen.getByText("findOpponent"));
      await waitFor(() => expect(screen.getByText("startChallenge")).toBeInTheDocument(), { timeout: 3000 });
      await user.click(screen.getByText("startChallenge"));
      await waitFor(() => expect(screen.getByText("challengeInProgress")).toBeInTheDocument(), { timeout: 3000 });

      // Click quit
      await user.click(screen.getByText("quit"));

      await waitFor(() => {
        expect(screen.getByText("challengeAbandoned")).toBeInTheDocument();
      }, { timeout: 3000 });

      // Negative Elo from quit
      expect(screen.getByTestId("elo-change")).toHaveTextContent("-10");
      // No tokens for quit
      expect(screen.queryByText("tokensEarned")).not.toBeInTheDocument();
      // No celebration for quit
      expect(screen.queryByTestId("celebration")).not.toBeInTheDocument();
    });

    // 31. Reset from result phase navigates to clean URL
    it("navigates to /challenge on reset from result phase with sessionId in URL", async () => {
      const challengeDetail = {
        id: "reset-url-test",
        challenger_id: "u1",
        opponent_id: "u2",
        problem_id: "p1",
        problem_rating: 1200,
        problem: { contest_id: 100, index: "A", name: "Reset URL", rating: 1200, tags: [], url: "https://codeforces.com/100/A" },
        challenger_solved: true,
        opponent_solved: false,
        challenger_submissions: 1,
        opponent_submissions: 2,
        challenger_time: 200,
        opponent_time: 300,
        status: "completed",
        result: "win",
        is_challenger: true,
        elo_change: 10,
        tokens_earned: 15,
        opponent_tokens_earned: 0,
        created_at: new Date(Date.now() - 300000).toISOString(),
        completed_at: new Date().toISOString(),
      };

      server.use(
        http.get("*/api/v1/challenge/reset-url-test", () =>
          HttpResponse.json({ success: true, data: challengeDetail, message: "ok" }),
        ),
        http.get("*/api/v1/challenge/active", () =>
          HttpResponse.json({ success: true, data: null, message: "ok" }),
        ),
      );

      const { container } = renderWithRoutes("/challenge/reset-url-test");

      await waitFor(() => {
        expect(screen.getByText("victory")).toBeInTheDocument();
      }, { timeout: 3000 });

      const user = userEvent.setup();
      await user.click(screen.getByText("newChallenge"));

      // After reset, should show idle phase
      await waitFor(() => {
        expect(screen.getByText("findOpponent")).toBeInTheDocument();
      }, { timeout: 3000 });
    });
  });
});
