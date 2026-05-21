import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

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
    span: ({ children, ...props }: React.PropsWithChildren<Record<string, unknown>>) => (
      <span {...props}>{children}</span>
    ),
  },
  AnimatePresence: ({ children }: React.PropsWithChildren) => <>{children}</>,
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

vi.mock("@/components/SolvingTimeline", () => ({
  SolvingTimeline: () => <div data-testid="solving-timeline" />,
}));

vi.mock("@/components/ProblemViewer", () => ({
  ProblemViewer: ({ contestId, index }: { contestId: string; index: string }) => (
    <div data-testid="problem-viewer">{contestId}{index}</div>
  ),
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

// PvE Challenge Store mock with controllable state
let mockPvEPhase: "idle" | "loading" | "in_progress" | "result" = "idle";
let mockPvEError = "";
let mockStartResponse: unknown = null;
let mockChallenge: unknown = null;
let mockSubmitResult: unknown = null;
let mockQuitResult: unknown = null;

const mockStartChallenge = vi.fn();
const mockQuitChallengeAction = vi.fn();
const mockReset = vi.fn();
const mockFetchChallenge = vi.fn();

vi.mock("@/stores/pveChallengeStore", () => ({
  usePvEChallengeStore: vi.fn((selector: (s: Record<string, unknown>) => unknown) =>
    selector({
      phase: mockPvEPhase,
      error: mockPvEError,
      sessionId: "pve1",
      startResponse: mockStartResponse,
      challenge: mockChallenge,
      submitResult: mockSubmitResult,
      quitResult: mockQuitResult,
      startChallenge: mockStartChallenge,
      quitChallengeAction: mockQuitChallengeAction,
      reset: mockReset,
      fetchChallenge: mockFetchChallenge,
    }),
  ),
}));

vi.mock("@/services/pveChallengeApi", () => ({
  getChallenge: vi.fn().mockResolvedValue({}),
}));

vi.mock("@/services/api", () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: { data: { status: "pending" } } }),
  },
}));

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import PvEChallengePage from "../challenge/PvEChallengePage";

