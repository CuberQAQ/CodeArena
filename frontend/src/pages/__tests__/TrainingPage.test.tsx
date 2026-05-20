import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
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
    slug: "dp",
    description: "Practice DP problems",
    cf_tags: ["dp"],
    display_order: 1,
    total_problems: 10,
    solved_count: 5,
    stars: 3,
    melo: 1350,
    shield_active: false,
  },
  {
    id: "t2",
    name: "Greedy",
    slug: "greedy",
    description: "Greedy algorithms",
    cf_tags: ["greedy", "math"],
    display_order: 2,
    total_problems: 8,
    solved_count: 0,
    stars: 0,
    melo: null,
    shield_active: false,
  },
  {
    id: "t3",
    name: "Graph Theory",
    slug: "graphs",
    description: null,
    cf_tags: ["graphs", "dfs", "bfs"],
    display_order: 3,
    total_problems: 12,
    solved_count: 12,
    stars: 7,
    melo: 2200,
    shield_active: true,
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

  // 2. Empty state — no topics
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
    // Should not crash and should show the empty state with BookOpen icon
    expect(screen.queryByText("Dynamic Programming")).not.toBeInTheDocument();
  });

  // 3. Error state — API returns error
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

  // 4. Normal data — topics render correctly
  it("renders topic cards with normal data", async () => {
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
    // Shows descriptions
    expect(screen.getByText("Practice DP problems")).toBeInTheDocument();
    expect(screen.getByText("Greedy algorithms")).toBeInTheDocument();
    // Shows solved/total
    expect(screen.getByText(/5\/10/)).toBeInTheDocument();
    expect(screen.getByText(/0\/8/)).toBeInTheDocument();
    expect(screen.getByText(/12\/12/)).toBeInTheDocument();
  });

  it("shows notStarted label when melo is null", async () => {
    server.use(
      http.get("*/api/v1/training/topics", () =>
        HttpResponse.json({ success: true, data: typicalTopics, message: "ok" }),
      ),
    );

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Greedy")).toBeInTheDocument();
    });
    expect(screen.getByText("notStarted")).toBeInTheDocument();
  });

  // 5. Boundary data — topic with zero problems, extreme melo
  it("renders topics with boundary values correctly", async () => {
    const boundaryTopics = [
      {
        id: "t-empty",
        name: "Empty Topic",
        slug: "empty",
        description: "A topic with zero problems",
        cf_tags: [],
        display_order: 1,
        total_problems: 0,
        solved_count: 0,
        stars: 0,
        melo: 0,
        shield_active: false,
      },
      {
        id: "t-extreme",
        name: "Extreme Topic With A Very Very Very Long Name That Should Not Break Layout",
        slug: "extreme",
        description: "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
        cf_tags: ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6"],
        display_order: 2,
        total_problems: 9999,
        solved_count: 9999,
        stars: 7,
        melo: 9999,
        shield_active: true,
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
    // Extreme long name should render
    expect(
      screen.getByText("Extreme Topic With A Very Very Very Long Name That Should Not Break Layout"),
    ).toBeInTheDocument();
    // Boundary solved/total
    expect(screen.getByText(/0\/0/)).toBeInTheDocument();
    expect(screen.getByText(/9999\/9999/)).toBeInTheDocument();
  });
});
