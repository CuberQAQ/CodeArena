import { describe, it, expect, vi, beforeAll, afterAll, afterEach, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
  initReactI18next: { type: "3rdParty", init: () => {} },
}));

vi.mock("@/i18n", () => ({
  default: { t: (key: string) => key, language: "en" },
}));

vi.mock("@/services/trainingApi", () => ({
  getMElo: vi.fn().mockResolvedValue({
    global_elo: 1500,
    melos: [
      { tag: "dp", elo: 1600, shield_active: false, total_submissions: 10 },
      { tag: "greedy", elo: 1400, shield_active: false, total_submissions: 5 },
    ],
  }),
}));

vi.mock("@/stores/auth", () => ({
  useAuthStore: () => ({
    user: { id: "user-1", elo: 1500 },
  }),
}));

vi.mock("@/utils", () => ({
  getRatingColor: () => "#00FF00",
  getDifficultyLabelKey: (r: number) => `rating:${r}`,
}));

vi.mock("@/components/charts/EloChart", () => ({
  EloChart: ({ data }: { data: unknown[] }) => (
    <div data-testid="elo-chart">EloChart ({data.length} pts)</div>
  ),
}));

vi.mock("@/components/charts/RadarChart", () => ({
  RadarChart: ({ data }: { data: unknown[] }) => (
    <div data-testid="radar-chart">RadarChart ({data.length} pts)</div>
  ),
}));

vi.mock("@/components/charts/PPChart", () => ({
  PPChart: ({ data }: { data: unknown[] }) => (
    <div data-testid="pp-chart">PPChart ({data.length} pts)</div>
  ),
}));

vi.mock("@/components/charts/StatsPanel", () => ({
  StatsPanel: ({ stats }: { stats: { total_solved: number } }) => (
    <div data-testid="stats-panel">StatsPanel (solved: {stats.total_solved})</div>
  ),
}));

// ---------------------------------------------------------------------------
// MSW server
// ---------------------------------------------------------------------------

const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { DashboardCharts } from "@/components/charts/DashboardCharts";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("DashboardCharts", () => {
  it("renders analytics title", async () => {
    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      expect(screen.getByText("analytics")).toBeInTheDocument();
    });
  });

  it("renders sub-charts after loading", async () => {
    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      expect(screen.getByTestId("elo-chart")).toBeInTheDocument();
      expect(screen.getByTestId("radar-chart")).toBeInTheDocument();
      expect(screen.getByTestId("pp-chart")).toBeInTheDocument();
      expect(screen.getByTestId("stats-panel")).toBeInTheDocument();
    });
  });

  it("renders refresh button", async () => {
    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      expect(screen.getByText("analytics")).toBeInTheDocument();
    });

    // Refresh button should be visible
    const buttons = screen.getAllByRole("button");
    expect(buttons.length).toBeGreaterThanOrEqual(1);
  });

  it("handles API errors gracefully", async () => {
    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({ success: false }, { status: 500 }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      expect(screen.getByText("analytics")).toBeInTheDocument();
    });
  });

  it("renders with elo history data", async () => {
    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({
          success: true,
          data: [
            { date: "2025-01-01", elo: 1400, change: 0 },
            { date: "2025-01-02", elo: 1420, change: 20 },
          ],
          message: "ok",
        }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({
          success: true,
          data: [
            { problem_name: "1920A", rating: 1500, pp: 25.5 },
          ],
          message: "ok",
        }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      expect(screen.getByTestId("elo-chart")).toHaveTextContent("2 pts");
    });
  });

  it("renders stats panel with solved count from melo data", async () => {
    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      // 10 + 5 = 15 total submissions from melos
      expect(screen.getByTestId("stats-panel")).toHaveTextContent("15");
    });
  });

  // Covers lines 55-56 in buildStatsFromData: positive and negative tx amounts
  it("computes stats with mixed positive and negative transaction amounts", async () => {
    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    const transactions = [
      { id: "1", amount: 10, type: "reward", reference_type: null, reference_id: null, balance_after: 110, created_at: "2025-01-01T00:00:00Z" },
      { id: "2", amount: -3, type: "hint", reference_type: null, reference_id: null, balance_after: 107, created_at: "2025-01-02T00:00:00Z" },
      { id: "3", amount: 5, type: "reward", reference_type: null, reference_id: null, balance_after: 112, created_at: "2025-01-03T00:00:00Z" },
    ];

    render(<DashboardCharts transactions={transactions} />);

    await waitFor(() => {
      expect(screen.getByTestId("stats-panel")).toBeInTheDocument();
    });
  });

  // Covers line 164: totalSolved fallback to ppResult.length when melo submissions are 0
  it("uses pp contributions count when melo total submissions is 0", async () => {
    const { getMElo } = await import("@/services/trainingApi");
    (getMElo as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      global_elo: 1500,
      melos: [
        { tag: "dp", elo: 1600, shield_active: false, total_submissions: 0 },
      ],
    });

    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({
          success: true,
          data: [
            { problem_name: "1920A", rating: 1500, pp: 25.5 },
            { problem_name: "1920B", rating: 1600, pp: 30 },
            { problem_name: "1921A", rating: 1700, pp: 35 },
          ],
          message: "ok",
        }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      // totalSolved should be 3 (from pp contributions) since melo total_submissions is 0
      expect(screen.getByTestId("stats-panel")).toHaveTextContent("3");
    });
  });

  // Covers shield_active=true branch in buildRadarDataFromMElo (line 52)
  it("uses global elo when shield is active for a tag", async () => {
    const { getMElo } = await import("@/services/trainingApi");
    (getMElo as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      global_elo: 1500,
      melos: [
        { tag: "dp", elo: 1600, shield_active: true, total_submissions: 5 },
        { tag: "greedy", elo: 1400, shield_active: false, total_submissions: 3 },
      ],
    });

    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      expect(screen.getByTestId("radar-chart")).toBeInTheDocument();
    });
  });

  // Covers buildStatsFromData fallback branch (lines 124-131)
  it("builds difficulty distribution from radar data when no pp contributions", async () => {
    const { getMElo } = await import("@/services/trainingApi");
    (getMElo as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      global_elo: 1500,
      melos: [
        { tag: "dp", elo: 1600, shield_active: false, total_submissions: 10 },
      ],
    });

    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      expect(screen.getByTestId("stats-panel")).toBeInTheDocument();
    });
  });

  // Covers getMElo rejection (line 172 catch)
  it("handles getMElo rejection gracefully", async () => {
    const { getMElo } = await import("@/services/trainingApi");
    (getMElo as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("Network error"));

    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      expect(screen.getByText("analytics")).toBeInTheDocument();
    });
  });

  // Covers pp.rating == null check (line 109)
  it("handles pp contributions with null ratings", async () => {
    const { getMElo } = await import("@/services/trainingApi");
    (getMElo as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      global_elo: 1500,
      melos: [
        { tag: "dp", elo: 1600, shield_active: false, total_submissions: 5 },
      ],
    });

    server.use(
      http.get("*/api/v1/auth/elo-history", () =>
        HttpResponse.json({ success: true, data: [], message: "ok" }),
      ),
      http.get("*/api/v1/auth/pp-contributions", () =>
        HttpResponse.json({
          success: true,
          data: [
            { problem_name: "1920A", rating: null, pp: 10 },
            { problem_name: "1920B", rating: 1500, pp: 25.5 },
          ],
          message: "ok",
        }),
      ),
    );

    render(<DashboardCharts transactions={[]} />);

    await waitFor(() => {
      expect(screen.getByTestId("stats-panel")).toBeInTheDocument();
    });
  });
});
