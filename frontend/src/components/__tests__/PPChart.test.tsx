import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/utils", () => ({
  getRatingColor: (rating: number) => {
    if (rating >= 2400) return "#FF0000";
    return "#00FF00";
  },
}));

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  BarChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Bar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  XAxis: () => <div />,
  YAxis: () => <div />,
  CartesianGrid: () => <div />,
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
                payload: [{ value: 25.5, payload: { problem_name: "1920A", rating: 1500, pp: 25.5 } }],
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

import { PPChart } from "@/components/charts/PPChart";
import type { PPContributionItem } from "@/types";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const sampleData: PPContributionItem[] = [
  { problem_name: "1920A", rating: 1500, pp: 25.5 },
  { problem_name: "1900B", rating: 2400, pp: 40.0 },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("PPChart", () => {
  it("shows empty state when no data", () => {
    render(<PPChart data={[]} />);
    expect(
      screen.getByText("No PP records yet. Solve problems to build your profile!"),
    ).toBeInTheDocument();
  });

  it("renders chart title when data present", () => {
    render(<PPChart data={sampleData} />);
    expect(screen.getByText("Top PP Contributions")).toBeInTheDocument();
  });

  it("renders ResponsiveContainer when data present", () => {
    render(<PPChart data={sampleData} />);
    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });

  // Covers bar chart rendering with Cell map (lines 73-75)
  it("renders PP chart with high-rated problems", () => {
    const highRatedData: PPContributionItem[] = [
      { problem_name: "2400A", rating: 2400, pp: 50.0 },
      { problem_name: "2000B", rating: 2000, pp: 30.0 },
    ];
    render(<PPChart data={highRatedData} />);
    expect(screen.getByText("Top PP Contributions")).toBeInTheDocument();
    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });

  // Covers empty bar chart with single data point
  it("renders chart with single data point", () => {
    render(<PPChart data={[{ problem_name: "1920A", rating: 1500, pp: 25.5 }]} />);
    expect(screen.getByText("Top PP Contributions")).toBeInTheDocument();
  });

  // Covers the CustomTooltip branch by rendering with active=true via BarChart internals
  it("renders chart with multiple data points triggering tooltip logic", () => {
    const multiData: PPContributionItem[] = [
      { problem_name: "1920A", rating: 1500, pp: 25.5 },
      { problem_name: "1900B", rating: 2400, pp: 40.0 },
      { problem_name: "1800C", rating: 1800, pp: 35.0 },
    ];
    render(<PPChart data={multiData} />);
    expect(screen.getByText("Top PP Contributions")).toBeInTheDocument();
    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });

  // Covers CustomTooltip: active=true with payload => renders problem name and PP value
  it("CustomTooltip renders content when active with payload", () => {
    render(<PPChart data={sampleData} />);
    const activeTooltip = screen.getByTestId("tooltip-active");
    expect(activeTooltip).toHaveTextContent("1920A");
    expect(activeTooltip).toHaveTextContent("25.5");
  });

  // Covers CustomTooltip: active=false => returns null
  it("CustomTooltip returns null when not active", () => {
    render(<PPChart data={sampleData} />);
    const inactiveTooltip = screen.getByTestId("tooltip-inactive");
    expect(inactiveTooltip.innerHTML).toBe("");
  });

  // Covers CustomTooltip: active=true but no payload => returns null
  it("CustomTooltip returns null when active but no payload", () => {
    render(<PPChart data={sampleData} />);
    const noPayloadTooltip = screen.getByTestId("tooltip-active-no-payload");
    expect(noPayloadTooltip.innerHTML).toBe("");
  });
});
