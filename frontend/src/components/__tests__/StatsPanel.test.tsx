import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  PieChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Pie: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Cell: () => <div />,
  Tooltip: ({ content }: { content?: React.ReactElement }) => {
    const TooltipFn = content && typeof content.type === "function" ? content.type : null;
    return (
      <div data-testid="tooltip-mock">
        <div data-testid="tooltip-inactive">
          {TooltipFn ? TooltipFn({ active: false, payload: [] }) : null}
        </div>
        <div data-testid="tooltip-active">
          {TooltipFn
            ? TooltipFn({
                active: true,
                payload: [{ value: 20, payload: { difficulty: "Easy", count: 20, color: "#00FF00" } }],
              })
            : null}
        </div>
        <div data-testid="tooltip-active-no-payload">
          {TooltipFn ? TooltipFn({ active: true, payload: [] }) : null}
        </div>
      </div>
    );
  },
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { StatsPanel } from "@/components/charts/StatsPanel";
import type { DashboardStats } from "@/types";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const emptyStats: DashboardStats = {
  total_solved: 0,
  difficulty_distribution: [],
  challenge_win_rate: 0,
  challenge_total: 0,
  challenge_wins: 0,
  total_tokens_earned: 0,
  total_tokens_spent: 0,
};

const statsWithData: DashboardStats = {
  total_solved: 50,
  difficulty_distribution: [
    { difficulty: "Easy", count: 20, color: "#00FF00" },
    { difficulty: "Medium", count: 20, color: "#FFA500" },
    { difficulty: "Hard", count: 10, color: "#FF0000" },
  ],
  challenge_win_rate: 65.5,
  challenge_total: 20,
  challenge_wins: 13,
  total_tokens_earned: 500,
  total_tokens_spent: 200,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StatsPanel", () => {
  it("renders empty state when no stats", () => {
    render(<StatsPanel stats={emptyStats} />);
    expect(screen.getByText("charts.noStats")).toBeInTheDocument();
  });

  it("renders total solved stat", () => {
    render(<StatsPanel stats={statsWithData} />);
    expect(screen.getByText("charts.totalSolved")).toBeInTheDocument();
    expect(screen.getByText("50")).toBeInTheDocument();
  });

  it("renders challenge win rate when challenges exist", () => {
    render(<StatsPanel stats={statsWithData} />);
    expect(screen.getByText("65.5%")).toBeInTheDocument();
  });

  it("renders dash for win rate when no challenges", () => {
    const stats = { ...emptyStats, total_solved: 10 };
    render(<StatsPanel stats={stats} />);
    expect(screen.getByText("-")).toBeInTheDocument();
  });

  it("renders tokens earned and spent", () => {
    render(<StatsPanel stats={statsWithData} />);
    expect(screen.getByText("charts.tokensEarned")).toBeInTheDocument();
    expect(screen.getByText("charts.tokensSpent")).toBeInTheDocument();
    expect(screen.getByText("500")).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
  });

  it("renders difficulty distribution when present", () => {
    render(<StatsPanel stats={statsWithData} />);
    expect(
      screen.getByText("charts.difficultyDistribution"),
    ).toBeInTheDocument();
    // Distribution items appear in both tooltip mock and distribution list
    expect(screen.getAllByText("Easy").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Medium").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Hard").length).toBeGreaterThanOrEqual(1);
  });

  // Covers StatCard with sub label (lines 41-42)
  it("renders stat card sub label when provided", () => {
    render(<StatsPanel stats={statsWithData} />);
    // Challenge win rate card has a sub label
    expect(screen.getByText("charts.winRateSub")).toBeInTheDocument();
  });

  // Covers no-difficulty-distribution path (lines 144-148)
  it("shows no stats message when difficulty distribution is empty", () => {
    const statsWithNoDist = { ...statsWithData, difficulty_distribution: [] };
    render(<StatsPanel stats={statsWithNoDist} />);
    // Should show the no-stats message inside the distribution section
    const noStatsMessages = screen.getAllByText("charts.noStats");
    expect(noStatsMessages.length).toBeGreaterThanOrEqual(1);
  });

  // Covers DifficultyTooltip: active=true with payload => renders difficulty and count
  it("DifficultyTooltip renders content when active with payload", () => {
    render(<StatsPanel stats={statsWithData} />);
    const activeTooltip = screen.getByTestId("tooltip-active");
    expect(activeTooltip).toHaveTextContent("Easy");
    expect(activeTooltip).toHaveTextContent("charts.solved");
  });

  // Covers DifficultyTooltip: active=false => returns null
  it("DifficultyTooltip returns null when not active", () => {
    render(<StatsPanel stats={statsWithData} />);
    const inactiveTooltip = screen.getByTestId("tooltip-inactive");
    expect(inactiveTooltip.innerHTML).toBe("");
  });

  // Covers DifficultyTooltip: active=true but no payload => returns null
  it("DifficultyTooltip returns null when active but no payload", () => {
    render(<StatsPanel stats={statsWithData} />);
    const noPayloadTooltip = screen.getByTestId("tooltip-active-no-payload");
    expect(noPayloadTooltip.innerHTML).toBe("");
  });
});
