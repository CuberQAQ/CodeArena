import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

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

vi.mock("@/stores/auth", () => ({
  useAuthStore: vi.fn(() => ({
    user: { id: "u1", username: "testuser", elo: 1200, tokens: 100 },
    isAuthenticated: true,
    isLoading: false,
    fetchUser: vi.fn().mockResolvedValue(undefined),
  })),
}));

vi.mock("@/hooks/useTheme", () => ({
  useTheme: () => ({ theme: "dark", resolved: "dark" }),
}));

vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: ({ text }: { text?: string }) => (
    <div data-testid="loading-spinner">{text ?? "Loading..."}</div>
  ),
}));

vi.mock("@/components/medal/MedalBadge", () => ({
  MedalBadge: ({ level }: { level: string }) => (
    <div data-testid="medal-badge">{level}</div>
  ),
}));

vi.mock("@/utils", () => ({
  getRatingTierInfo: (rating: number) => {
    if (rating >= 2400) return { name: "Grandmaster", color: "#FF0000" };
    if (rating >= 1600) return { name: "Expert", color: "#0000FF" };
    if (rating >= 1200) return { name: "Pupil", color: "#008000" };
    return { name: "Newbie", color: "#808080" };
  },
  RATING_KEY_MAP: {
    Newbie: "rating:newbie",
    Pupil: "rating:pupil",
    Expert: "rating:expert",
    Grandmaster: "rating:grandmaster",
  },
}));

vi.mock("@/services/trainingApi", () => ({
  getRecommendedTopics: vi.fn().mockResolvedValue([]),
  getMElo: vi.fn().mockResolvedValue({
    melos: [
      { tag: "dp", elo: 1300, shield_active: false, total_submissions: 5 },
    ],
    global_elo: 1200,
  }),
}));