function renderPage() {
  return render(
    <MemoryRouter>
      <PvEChallengePage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PvEChallengePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPvEPhase = "idle";
    mockPvEError = "";
    mockStartResponse = null;
    mockChallenge = null;
    mockSubmitResult = null;
    mockQuitResult = null;
  });

  // 1. Idle phase renders title and start button
  it("renders idle phase with title and start button", () => {
    mockPvEPhase = "idle";
    renderPage();

    expect(screen.getByText("pve.title")).toBeInTheDocument();
    expect(screen.getByText("pve.description")).toBeInTheDocument();
    expect(screen.getByText("pve.startSoloChallenge")).toBeInTheDocument();
  });

  // 2. Shows how it works section
  it("shows how it works section", () => {
    mockPvEPhase = "idle";
    renderPage();

    expect(screen.getByText("pve.howItWorks")).toBeInTheDocument();
    expect(screen.getByText("pve.step1")).toBeInTheDocument();
    expect(screen.getByText("pve.step2")).toBeInTheDocument();
    expect(screen.getByText("pve.step3")).toBeInTheDocument();
    expect(screen.getByText("pve.step4")).toBeInTheDocument();
    expect(screen.getByText("pve.step5")).toBeInTheDocument();
  });

  // 3. Click start calls store action
  it("calls startChallenge on start button click", async () => {
    mockPvEPhase = "idle";
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("pve.startSoloChallenge"));
    expect(mockStartChallenge).toHaveBeenCalled();
  });

  // 4. Loading phase shows spinner on button
  it("shows loading state on start button when loading", () => {
    mockPvEPhase = "loading";
    renderPage();

    expect(screen.getByText("pve.loadingProblem")).toBeInTheDocument();
  });

  // 5. Error message in idle phase
  it("shows error message when present", () => {
    mockPvEPhase = "idle";
    mockPvEError = "Something went wrong";
    renderPage();

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  // 6. In-progress phase renders blind box
  it("renders in-progress phase with problem and mystery elements", () => {
    mockPvEPhase = "in_progress";
    mockStartResponse = {
      session_id: "pve1",
      problem: {
        name: "Mystery Problem",
        contest_id: "100",
        index: "A",
        rating: 1500,
        tags: ["dp", "math"],
        url: "https://codeforces.com/100/A",
      },
    };
    renderPage();

    expect(screen.getByText("Mystery Problem")).toBeInTheDocument();
    expect(screen.getAllByText("???").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("challenge:pve.quit")).toBeInTheDocument();
  });

  // 7. In-progress shows auto-tracking
  it("shows auto-tracking panel in progress phase", () => {
    mockPvEPhase = "in_progress";
    mockStartResponse = {
      session_id: "pve1",
      problem: {
        name: "Test",
        contest_id: "1",
        index: "A",
        rating: 1200,
        tags: [],
        url: "https://codeforces.com/1/A",
      },
    };
    renderPage();

    expect(screen.getByText("challenge:waitingForCFResult")).toBeInTheDocument();
  });

  // 8. Quit button calls quitChallengeAction
  it("calls quitChallengeAction on quit click", async () => {
    mockPvEPhase = "in_progress";
    mockStartResponse = {
      session_id: "pve1",
      problem: {
        name: "Test",
        contest_id: "1",
        index: "A",
        rating: 1200,
        tags: [],
        url: "https://codeforces.com/1/A",
      },
    };
    mockQuitChallengeAction.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("challenge:pve.quit"));
    expect(mockQuitChallengeAction).toHaveBeenCalledWith(0);
  });

  // 9. Result phase - solved
  it("renders result phase for solved challenge", () => {
    mockPvEPhase = "result";
    mockStartResponse = {
      session_id: "pve1",
      problem: {
        name: "Mystery Problem",
        contest_id: "100",
        index: "A",
        rating: 1500,
        tags: ["dp", "math"],
        url: "https://codeforces.com/100/A",
      },
    };
    mockSubmitResult = {
      solved: true,
      elo_change: 15,
      pp_change: 2.5,
      tokens_earned: 10,
      overkill_multiplier: 1.5,
      achievements: [],
    };
    renderPage();

    expect(screen.getByText("challenge:pve.challengeComplete")).toBeInTheDocument();
    expect(screen.getByText("1500")).toBeInTheDocument();
    expect(screen.getByText("dp")).toBeInTheDocument();
    expect(screen.getByText("math")).toBeInTheDocument();
  });

  // 10. Result phase - quit/abandoned
  it("renders result phase for quit challenge", () => {
    mockPvEPhase = "result";
    mockChallenge = { status: "quit", problem_rating: 1200, problem_tags: ["greedy"] };
    mockStartResponse = {
      session_id: "pve1",
      problem: {
        name: "Quit Problem",
        contest_id: "50",
        index: "B",
        rating: 1200,
        tags: ["greedy"],
        url: "https://codeforces.com/50/B",
      },
    };
    mockQuitResult = { elo_change: -5 };
    renderPage();

    expect(screen.getByText("challenge:pve.challengeAbandoned")).toBeInTheDocument();
  });

  // 11. Result phase - not solved
  it("renders result phase for unsolved challenge", () => {
    mockPvEPhase = "result";
    mockStartResponse = {
      session_id: "pve1",
      problem: {
        name: "Failed Problem",
        contest_id: "60",
        index: "C",
        rating: 1800,
        tags: [],
        url: "https://codeforces.com/60/C",
      },
    };
    mockSubmitResult = {
      solved: false,
      elo_change: -10,
      pp_change: 0,
      tokens_earned: 0,
      overkill_multiplier: 1.0,
      achievements: [],
    };
    renderPage();

    expect(screen.getByText("challenge:pve.notSolved")).toBeInTheDocument();
  });

  // 12. Overkill bonus indicator
  it("shows overkill bonus when multiplier > 1", () => {
    mockPvEPhase = "result";
    mockStartResponse = {
      session_id: "pve1",
      problem: {
        name: "Overkill Problem",
        contest_id: "70",
        index: "D",
        rating: 800,
        tags: [],
        url: "https://codeforces.com/70/D",
      },
    };
    mockSubmitResult = {
      solved: true,
      elo_change: 25,
      pp_change: 5.0,
      tokens_earned: 20,
      overkill_multiplier: 2.0,
      achievements: [],
    };
    renderPage();

    expect(screen.getByText("challenge:pve.overkillBonus")).toBeInTheDocument();
  });

  // 13. Result phase - new challenge button calls reset
  it("resets on new challenge button click", async () => {
    mockPvEPhase = "result";
    mockStartResponse = {
      session_id: "pve1",
      problem: {
        name: "Test",
        contest_id: "1",
        index: "A",
        rating: 1200,
        tags: [],
        url: "https://codeforces.com/1/A",
      },
    };
    mockSubmitResult = {
      solved: true,
      elo_change: 10,
      pp_change: 1.0,
      tokens_earned: 5,
      overkill_multiplier: 1.0,
      achievements: [],
    };
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("challenge:pve.newChallenge"));
    expect(mockReset).toHaveBeenCalled();
  });

  // 14. Result phase - back to dashboard
  it("navigates to dashboard on back button click", async () => {
    mockPvEPhase = "result";
    mockStartResponse = {
      session_id: "pve1",
      problem: {
        name: "Test",
        contest_id: "1",
        index: "A",
        rating: 1200,
        tags: [],
        url: "https://codeforces.com/1/A",
      },
    };
    mockSubmitResult = {
      solved: true,
      elo_change: 10,
      pp_change: 1.0,
      tokens_earned: 5,
      overkill_multiplier: 1.0,
      achievements: [],
    };
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByText("challenge:pve.backToDashboard"));
    expect(mockNavigate).toHaveBeenCalledWith("/dashboard");
  });
});
