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
});
