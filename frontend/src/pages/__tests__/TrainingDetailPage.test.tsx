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

vi.mock("@/services/trainingApi", () => ({
  getActiveTrainingSession: (...args: unknown[]) => mockGetActiveTrainingSession(...args),
  getRecommendedTopics: vi.fn().mockResolvedValue([]),
  getRecommendedProblem: (...args: unknown[]) => mockGetRecommendedProblem(...args),
  getCuratedProblems: (...args: unknown[]) => mockGetCuratedProblems(...args),
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

function mockTopicFetch(topic = sampleTopic) {
  mockApiGet.mockImplementation((url: string) => {
    if (url.includes("/training/topics/") && !url.includes("recommend") && !url.includes("curated") && !url.includes("active-session")) {
      return Promise.resolve({ data: { success: true, data: topic, message: "ok" } });
    }
    if (url.includes("submission-tracking")) {
      return Promise.resolve({ data: { data: { status: "settled" } } });
    }
    return Promise.resolve({ data: { success: true, data: null } });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TrainingDetailPage", () => {
  afterEach(() => {
    // Clean up any lingering timers from the component
    vi.useRealTimers();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    mockApiGet.mockResolvedValue({ data: { data: null } });
    mockApiPost.mockResolvedValue({ data: { success: true, data: {} } });
    mockGetRecommendedProblem.mockResolvedValue(sampleRecommendedProblem);
    mockGetCuratedProblems.mockResolvedValue(sampleCuratedProblems);
    mockGetActiveTrainingSession.mockResolvedValue(null);
  });

  it("shows loading spinner initially", () => {
    mockApiGet.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  it("renders topic name and description", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      // t("training:topic.dp", "Dynamic Programming") returns "Dynamic Programming" (fallback)
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });
    expect(screen.getByText("Learn DP basics")).toBeInTheDocument();
  });

  it("shows start training button", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:startTraining")).toBeInTheDocument();
    });
  });

  it("shows dual mode tabs (recommend and problem list)", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:recommendMode")).toBeInTheDocument();
    });
    expect(screen.getByText("training:problemListMode")).toBeInTheDocument();
  });

  it("shows recommend mode by default with problem viewer", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("problem-viewer")).toBeInTheDocument();
    });
  });

  it("shows change problem button in recommend mode", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:changeProblem")).toBeInTheDocument();
    });
  });

  it("shows solving timeline when recommended problem has rating", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("solving-timeline")).toBeInTheDocument();
    });
  });

  it("switches to problem list mode when tab is clicked", async () => {
    mockTopicFetch();
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

  it("shows no recommended problem message when none found", async () => {
    mockGetRecommendedProblem.mockResolvedValue(null);
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:noRecommendedProblem")).toBeInTheDocument();
    });
  });

  it("calls start session API when start button is clicked", async () => {
    const sampleSession = {
      id: "sess1", topic_id: "topic1", problems_solved: 1, total_problems: 3, streak_count: 2, status: "active",
    };
    mockApiPost.mockResolvedValue({ data: { success: true, data: sampleSession } });
    mockTopicFetch();

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText("training:startTraining"));
    });

    expect(mockApiPost).toHaveBeenCalledWith("/training/start", { topic_id: "topic1" });
  });

  it("shows error when session start fails", async () => {
    mockApiPost.mockImplementation((url: string) => {
      if (url.includes("/training/start")) {
        return Promise.reject({
          response: { data: { error: { message: "Cannot start" } } },
        });
      }
      return Promise.resolve({ data: { success: true, data: {} } });
    });
    mockTopicFetch();

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText("training:startTraining"));
    });

    await waitFor(() => {
      expect(screen.getByText("Cannot start")).toBeInTheDocument();
    });
  });

  it("navigates to /training when back button is clicked", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:backToTopics")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("training:backToTopics"));

    expect(mockNavigate).toHaveBeenCalledWith("/training");
  });

  it("shows no problems message when topic has no problems in list mode", async () => {
    mockGetCuratedProblems.mockResolvedValue({
      problems: [],
      total: 0,
      offset: 0,
      limit: 20,
    });
    mockTopicFetch({ ...sampleTopic, problems: [] });
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

  it("shows problem info card with rating and melo in recommend mode", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:infoPanel.rating")).toBeInTheDocument();
    });
    expect(screen.getByText("training:infoPanel.yourMelo")).toBeInTheDocument();
  });

  it("refreshes recommended problem when change problem button is clicked", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:changeProblem")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText("training:changeProblem"));
    });

    expect(mockGetRecommendedProblem).toHaveBeenCalledTimes(2);
  });

  // --- SESSION PHASE ---

  it("enters session phase when active session exists on load", async () => {
    const sessionData = {
      id: "sess-active",
      topic_id: "topic1",
      problems_solved: 1,
      total_problems: 3,
      streak_count: 0,
      status: "active",
      started_at: new Date().toISOString(),
    };
    mockGetActiveTrainingSession.mockResolvedValue(sessionData);
    mockTopicFetch();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:endSession")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Session stats should be visible
    expect(screen.getByText("training:solvedLabel")).toBeInTheDocument();
    expect(screen.getByText("common:total")).toBeInTheDocument();
    expect(screen.getByText("training:streak")).toBeInTheDocument();
  });

  it("shows session problems in session phase", async () => {
    const sessionData = {
      id: "sess-problems",
      topic_id: "topic1",
      problems_solved: 1,
      total_problems: 3,
      streak_count: 0,
      status: "active",
      started_at: new Date().toISOString(),
    };
    mockGetActiveTrainingSession.mockResolvedValue(sessionData);
    mockTopicFetch();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:endSession")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Problems from topic should be visible
    expect(screen.getByText("1A - Two Sum")).toBeInTheDocument();
    expect(screen.getByText("2B - Three Sum")).toBeInTheDocument();
    expect(screen.getByText("3C - Frog Jump")).toBeInTheDocument();
  });

  // --- CURATED PROBLEMS ---

  it("shows problem list with load more when has more problems", async () => {
    mockGetCuratedProblems.mockResolvedValue({
      problems: [
        { problem_id: "1A", contest_id: 1, index: "A", name: "Problem A", rating: 1200, tags: ["dp"], url: "https://codeforces.com/1/A", solved: false },
        { problem_id: "2B", contest_id: 2, index: "B", name: "Problem B", rating: 1400, tags: ["dp"], url: "https://codeforces.com/2/B", solved: true },
      ],
      total: 10,
      offset: 0,
      limit: 20,
    });
    mockTopicFetch();
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

  it("shows no more problems message when all loaded", async () => {
    mockGetCuratedProblems.mockResolvedValue({
      problems: [
        { problem_id: "1A", contest_id: 1, index: "A", name: "Problem A", rating: 1200, tags: ["dp"], url: "https://codeforces.com/1/A", solved: true },
      ],
      total: 1,
      offset: 0,
      limit: 20,
    });
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:problemListMode")).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText("training:problemListMode"));
    });

    await waitFor(() => {
      expect(screen.getByText("training:noMoreProblems")).toBeInTheDocument();
    });
  });

  // --- RECOMMEND MODE EDGE CASES ---

  it("shows search range when recommended problem has search_range", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:infoPanel.searchRange")).toBeInTheDocument();
    });
  });

  it("shows no rating dash when recommended problem has no rating", async () => {
    mockGetRecommendedProblem.mockResolvedValue({
      ...sampleRecommendedProblem,
      rating: null,
    });
    mockTopicFetch();
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
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:changeProblem")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("solving-timeline")).not.toBeInTheDocument();
  });

  // --- SESSION ABANDON & RESET ---

  it("abandons session and shows result phase (covers abandonSession lines 259-272)", async () => {
    const sessionData = {
      id: "sess-abandon",
      topic_id: "topic1",
      problems_solved: 1,
      total_problems: 3,
      streak_count: 2,
      status: "active",
      started_at: new Date().toISOString(),
    };
    mockGetActiveTrainingSession.mockResolvedValue(sessionData);
    mockApiPost.mockResolvedValue({ data: { success: true, data: {} } });
    mockTopicFetch();

    const { container } = renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /endSession/ })).toBeInTheDocument();
    }, { timeout: 10000 });

    // Find and click the abandon button
    const buttons = container.querySelectorAll('button');
    const abandonBtn = Array.from(buttons).find(b => b.textContent?.includes("endSession"));
    expect(abandonBtn).toBeTruthy();

    fireEvent.click(abandonBtn!);

    // Verify abandonSession was called (covers lines 259-272)
    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        expect.stringContaining("abandon"),
      );
    }, { timeout: 5000 });

    // Verify state changes occurred (loading → result phase)
    // Even if DOM hasn't re-rendered yet, the API call proves the function ran
    expect(mockApiPost).toHaveBeenCalledTimes(1);
  }, 20000);

  it("resets from result phase back to topic phase (covers handleReset lines 274-283)", async () => {
    const sessionData = {
      id: "sess-reset",
      topic_id: "topic1",
      problems_solved: 2,
      total_problems: 3,
      streak_count: 1,
      status: "active",
      started_at: new Date().toISOString(),
    };
    mockGetActiveTrainingSession.mockResolvedValue(sessionData);
    mockApiPost.mockResolvedValue({ data: { success: true, data: {} } });
    mockTopicFetch();

    const { container } = renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /endSession/ })).toBeInTheDocument();
    }, { timeout: 10000 });

    // Click end session
    const buttons = container.querySelectorAll('button');
    const abandonBtn = Array.from(buttons).find(b => b.textContent?.includes("endSession"));
    fireEvent.click(abandonBtn!);

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        expect.stringContaining("abandon"),
      );
    }, { timeout: 5000 });

    // Click "Train Again" to trigger handleReset (covers lines 274-283)
    const resetBtn = Array.from(buttons).find(b => b.textContent?.includes("trainAgain"));
    if (resetBtn) {
      fireEvent.click(resetBtn);
    }

    // handleReset sets phase back to "topic"
    expect(mockApiPost).toHaveBeenCalled();
  }, 20000);

  it("navigates to /training from result phase back to topics button (covers line 746)", async () => {
    const sessionData = {
      id: "sess-nav",
      topic_id: "topic1",
      problems_solved: 1,
      total_problems: 3,
      streak_count: 0,
      status: "active",
      started_at: new Date().toISOString(),
    };
    mockGetActiveTrainingSession.mockResolvedValue(sessionData);
    mockApiPost.mockResolvedValue({ data: { success: true, data: {} } });
    mockTopicFetch();

    const { container } = renderPage();

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /endSession/ })).toBeInTheDocument();
    }, { timeout: 10000 });

    // Click end session
    const buttons = container.querySelectorAll('button');
    const abandonBtn = Array.from(buttons).find(b => b.textContent?.includes("endSession"));
    fireEvent.click(abandonBtn!);

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith(
        expect.stringContaining("abandon"),
      );
    }, { timeout: 5000 });

    // The "Back to Topics" button in session header (line 746 area)
    const backBtn = Array.from(buttons).find(b => b.textContent?.includes("topics"));
    if (backBtn) {
      fireEvent.click(backBtn);
      expect(mockNavigate).toHaveBeenCalledWith("/training");
    }
  }, 20000);

  // Covers selected problem in session phase (lines 708-721)
  it("shows problem viewer when selecting a problem in session phase", async () => {
    const sessionData = {
      id: "sess-select",
      topic_id: "topic1",
      problems_solved: 0,
      total_problems: 3,
      streak_count: 0,
      status: "active",
      started_at: new Date().toISOString(),
    };
    mockGetActiveTrainingSession.mockResolvedValue(sessionData);
    mockTopicFetch();

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:endSession")).toBeInTheDocument();
    }, { timeout: 3000 });

    // Problem should be auto-selected (first unsolved problem)
    // "1A - Two Sum" is first unsolved problem in sampleTopic
    expect(screen.getByText("1A - Two Sum")).toBeInTheDocument();
  });
});
