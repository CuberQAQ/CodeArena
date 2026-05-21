import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

vi.mock("@/services/trainingApi", () => ({
  getActiveTrainingSession: vi.fn().mockResolvedValue(null),
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
      return Promise.resolve({ data: { data: { status: "pending" } } });
    }
    return Promise.resolve({ data: { success: true, data: null } });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TrainingDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApiGet.mockResolvedValue({ data: { data: null } });
    mockApiPost.mockResolvedValue({ data: { success: true, data: {} } });
    mockGetRecommendedProblem.mockResolvedValue(sampleRecommendedProblem);
    mockGetCuratedProblems.mockResolvedValue(sampleCuratedProblems);
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
});
