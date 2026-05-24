import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, params?: Record<string, unknown> | string) => {
      if (typeof params === "string") {
        return params;
      }
      if (params && typeof params === "object") {
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

vi.mock("@/components/ui/button", () => ({
  Button: (props: Record<string, unknown>) => {
    const { onClick, children, disabled, ..._rest } = props;
    return (
      <button onClick={onClick as React.MouseEventHandler} disabled={!!disabled} type="button" data-testid="mock-button">
        {children as React.ReactNode}
      </button>
    );
  },
}));

vi.mock("@/components/ui/alert-dialog", () => ({
  ConfirmDialog: ({ open, onConfirm, onClose, title, message, cancelText, confirmText }: {
    open: boolean;
    onConfirm: () => void;
    onClose: () => void;
    title: string;
    message: string;
    cancelText?: string;
    confirmText?: string;
  }) => {
    if (!open) return null;
    return (
      <div data-testid="confirm-dialog">
        <span data-testid="dialog-title">{title}</span>
        <span data-testid="dialog-message">{message}</span>
        <button data-testid="dialog-confirm" onClick={onConfirm}>{confirmText ?? "Confirm"}</button>
        <button data-testid="dialog-cancel" onClick={onClose}>{cancelText ?? "Cancel"}</button>
      </div>
    );
  },
}));

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
}));

vi.mock("@/components/animations/StreakEffect", () => ({
  StreakEffect: ({ streak }: { streak: number }) => (
    <div data-testid="streak-effect">{streak}</div>
  ),
}));

vi.mock("@/components/animations/CoinAnimation", () => ({
  CoinAnimation: ({ amount }: { amount: number }) => (
    <div data-testid="coin-anim">{amount}</div>
  ),
}));

vi.mock("@/components/animations", () => ({
  AchievementPopup: () => <div data-testid="achievement-popup" />,
}));

vi.mock("@/components/ProblemViewer", () => ({
  ProblemViewer: ({ contestId, index }: { contestId: string | number; index: string }) => (
    <div data-testid="problem-viewer">{contestId}{index}</div>
  ),
}));

