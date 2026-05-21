import { describe, it, expect, vi } from "vitest";
import { render, screen, rerender } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let mockReducedMotion = false;

vi.mock("@/hooks/useAnimation", () => ({
  usePrefersReducedMotion: () => mockReducedMotion,
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { StreakEffect } from "@/components/animations/StreakEffect";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StreakEffect", () => {
  it("renders streak count 0", () => {
    render(<StreakEffect streak={0} />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("renders streak count", () => {
    render(<StreakEffect streak={5} />);
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("renders flame icon", () => {
    const { container } = render(<StreakEffect streak={3} />);
    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(
      <StreakEffect streak={1} className="my-class" />,
    );
    // The streak content div should have the class
    const divs = container.querySelectorAll(".my-class");
    expect(divs.length).toBeGreaterThan(0);
  });

  it("shows grey flame at streak 0", () => {
    const { container } = render(<StreakEffect streak={0} />);
    const svg = container.querySelector("svg") as SVGElement;
    expect(svg.style.color).toBe("rgb(136, 136, 136)"); // #888
  });

  it("shows yellow flame at streak 2", () => {
    const { container } = render(<StreakEffect streak={2} />);
    const svg = container.querySelector("svg") as SVGElement;
    expect(svg.style.color).toBe("rgb(255, 187, 0)"); // #FFBB00
  });

  it("shows orange flame at streak 4", () => {
    const { container } = render(<StreakEffect streak={4} />);
    const svg = container.querySelector("svg") as SVGElement;
    expect(svg.style.color).toBe("rgb(255, 140, 0)"); // #FF8C00
  });

  it("shows red flame at streak 6", () => {
    const { container } = render(<StreakEffect streak={6} />);
    const svg = container.querySelector("svg") as SVGElement;
    expect(svg.style.color).toBe("rgb(255, 60, 0)"); // #FF3C00
  });

  // Covers pulsing animation when streak increases (lines 42-48, 61-72)
  it("shows pulse glow when streak increases from lower value", () => {
    vi.useFakeTimers();
    const { container, rerender } = render(<StreakEffect streak={1} />);
    // Increase streak to trigger pulse
    rerender(<StreakEffect streak={3} />);
    // The glow div should be rendered (motion.div with fixed inset-0)
    const glowDiv = container.querySelector(".fixed.inset-0");
    expect(glowDiv).toBeInTheDocument();
    vi.useRealTimers();
  });

  // Covers line 77-84: reduced motion animation path
  it("renders without pulse animation in reduced motion", () => {
    mockReducedMotion = true;
    vi.useFakeTimers();
    render(<StreakEffect streak={3} />);
    expect(screen.getByText("3")).toBeInTheDocument();
    vi.useRealTimers();
    mockReducedMotion = false;
  });

  // Covers text shadow branch (line 116-118): intensity > 3 && !reduced
  it("applies text shadow at high streak values", () => {
    const { container } = render(<StreakEffect streak={5} />);
    // The span with text shadow is inside the motion.div
    const spans = container.querySelectorAll("span");
    let foundTextShadow = false;
    for (const span of spans) {
      if (span.textContent === "5" && span.style.textShadow && span.style.textShadow !== "none") {
        foundTextShadow = true;
        break;
      }
    }
    expect(foundTextShadow).toBe(true);
  });

  // Covers text shadow "none" branch
  it("does not apply text shadow at low streak values", () => {
    const { container } = render(<StreakEffect streak={1} />);
    const span = screen.getByText("1");
    expect(span.style.textShadow).toBe("none");
  });
});