vi.mock("@/components/charts/TrainingRadarChart", () => ({
  TrainingRadarChart: ({ data }: { data: Array<{ topic: string; value: number }> }) => (
    <div data-testid="training-radar">
      {data.length > 0 ? `Radar: ${data.length} dims` : "Radar: empty"}
    </div>
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

import TrainingPage from "../TrainingPage";

function renderPage(initialPath = "/training") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <TrainingPage />
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Test data
// ---------------------------------------------------------------------------

const typicalTopics = [
  {
    id: "t1",
    name: "Dynamic Programming",
    name_zh: "动态规划",
    slug: "dp",
    description: "Practice DP problems",
    cf_tags: ["dp"],
    display_order: 1,
    total_problems: 10,
    solved_count: 5,
    stars: 3,
    melo: 1350,
    shield_active: false,
    medal: { level: "provincial", type: "silver" },
    current_medal_threshold: 1200,
    next_medal_threshold: 1400,
  },
  {
    id: "t2",
    name: "Greedy",
    name_zh: "贪心",
    slug: "greedy",
    description: "Greedy algorithms",
    cf_tags: ["greedy", "math"],
    display_order: 2,
    total_problems: 8,
    solved_count: 0,
    stars: 0,
    melo: null,
    shield_active: false,
    medal: null,
    current_medal_threshold: null,
    next_medal_threshold: null,
  },
  {
    id: "t3",
    name: "Graph Theory",
    name_zh: "图论",
    slug: "graphs",
    description: null,
    cf_tags: ["graphs", "dfs", "bfs"],
    display_order: 3,
    total_problems: 12,
    solved_count: 12,
    stars: 7,
    melo: 2200,
    shield_active: true,
    medal: { level: "regional", type: "gold" },
    current_medal_threshold: 1600,
    next_medal_threshold: null,
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("TrainingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.resetHandlers();
  });

  // 1. Loading state
  it("shows loading spinner initially", () => {
    server.use(
      http.get("*/api/v1/training/topics", async () => {
        await new Promise(() => {}); // Never resolves
      }),
    );

    renderPage();
    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
    expect(screen.getByText("loadingTopics")).toBeInTheDocument();
  });

  // 2. Empty state -- no topics
  it("shows empty state message when no topics available", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("noTopics")).toBeInTheDocument();
    });
    expect(screen.queryByText("Dynamic Programming")).not.toBeInTheDocument();
  });

  // 3. Error state -- API returns error
  it("shows error message when API returns an error", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR", message: "Failed to load topics" } },
          { status: 500 },
        ),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Failed to load topics")).toBeInTheDocument();
    });
  });

  it("shows fallback error message when API error has no message", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json(
          { success: false, error: { code: "ERR" } },
          { status: 500 },
        ),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("failedLoadTopics")).toBeInTheDocument();
    });
  });

  // 4. Normal data -- topic cards render with fallback names
  it("renders topic cards with fallback names and progress", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: typicalTopics, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });
    expect(screen.getByText("Greedy")).toBeInTheDocument();
    expect(screen.getByText("Graph Theory")).toBeInTheDocument();
    // Shows progress: solved/total
    expect(screen.getByText(/5\/10/)).toBeInTheDocument();
    expect(screen.getByText(/0\/8/)).toBeInTheDocument();
    expect(screen.getByText(/12\/12/)).toBeInTheDocument();
  });

  // 5. Boundary data
  it("renders topics with boundary values correctly", async () => {
    const boundaryTopics = [
      {
        id: "t-empty",
        name: "Empty Topic",
        name_zh: "空专题",
        slug: "empty",
        description: "A topic with zero problems",
        cf_tags: [],
        display_order: 1,
        total_problems: 0,
        solved_count: 0,
        stars: 0,
        melo: 0,
        shield_active: false,
        medal: { level: "unranked" },
        current_medal_threshold: null,
        next_medal_threshold: null,
      },
      {
        id: "t-extreme",
        name: "Extreme Topic With A Very Long Name",
        name_zh: "极端专题",
        slug: "extreme",
        description: "Lorem ipsum dolor sit amet.",
        cf_tags: ["tag1", "tag2", "tag3"],
        display_order: 2,
        total_problems: 9999,
        solved_count: 9999,
        stars: 7,
        melo: 9999,
        shield_active: true,
        medal: { level: "world_finals", type: "gold" },
        current_medal_threshold: 2800,
        next_medal_threshold: null,
      },
    ];

    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: boundaryTopics, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Empty Topic")).toBeInTheDocument();
    });
    expect(screen.getByText("Extreme Topic With A Very Long Name")).toBeInTheDocument();
    expect(screen.getByText(/0\/0/)).toBeInTheDocument();
    expect(screen.getByText(/9999\/9999/)).toBeInTheDocument();
  });

  // 6. ProgressRing removed - Elo progress bar replaces it
  it("no longer shows ProgressRing percentage text", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: [typicalTopics[0]], message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });
    // ProgressRing used to show "50%" text - should no longer exist
    expect(screen.queryByText("50%")).not.toBeInTheDocument();
  });

  // 7. Today's training goal section
  it("shows today's training goal section", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: typicalTopics, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("todayGoal.title")).toBeInTheDocument();
    });
  });

  // 8. Recommended topics section displays when API returns data
  it("shows recommended topics section when API returns data", async () => {
    const { getRecommendedTopics } = await import("@/services/trainingApi");
    vi.mocked(getRecommendedTopics).mockResolvedValue([
      { slug: "dp", name: "Dynamic Programming", name_zh: "动态规划", melo: 1000, reason: "Lowest M-Elo" },
      { slug: "greedy", name: "Greedy", name_zh: "贪心", melo: null, reason: "Not started" },
    ]);

    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: typicalTopics, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("recommendedTopics.title")).toBeInTheDocument();
    });
    expect(screen.getAllByText("Dynamic Programming").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Greedy").length).toBeGreaterThanOrEqual(2);
  });

  // 9. Recommended topics section hidden when API fails
  it("hides recommended topics section when API fails", async () => {
    const { getRecommendedTopics } = await import("@/services/trainingApi");
    vi.mocked(getRecommendedTopics).mockRejectedValue(new Error("Failed"));

    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: typicalTopics, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });
    expect(screen.queryByText("recommendedTopics.title")).not.toBeInTheDocument();
  });

  // 10. Topic cards link to correct detail page
  it("links topic cards to the correct training detail page", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: [typicalTopics[0]], message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      const link = screen.getByText("Dynamic Programming").closest("a");
      expect(link).toHaveAttribute("href", "/training/t1");
    });
  });

  // 11. Radar chart is rendered
  it("renders the skill radar chart", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: typicalTopics, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("training-radar")).toBeInTheDocument();
    });
  });

  // 12. Medal badges are shown on topic cards
  it("shows medal badges on topic cards", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: typicalTopics, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });
    // DP has medal level "provincial"
    const badges = screen.getAllByTestId("medal-badge");
    expect(badges.length).toBeGreaterThanOrEqual(2); // DP + Graphs both have medals
    expect(badges.some((b) => b.textContent === "provincial")).toBe(true);
    expect(badges.some((b) => b.textContent === "regional")).toBe(true);
  });

  // 13. Medal badge not shown when medal is null
  it("does not show medal badge when topic has no medal", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: [typicalTopics[1]], message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Greedy")).toBeInTheDocument();
    });
    // Greedy topic has medal: null
    expect(screen.queryByTestId("medal-badge")).not.toBeInTheDocument();
  });

  // 14. Elo progress bar shows "eloUntilNext" for normal topic
  it("shows Elo progress info for topics with melo data", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: [typicalTopics[0]], message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });
    // DP: melo=1350, currentThreshold=1200, nextThreshold=1400
    // remaining = 1400 - 1350 = 50
    expect(screen.getByText(/50/)).toBeInTheDocument();
  });

  // 15. Elo progress bar shows max tier for highest tier topic
  it("shows max tier message when at highest medal tier", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: [typicalTopics[2]], message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Graph Theory")).toBeInTheDocument();
    });
    // Graphs: nextThreshold=null, currentThreshold=1600 -> max tier
    expect(screen.getByText("eloProgressMax")).toBeInTheDocument();
  });

  // 16. Hover-only secondary info present in DOM
  it("has solved count info in topic cards for hover", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: [typicalTopics[0]], message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Dynamic Programming")).toBeInTheDocument();
    });
    // The hover info section exists (opacity-0 by default)
    expect(screen.getByText(/solvedCount/)).toBeInTheDocument();
  });

  // 17. Radar chart shows empty state when M-Elo API fails
  it("shows empty radar when M-Elo API fails", async () => {
    const { getMElo } = await import("@/services/trainingApi");
    vi.mocked(getMElo).mockRejectedValue(new Error("Failed"));

    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: typicalTopics, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("training-radar")).toBeInTheDocument();
    });
    // When getMElo fails, radarData stays empty
    expect(screen.getByText("Radar: empty")).toBeInTheDocument();
  });

  // 18. Topic with null melo does not show Elo progress bar
  it("does not show Elo progress bar when melo is null", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: [typicalTopics[1]], message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Greedy")).toBeInTheDocument();
    });
    // Greedy has melo: null, should not show eloUntilNext or eloProgressMax
    expect(screen.queryByText(/eloUntilNext/)).not.toBeInTheDocument();
    expect(screen.queryByText("eloProgressMax")).not.toBeInTheDocument();
  });
});