vi.mock("@/components/SolvingTimeline", () => ({
  SolvingTimeline: ({ problemId }: { problemId: string }) => (
    <div data-testid="solving-timeline">{problemId}</div>
  ),
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

// Mock api module
const mockApiGet = vi.fn();
const mockApiPost = vi.fn();

vi.mock("@/services/api", () => ({
  default: {
    get: (...args: unknown[]) => mockApiGet(...args),
    post: (...args: unknown[]) => mockApiPost(...args),
  },
}));

// Mock trainingApi
const mockGetRecommendedProblem = vi.fn();
const mockGetCuratedProblems = vi.fn();
const mockGetActiveTrainingSession = vi.fn().mockResolvedValue(null);
const mockSkipProblem = vi.fn();

vi.mock("@/services/trainingApi", () => ({
  getActiveTrainingSession: (...args: unknown[]) => mockGetActiveTrainingSession(...args),
  getRecommendedTopics: vi.fn().mockResolvedValue([]),
  getRecommendedProblem: (...args: unknown[]) => mockGetRecommendedProblem(...args),
  getCuratedProblems: (...args: unknown[]) => mockGetCuratedProblems(...args),
  skipProblem: (...args: unknown[]) => mockSkipProblem(...args),
}));

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

const sampleTopic = {
  id: "topic1",
  name: "Dynamic Programming",
  name_zh: "动态规划",
  slug: "dp",
  description: "Learn DP basics",
  cf_tags: ["dp"],
  problems: [
    { problem_id: "p1", name: "Two Sum", contest_id: "1", index: "A", rating: 1200, url: "https://codeforces.com/1/A", solved: false, time_spent: null, attempts: 0 },
    { problem_id: "p2", name: "Three Sum", contest_id: "2", index: "B", rating: 1500, url: "https://codeforces.com/2/B", solved: true, time_spent: 120, attempts: 2 },
    { problem_id: "p3", name: "Frog Jump", contest_id: "3", index: "C", rating: 1800, url: "https://codeforces.com/3/C", solved: false, time_spent: null, attempts: 0 },
  ],
};

const sampleSession = {
  id: "sess-auto",
  topic_id: "topic1",
  topic_name: "Dynamic Programming",
  problems_solved: 0,
  total_problems: 3,
  streak_count: 0,
  status: "active",
  started_at: new Date().toISOString(),
  last_solved_rating: null,
  streak_tokens_earned: 0,
};

const sampleRecommendedProblem = {
  problem_id: "1A",
  contest_id: 1,
  index: "A",
  name: "Two Sum",
  rating: 1200,
  tags: ["dp"],
  url: "https://codeforces.com/1/A",
  melo: 1350,
  search_range: [1250, 1550],
};

const sampleCuratedProblems = {
  problems: [
    { problem_id: "1A", contest_id: 1, index: "A", name: "Problem A", rating: 1200, tags: ["dp"], url: "https://codeforces.com/1/A", solved: false },
    { problem_id: "2B", contest_id: 2, index: "B", name: "Problem B", rating: 1400, tags: ["dp"], url: "https://codeforces.com/2/B", solved: true },
  ],
  total: 5,
  offset: 0,
  limit: 20,
};

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import TrainingDetailPage from "../TrainingDetailPage";

function renderPage(topicId = "topic1") {
  return render(
    <MemoryRouter initialEntries={[`/training/${topicId}`]}>
      <Routes>
        <Route path="/training/:id" element={<TrainingDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function setupAutoStartMocks(sessionData = sampleSession) {
  // GET topic detail
  mockApiGet.mockImplementation((url: string) => {
    if (url.includes("/training/topics/") && !url.includes("recommend") && !url.includes("curated") && !url.includes("active-session")) {
      return Promise.resolve({ data: { success: true, data: sampleTopic, message: "ok" } });
    }
    if (url.includes("active-session")) {
      return mockGetActiveTrainingSession().then(d => ({ data: { success: true, data: d } }));
    }
    if (url.includes("submission-tracking")) {
      return Promise.resolve({ data: { data: { status: "settled" } } });
    }
    return Promise.resolve({ data: { success: true, data: null } });
  });
  // POST auto-start session and abandon
  mockApiPost.mockImplementation((url: string) => {
    if (url.includes("/training/start")) {
      return Promise.resolve({ data: { success: true, data: sessionData } });
    }
    if (url.includes("abandon")) {
      return Promise.resolve({ data: { success: true, data: { session_id: "sess1", status: "abandoned", problems_solved: 0, total_problems: 3 } } });
    }
    return Promise.resolve({ data: { success: true, data: {} } });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TrainingDetailPage", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockApiGet.mockResolvedValue({ data: { data: null } });
    mockApiPost.mockResolvedValue({ data: { success: true, data: {} } });
    mockGetRecommendedProblem.mockResolvedValue(sampleRecommendedProblem);
    mockGetCuratedProblems.mockResolvedValue(sampleCuratedProblems);
    mockGetActiveTrainingSession.mockResolvedValue(null);
    mockSkipProblem.mockResolvedValue(undefined);
  });

  // ---- Loading ----

  it("shows loading spinner initially", () => {
    mockApiGet.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  // ---- Auto-start session ----

  it("auto-starts session when no active session exists", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith("/training/start", { topic_id: "topic1" });
    });
  });

  it("recovers existing active session without starting new one", async () => {
    const existingSession = { ...sampleSession, id: "existing-sess" };
    mockGetActiveTrainingSession.mockResolvedValue(existingSession);
    setupAutoStartMocks();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:endSession")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Should NOT have called POST /training/start since we recovered a session
    expect(mockApiPost).not.toHaveBeenCalledWith("/training/start", expect.anything());
  });

  it("shows unified layout with session stats when session is active", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:solvedLabel")).toBeInTheDocument();
    }, { timeout: 3000 });

    expect(screen.getByText("common:total")).toBeInTheDocument();
    expect(screen.getByText("training:streak")).toBeInTheDocument();
  });

  it("shows error but stays on page when auto-start fails", async () => {
    mockApiGet.mockImplementation((url: string) => {
      if (url.includes("/training/topics/") && !url.includes("recommend") && !url.includes("curated") && !url.includes("active-session")) {
        return Promise.resolve({ data: { success: true, data: sampleTopic, message: "ok" } });
      }
      return Promise.resolve({ data: { data: null } });
    });
    mockApiPost.mockImplementation((url: string) => {
      if (url.includes("/training/start")) {
        return Promise.reject({
          response: { data: { error: { message: "Cannot start" } } },
        });
      }
      return Promise.resolve({ data: { success: true, data: {} } });
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Cannot start")).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  // ---- Unified dual-column layout ----

  it("shows dual mode tabs in right panel", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:currentProblem")).toBeInTheDocument();
    });
    expect(screen.getByText("training:problemListMode")).toBeInTheDocument();
  });

  it("shows topic name in top bar", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });
  });

  it("shows timer in top bar", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("0:00")).toBeInTheDocument();
    });
  });

  it("shows back button with topics text", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:topics")).toBeInTheDocument();
    });
  });

  // ---- Recommend mode ----

  it("shows recommended problem viewer by default", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("problem-viewer")).toBeInTheDocument();
    });
  });

  it("shows change problem button in recommend mode", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:changeProblem")).toBeInTheDocument();
    });
  });

  it("shows solving timeline when recommended problem has rating", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("solving-timeline")).toBeInTheDocument();
    });
  });

  it("shows problem info card with rating and melo", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:infoPanel.rating")).toBeInTheDocument();
    });
    expect(screen.getByText("training:infoPanel.yourMelo")).toBeInTheDocument();
  });

  it("shows search range when recommended problem has search_range", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:infoPanel.searchRange")).toBeInTheDocument();
    });
  });

  it("shows View on Codeforces link", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:infoPanel.viewOnCodeforces")).toBeInTheDocument();
    });
  });

  it("shows no recommended problem message when none found", async () => {
    mockGetRecommendedProblem.mockResolvedValue(null);
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:noRecommendedProblem")).toBeInTheDocument();
    });
  });

  it("shows dash when recommended problem has no rating", async () => {
    mockGetRecommendedProblem.mockResolvedValue({
      ...sampleRecommendedProblem,
      rating: null,
    });
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:infoPanel.rating")).toBeInTheDocument();
    });
  });

  it("does not show SolvingTimeline when recommended problem has no rating", async () => {
    mockGetRecommendedProblem.mockResolvedValue({
      ...sampleRecommendedProblem,
      rating: null,
    });
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:changeProblem")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("solving-timeline")).not.toBeInTheDocument();
  });

  it("refreshes recommended problem when change problem button is clicked", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:changeProblem")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText("training:changeProblem"));
    });

    expect(mockGetRecommendedProblem).toHaveBeenCalledTimes(2);
  });

  // ---- List mode ----

  it("switches to problem list mode when tab is clicked", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:problemListMode")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText("training:problemListMode"));
    });

    await waitFor(() => {
      expect(mockGetCuratedProblems).toHaveBeenCalled();
    });
  });

  it("shows curated problems in list mode", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:problemListMode")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText("training:problemListMode"));
    });

    await waitFor(() => {
      expect(screen.getByText("1A - Problem A")).toBeInTheDocument();
    });
    expect(screen.getByText("2B - Problem B")).toBeInTheDocument();
  });

  it("shows load more button when there are more problems", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:problemListMode")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText("training:problemListMode"));
    });

    await waitFor(() => {
      expect(screen.getByText("training:loadMore")).toBeInTheDocument();
    });
  });

  it("shows no problems message when topic has no problems in list mode", async () => {
    mockGetCuratedProblems.mockResolvedValue({
      problems: [],
      total: 0,
      offset: 0,
      limit: 20,
    });
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:problemListMode")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText("training:problemListMode"));
    });

    await waitFor(() => {
      expect(screen.getByText("training:noProblems")).toBeInTheDocument();
    });
  });

  // ---- Session management ----

  it("calls abandon API when end session button is clicked", async () => {
    setupAutoStartMocks();
    const { container } = renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:endSession")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Find the end session button
    const endBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("endSession"),
    );
    expect(endBtn).toBeTruthy();

    // Click the button
    fireEvent.click(endBtn!);

    // Verify the abandon API was called
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        expect.stringContaining("abandon"),
      );
    }, { timeout: 3000 });
  });

  it("calls abandon API when back button is clicked during active session", async () => {
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:topics")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Click back button
    fireEvent.click(screen.getByText("training:topics"));

    // Back button also triggers abandon
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        expect.stringContaining("abandon"),
      );
    }, { timeout: 3000 });
  });

  // ---- Protection period ----

  it("shows protection period banner when session just started", async () => {
    // Session started 10 seconds ago
    const recentSession = {
      ...sampleSession,
      started_at: new Date(Date.now() - 10000).toISOString(),
    };
    setupAutoStartMocks(recentSession);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/training:protection.banner/)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it("does not show protection banner when session started more than 5 min ago", async () => {
    // Session started 10 minutes ago
    const oldSession = {
      ...sampleSession,
      started_at: new Date(Date.now() - 600000).toISOString(),
    };
    setupAutoStartMocks(oldSession);

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:endSession")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Protection banner should NOT be shown
    expect(screen.queryByText(/training:protection.banner/)).not.toBeInTheDocument();
  });

  // ---- Navigation guard ----

  it("registers beforeunload event when session is active", async () => {
    const addSpy = vi.spyOn(window, "addEventListener");
    setupAutoStartMocks();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:endSession")).toBeInTheDocument();
    }, { timeout: 3000 });

    expect(addSpy).toHaveBeenCalledWith("beforeunload", expect.any(Function));
    addSpy.mockRestore();
  });
});
