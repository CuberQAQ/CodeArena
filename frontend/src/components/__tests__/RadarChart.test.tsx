import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  RadarChart: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PolarGrid: () => <div />,
  PolarAngleAxis: () => <div />,
  PolarRadiusAxis: () => <div />,
  Radar: () => <div />,
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
                payload: [{ value: 1500, payload: { topic: "DP", value: 1500, fullMark: 2000 } }],
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

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { RadarChart } from "@/components/charts/RadarChart";
import type { RadarDataPoint } from "@/types";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const sampleData: RadarDataPoint[] = [
  { topic: "DP", value: 1500, fullMark: 2000 },
  { topic: "Greedy", value: 1200, fullMark: 2000 },
  { topic: "Graphs", value: 800, fullMark: 2000 },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RadarChart", () => {
  it("shows empty state when no data", () => {
    render(<RadarChart data={[]} />);
    expect(
      screen.getByText("radar.empty"),
    ).toBeInTheDocument();
  });

  it("renders chart title when data present", () => {
    render(<RadarChart data={sampleData} />);
    expect(screen.getByText("radar.title")).toBeInTheDocument();
  });

  it("renders ResponsiveContainer when data present", () => {
    render(<RadarChart data={sampleData} />);
    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });

  // Covers lines 47-48: maxValue and fullMark calculation
  it("renders chart with high value data", () => {
    const highData: RadarDataPoint[] = [
      { topic: "DP", value: 2500, fullMark: 3000 },
      { topic: "Graphs", value: 1800, fullMark: 3000 },
    ];
    render(<RadarChart data={highData} />);
    expect(screen.getByText("radar.title")).toBeInTheDocument();
    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });

  // Covers single data point edge case
  it("renders chart with single data point", () => {
    render(<RadarChart data={[{ topic: "DP", value: 1000, fullMark: 2000 }]} />);
    expect(screen.getByText("radar.title")).toBeInTheDocument();
  });

  // Covers zero-value data point
  it("renders chart with zero value data point", () => {
    render(<RadarChart data={[{ topic: "DP", value: 0, fullMark: 2000 }]} />);
    expect(screen.getByText("radar.title")).toBeInTheDocument();
  });

  // Covers CustomTooltip: active=true with payload => renders topic and M-Elo
  it("CustomTooltip renders content when active with payload", () => {
    render(<RadarChart data={sampleData} />);
    const activeTooltip = screen.getByTestId("tooltip-active");
    expect(activeTooltip).toHaveTextContent("DP");
    expect(activeTooltip).toHaveTextContent("1500");
  });

  // Covers CustomTooltip: active=false => returns null
  it("CustomTooltip returns null when not active", () => {
    render(<RadarChart data={sampleData} />);
    const inactiveTooltip = screen.getByTestId("tooltip-inactive");
    expect(inactiveTooltip.innerHTML).toBe("");
  });

  // Covers CustomTooltip: active=true but no payload => returns null
  it("CustomTooltip returns null when active but no payload", () => {
    render(<RadarChart data={sampleData} />);
    const noPayloadTooltip = screen.getByTestId("tooltip-active-no-payload");
    expect(noPayloadTooltip.innerHTML).toBe("");
  });
});
