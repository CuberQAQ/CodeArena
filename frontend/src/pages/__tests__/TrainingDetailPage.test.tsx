import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

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
  ProblemViewer: ({ contestId, index }: { contestId: string; index: string }) => (
    <div data-testid="problem-viewer">{contestId}{index}</div>
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

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

const sampleTopic = {
  id: "topic1",
  name: "Dynamic Programming",
  description: "Learn DP basics",
  cf_tags: ["dp"],
  problems: [
    { problem_id: "p1", name: "Two Sum", contest_id: "1", index: "A", rating: 1200, url: "https://codeforces.com/1/A", solved: false, time_spent: null, attempts: 0 },
    { problem_id: "p2", name: "Three Sum", contest_id: "2", index: "B", rating: 1500, url: "https://codeforces.com/2/B", solved: true, time_spent: 120, attempts: 2 },
    { problem_id: "p3", name: "Frog Jump", contest_id: "3", index: "C", rating: 1800, url: "https://codeforces.com/3/C", solved: false, time_spent: null, attempts: 0 },
  ],
};

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

import TrainingDetailPage from "../TrainingDetailPage";

function renderPage(topicId = "topic1") {
  return render(
    <MemoryRouter initialEntries={[`/training/topic/${topicId}`]}>
      <Routes>
        <Route path="/training/topic/:id" element={<TrainingDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function mockTopicFetch(topic = sampleTopic) {
  mockApiGet.mockImplementation((url: string) => {
    if (url.includes("/training/topics/")) {
      return Promise.resolve({ data: { success: true, data: topic, message: "ok" } });
    }
    if (url.includes("submission-tracking")) {
      return Promise.resolve({ data: { data: { status: "pending" } } });
    }
    return Promise.resolve({ data: { success: true, data: {} } });
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TrainingDetailPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApiGet.mockResolvedValue({ data: { data: { status: "pending" } } });
    mockApiPost.mockResolvedValue({ data: { success: true, data: {} } });
  });

  it("shows loading spinner initially", () => {
    mockApiGet.mockReturnValue(new Promise(() => {}));
    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  it("renders topic name, description, and tags", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });
    expect(screen.getByText("Learn DP basics")).toBeInTheDocument();
    expect(screen.getByText("dp")).toBeInTheDocument();
  });

  it("renders problem list with names and ratings", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/Two Sum/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Three Sum/)).toBeInTheDocument();
    expect(screen.getByText(/Frog Jump/)).toBeInTheDocument();
  });

  it("shows start training button", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:startTraining")).toBeInTheDocument();
    });
  });

  it("shows solved indicator for solved problems", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/training:solvedIn/)).toBeInTheDocument();
    });
  });

  it("shows no problems message when topic has no problems", async () => {
    mockTopicFetch({ ...sampleTopic, problems: [] });
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("training:noProblems")).toBeInTheDocument();
    });
  });

  it("fetches topic with correct topic ID from URL params", async () => {
    mockTopicFetch();
    renderPage("my-topic-123");

    await waitFor(() => {
      expect(mockApiGet).toHaveBeenCalledWith(
        expect.stringContaining("my-topic-123"),
      );
    });
  });

  it("falls back to loading spinner when topic fetch fails", async () => {
    mockApiGet.mockImplementation((url: string) => {
      if (url.includes("/training/topics/")) {
        return Promise.reject({
          response: { data: { error: { message: "Topic not found" } } },
        });
      }
      return Promise.resolve({ data: { data: { status: "pending" } } });
    });
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
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

  it("renders all problems with correct content in order", async () => {
    mockTopicFetch();
    renderPage();

    await waitFor(() => {
      expect(screen.getByText("1A - Two Sum")).toBeInTheDocument();
    });
    expect(screen.getByText("2B - Three Sum")).toBeInTheDocument();
    expect(screen.getByText("3C - Frog Jump")).toBeInTheDocument();
  });
});
