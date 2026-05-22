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

import { MedalBadge } from "@/components/medal/MedalBadge";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MedalBadge", () => {
  it("renders unranked when no type provided", () => {
    render(<MedalBadge level="unranked" />);
    expect(screen.getByText("medal:levels.unranked")).toBeInTheDocument();
  });

  it("renders unranked when level is unranked", () => {
    render(<MedalBadge level="unranked" type="gold" />);
    expect(screen.getByText("medal:levels.unranked")).toBeInTheDocument();
  });

  it("renders gold medal with type and level", () => {
    render(<MedalBadge level="regional" type="gold" />);
    expect(screen.getByText(/medal:levels.regional/)).toBeInTheDocument();
    expect(screen.getByText(/medal:types.gold/)).toBeInTheDocument();
  });

  it("renders silver medal", () => {
    render(<MedalBadge level="provincial" type="silver" />);
    expect(screen.getByText(/medal:levels.provincial/)).toBeInTheDocument();
    expect(screen.getByText(/medal:types.silver/)).toBeInTheDocument();
  });

  it("renders bronze medal", () => {
    render(<MedalBadge level="world_finals" type="bronze" />);
    expect(screen.getByText(/medal:levels.worldFinals/)).toBeInTheDocument();
    expect(screen.getByText(/medal:types.bronze/)).toBeInTheDocument();
  });

  it("applies custom size", () => {
    render(
      <MedalBadge level="regional" type="gold" size="lg" />,
    );
    // lg uses text-sm for the label
    expect(screen.getByText(/medal:types.gold/)).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(
      <MedalBadge level="regional" type="gold" className="my-class" />,
    );
    const outer = container.firstElementChild as HTMLElement;
    expect(outer.classList.contains("my-class")).toBe(true);
  });
});
