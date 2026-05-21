import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { act } from "react";

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

import { AcceptedCelebration } from "@/components/animations/AcceptedCelebration";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AcceptedCelebration", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockReducedMotion = false;
  });

  afterEach(() => {
    vi.useRealTimers();
    mockReducedMotion = false;
  });

  it("renders nothing when not active", () => {
    render(<AcceptedCelebration active={false} />);
    expect(screen.queryByText("Accepted!")).not.toBeInTheDocument();
  });

  it("renders Accepted! text when active", () => {
    render(<AcceptedCelebration active={true} />);
    expect(screen.getByText("Accepted!")).toBeInTheDocument();
  });

  it("calls onComplete after duration", () => {
    const onComplete = vi.fn();
    render(
      <AcceptedCelebration active={true} onComplete={onComplete} duration={1000} />,
    );

    expect(onComplete).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("does not call onComplete when not active", () => {
    const onComplete = vi.fn();
    render(
      <AcceptedCelebration active={false} onComplete={onComplete} duration={1000} />,
    );

    act(() => {
      vi.advanceTimersByTime(2000);
    });

    expect(onComplete).not.toHaveBeenCalled();
  });

  it("applies custom className", () => {
    const { container } = render(
      <AcceptedCelebration active={true} className="my-overlay" />,
    );
    const divs = container.querySelectorAll(".my-overlay");
    expect(divs.length).toBeGreaterThan(0);
  });

  it("renders particle elements when active", () => {
    const { container } = render(<AcceptedCelebration active={true} />);
    // Particles are absolute positioned rounded-full divs
    const particles = container.querySelectorAll(".rounded-full");
    expect(particles.length).toBeGreaterThan(0);
  });

  // Covers line 71: reduced motion path sets empty particles
  it("does not render particles when reduced motion is enabled", () => {
    mockReducedMotion = true;
    const { container } = render(<AcceptedCelebration active={true} />);
    // In reduced motion, particles array is empty, so no rounded-full divs
    const particles = container.querySelectorAll(".rounded-full");
    expect(particles.length).toBe(0);
  });
});
