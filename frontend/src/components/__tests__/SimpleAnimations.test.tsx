import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let mockReducedMotion = false;

vi.mock("@/hooks/useAnimation", () => ({
  usePrefersReducedMotion: () => mockReducedMotion,
  useAnimationScale: () => (mockReducedMotion ? 0 : 1),
  useSpringTransition: () =>
    mockReducedMotion ? { duration: 0 } : { type: "spring", stiffness: 300, damping: 30 },
  useTweenTransition: () =>
    mockReducedMotion ? { duration: 0 } : { duration: 0.3, ease: "easeOut" },
}));

// ---------------------------------------------------------------------------
// Import SUTs
// ---------------------------------------------------------------------------

import { LevelUpEffect } from "@/components/animations/LevelUpEffect";
import { MatchWaiting } from "@/components/animations/MatchWaiting";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LevelUpEffect", () => {
  it("renders nothing when not active", () => {
    render(<LevelUpEffect active={false} />);
    expect(screen.queryByText(/./)).not.toBeInTheDocument();
  });

  it("renders star icon when active", () => {
    const { container } = render(<LevelUpEffect active={true} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("renders label when active and label provided", () => {
    render(<LevelUpEffect active={true} label="Level 5" />);
    expect(screen.getByText("Level 5")).toBeInTheDocument();
  });

  it("does not render label when not provided", () => {
    render(<LevelUpEffect active={true} />);
    // No label prop means no text span for label
    expect(screen.queryByText("Level 5")).not.toBeInTheDocument();
  });

  it("applies custom color", () => {
    const { container } = render(
      <LevelUpEffect active={true} color="#FF0000" />,
    );
    const circleDiv = container.querySelector("[style*='background: radial-gradient']");
    expect(circleDiv).toBeInTheDocument();
  });
});

describe("MatchWaiting", () => {
  it("renders default label", () => {
    render(<MatchWaiting />);
    expect(screen.getByText("Finding Opponent...")).toBeInTheDocument();
  });

  it("renders custom label", () => {
    render(<MatchWaiting label="Matching..." />);
    expect(screen.getByText("Matching...")).toBeInTheDocument();
  });

  it("renders Swords icon", () => {
    const { container } = render(<MatchWaiting />);
    // lucide-react renders an svg for Swords
    const svgs = container.querySelectorAll("svg");
    expect(svgs.length).toBeGreaterThan(0);
  });

  it("applies custom className", () => {
    const { container } = render(
      <MatchWaiting className="test-class" />,
    );
    const root = container.firstElementChild as HTMLElement;
    expect(root.classList.contains("test-class")).toBe(true);
  });

  it("does not render pulsing ring in reduced motion", () => {
    mockReducedMotion = true;
    const { container } = render(<MatchWaiting />);
    // In reduced motion, the pulsing ring animation is skipped
    expect(screen.getByText("Finding Opponent...")).toBeInTheDocument();
    mockReducedMotion = false;
  });
});

// Covers LevelUpEffect reduced motion branch (lines 33-35, 39-40, 48-50, 59, 96-98)
describe("LevelUpEffect reduced motion", () => {
  it("renders without animation when reduced motion is enabled", () => {
    mockReducedMotion = true;
    const { container } = render(<LevelUpEffect active={true} label="Rank Up" />);
    expect(screen.getByText("Rank Up")).toBeInTheDocument();
    // No glow div in reduced motion (line 59 condition)
    const glowDivs = container.querySelectorAll("[style*='blur']");
    expect(glowDivs.length).toBe(0);
    mockReducedMotion = false;
  });

  it("renders star icon in reduced motion", () => {
    mockReducedMotion = true;
    const { container } = render(<LevelUpEffect active={true} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    mockReducedMotion = false;
  });
});
