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
});
