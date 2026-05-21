import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("recharts", async () => {
  const OriginalModule = await vi.importActual<typeof import("recharts")>("recharts");
  return {
    ...OriginalModule,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="responsive-container">{children}</div>
    ),
  };
});

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
      screen.getByText("No M-Elo data yet. Start training to build your skill profile!"),
    ).toBeInTheDocument();
  });

  it("renders chart title when data present", () => {
    render(<RadarChart data={sampleData} />);
    expect(screen.getByText("Skill Radar")).toBeInTheDocument();
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
    expect(screen.getByText("Skill Radar")).toBeInTheDocument();
    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });

  // Covers single data point edge case
  it("renders chart with single data point", () => {
    render(<RadarChart data={[{ topic: "DP", value: 1000, fullMark: 2000 }]} />);
    expect(screen.getByText("Skill Radar")).toBeInTheDocument();
  });

  // Covers zero-value data point
  it("renders chart with zero value data point", () => {
    render(<RadarChart data={[{ topic: "DP", value: 0, fullMark: 2000 }]} />);
    expect(screen.getByText("Skill Radar")).toBeInTheDocument();
  });
});
