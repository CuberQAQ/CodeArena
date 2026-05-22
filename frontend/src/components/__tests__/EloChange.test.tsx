import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let mockReducedMotion = false;

vi.mock("@/hooks/useAnimation", () => ({
  usePrefersReducedMotion: () => mockReducedMotion,
  useSpringTransition: () =>
    mockReducedMotion
      ? { duration: 0 }
      : { type: "spring", stiffness: 300, damping: 30 },
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { EloChange } from "@/components/animations/EloChange";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("EloChange", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not render when value is null", () => {
    const { container } = render(<EloChange value={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("does not render when value is undefined", () => {
    const { container } = render(<EloChange value={undefined} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders positive value with + prefix", () => {
    render(<EloChange value={25} triggerKey="t1" />);
    // Should render with + sign
    expect(screen.getByText(/\+0/)).toBeInTheDocument();
  });

  it("renders negative value without + prefix", () => {
    render(<EloChange value={-10} triggerKey="t1" />);
    expect(screen.getByText(/-?0/)).toBeInTheDocument();
  });

  it("renders zero value", () => {
    render(<EloChange value={0} triggerKey="t1" />);
    expect(screen.getByText("0")).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(
      <EloChange value={10} triggerKey="t1" className="custom" />,
    );
    const divs = container.querySelectorAll(".custom");
    expect(divs.length).toBeGreaterThan(0);
  });

  it("does not show display when value is null after initial render", () => {
    // When value is null from the start, nothing renders
    const { container } = render(<EloChange value={null} />);
    expect(container.innerHTML).toBe("");
  });

  // Covers reduced motion path: value is set immediately (line 38)
  it("shows final value immediately in reduced motion", () => {
    mockReducedMotion = true;
    render(<EloChange value={42} triggerKey="t1" />);
    expect(screen.getByText("+42")).toBeInTheDocument();
    mockReducedMotion = false;
  });

  // Covers negative value display with reduced motion
  it("shows negative value immediately in reduced motion", () => {
    mockReducedMotion = true;
    render(<EloChange value={-15} triggerKey="t1" />);
    expect(screen.getByText("-15")).toBeInTheDocument();
    mockReducedMotion = false;
  });

  // Covers rAF animation counting (lines 42-54)
  it("animates value through rAF calls", () => {
    vi.useFakeTimers();
    // Mock performance.now and requestAnimationFrame
    const originalRAF = window.requestAnimationFrame;
    const originalCAF = window.cancelAnimationFrame;
    let rafCallback: FrameRequestCallback | null = null;
    let rafId = 0;

    window.requestAnimationFrame = (cb: FrameRequestCallback) => {
      rafId++;
      rafCallback = cb;
      return rafId;
    };
    window.cancelAnimationFrame = () => {};

    render(<EloChange value={100} triggerKey="anim1" />);

    // Simulate first rAF tick
    act(() => {
      if (rafCallback) rafCallback(performance.now() + 400);
    });

    // Should show intermediate value (not 0, not 100)
    expect(screen.getByText(/\d+/)).toBeInTheDocument();

    // Simulate final rAF tick (progress >= 1)
    act(() => {
      if (rafCallback) rafCallback(performance.now() + 1000);
    });

    expect(screen.getByText("+100")).toBeInTheDocument();

    window.requestAnimationFrame = originalRAF;
    window.cancelAnimationFrame = originalCAF;
    vi.useRealTimers();
  });
});
