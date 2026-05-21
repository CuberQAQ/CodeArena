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

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { MedalCabinet } from "@/components/medal/MedalCabinet";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MedalCabinet", () => {
  it("shows no medals message when stats is empty", () => {
    render(<MedalCabinet stats={{}} />);
    expect(screen.getByText("cabinet.noMedals")).toBeInTheDocument();
  });

  it("renders medal table with stats", () => {
    const stats = {
      regional: { gold: 2, silver: 1, bronze: 0 },
      provincial: { gold: 0, silver: 3, bronze: 1 },
    };

    render(<MedalCabinet stats={stats} />);
    expect(screen.getByText("cabinet.title")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    // Multiple "1" values exist (silver:1, bronze:1)
    const ones = screen.getAllByText("1");
    expect(ones.length).toBeGreaterThanOrEqual(2);
  });

  it("shows total medals when provided", () => {
    const stats = {
      regional: { gold: 1, silver: 0, bronze: 0 },
    };

    render(<MedalCabinet stats={stats} totalMedals={7} />);
    expect(screen.getByText(/7/)).toBeInTheDocument();
  });

  it("does not show total medals when not provided", () => {
    const stats = {
      regional: { gold: 1, silver: 0, bronze: 0 },
    };

    render(<MedalCabinet stats={stats} />);
    expect(screen.queryByText(/cabinet.totalMedals/)).not.toBeInTheDocument();
  });

  it("shows dash for zero medal counts", () => {
    const stats = {
      regional: { gold: 0, silver: 0, bronze: 0 },
    };

    render(<MedalCabinet stats={stats} />);
    const dashes = screen.getAllByText("-");
    expect(dashes.length).toBe(3);
  });

  it("applies custom className", () => {
    const { container } = render(
      <MedalCabinet stats={{}} className="custom" />,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root.classList.contains("custom")).toBe(true);
  });
});
