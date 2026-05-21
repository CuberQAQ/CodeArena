import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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
  default: { t: (key: string, params?: Record<string, unknown>) => {
    if (params) return `${key}-${Object.values(params).join(",")}`;
    return key;
  }, language: "en" },
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

import { EloChart } from "@/components/charts/EloChart";
import type { EloHistoryPoint } from "@/types";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const sampleData: EloHistoryPoint[] = [
  { date: "2025-01-01", elo: 1400, change: 0 },
  { date: "2025-01-02", elo: 1420, change: 20 },
  { date: "2025-01-03", elo: 1390, change: -30 },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EloChart", () => {
  it("shows empty state when no data", () => {
    render(<EloChart data={[]} />);
    expect(screen.getByText("charts.noEloHistory")).toBeInTheDocument();
  });

  it("renders chart title when data present", () => {
    render(<EloChart data={sampleData} />);
    expect(screen.getByText("charts.eloTrend")).toBeInTheDocument();
  });

  it("renders range selector buttons", () => {
    render(<EloChart data={sampleData} />);
    expect(screen.getByText("charts.7d")).toBeInTheDocument();
    expect(screen.getByText("charts.30d")).toBeInTheDocument();
    expect(screen.getByText("charts.all")).toBeInTheDocument();
  });

  it("switches range on button click", async () => {
    const user = userEvent.setup();
    render(<EloChart data={sampleData} />);

    await user.click(screen.getByText("charts.7d"));
    // Should not throw and chart still visible
    expect(screen.getByText("charts.eloTrend")).toBeInTheDocument();
  });

  it("renders ResponsiveContainer when data present", () => {
    render(<EloChart data={sampleData} />);
    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });

  // Covers 30d range button click (line 96 setRange)
  it("switches to 30d range on click", async () => {
    const user = userEvent.setup();
    render(<EloChart data={sampleData} />);

    await user.click(screen.getByText("charts.30d"));
    expect(screen.getByText("charts.eloTrend")).toBeInTheDocument();
  });

  // Covers "all" range (line 22: returns all points)
  it("switches to all range on click", async () => {
    const user = userEvent.setup();
    render(<EloChart data={sampleData} />);

    await user.click(screen.getByText("charts.all"));
    expect(screen.getByText("charts.eloTrend")).toBeInTheDocument();
  });

  // Covers elo domain with single point (edge case in useMemo)
  it("renders chart with single data point", () => {
    render(<EloChart data={[{ date: "2025-01-01", elo: 1500, change: 0 }]} />);
    expect(screen.getByText("charts.eloTrend")).toBeInTheDocument();
    expect(screen.getByTestId("responsive-container")).toBeInTheDocument();
  });
});
