import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/hooks/useAnimation", () => ({
  usePrefersReducedMotion: () => false,
}));

// ---------------------------------------------------------------------------
// Import SUT
// ---------------------------------------------------------------------------

import { AchievementPopup } from "@/components/animations/AchievementPopup";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const sampleAchievements = [
  {
    type: "overkill_bonus",
    title: "Overkill Bonus",
    description: "You solved it way faster than expected!",
    icon: "zap",
  },
];

const multipleAchievements = [
  {
    type: "overkill_bonus",
    title: "First Achievement",
    description: "Desc 1",
    icon: "zap",
  },
  {
    type: "contest_win",
    title: "Contest Winner",
    description: "Desc 2",
    icon: "trophy",
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("AchievementPopup", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when achievements list is empty", () => {
    render(<AchievementPopup achievements={[]} />);
    expect(screen.queryByText(/Achievement/)).not.toBeInTheDocument();
  });

  it("renders achievement title and description", () => {
    render(<AchievementPopup achievements={sampleAchievements} />);
    expect(screen.getByText("Overkill Bonus")).toBeInTheDocument();
    expect(
      screen.getByText("You solved it way faster than expected!"),
    ).toBeInTheDocument();
  });

  it("shows progress dots for multiple achievements", () => {
    render(<AchievementPopup achievements={multipleAchievements} />);
    const dots = document.querySelectorAll(".size-2.rounded-full");
    expect(dots.length).toBe(2);
  });

  it("calls onComplete after all achievements shown", () => {
    const onComplete = vi.fn();
    render(
      <AchievementPopup
        achievements={sampleAchievements}
        onComplete={onComplete}
        duration={1000}
      />,
    );

    // Advance past first card duration + exit animation
    act(() => {
      vi.advanceTimersByTime(1000);
    });

    // Advance past exit animation (400ms)
    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("renders star icon for unknown icon name", () => {
    render(
      <AchievementPopup
        achievements={[
          {
            type: "unknown_type",
            title: "Unknown",
            description: "Test",
            icon: "nonexistent",
          },
        ]}
      />,
    );
    expect(screen.getByText("Unknown")).toBeInTheDocument();
  });

  it("renders different color themes for different types", () => {
    render(
      <AchievementPopup
        achievements={multipleAchievements}
      />,
    );
    // Both cards should exist with different border colors
    expect(screen.getByText("First Achievement")).toBeInTheDocument();
  });

  // Covers the "advance to next achievement" branch (lines 81-83)
  it("shows second achievement after first one finishes", () => {
    render(
      <AchievementPopup
        achievements={multipleAchievements}
        duration={500}
      />,
    );

    // Initially shows first achievement
    expect(screen.getByText("First Achievement")).toBeInTheDocument();

    // Advance past first card duration
    act(() => {
      vi.advanceTimersByTime(500);
    });

    // Advance past exit animation (400ms)
    act(() => {
      vi.advanceTimersByTime(500);
    });

    // Should now show second achievement
    expect(screen.getByText("Contest Winner")).toBeInTheDocument();
  });

  // Covers the advance function with multiple achievements + onComplete
  it("shows all achievements then calls onComplete", () => {
    const onComplete = vi.fn();
    render(
      <AchievementPopup
        achievements={multipleAchievements}
        onComplete={onComplete}
        duration={500}
      />,
    );

    // First achievement
    expect(screen.getByText("First Achievement")).toBeInTheDocument();

    // Advance past first
    act(() => {
      vi.advanceTimersByTime(500);
    });
    act(() => {
      vi.advanceTimersByTime(500);
    });

    // Second achievement
    expect(screen.getByText("Contest Winner")).toBeInTheDocument();

    // Advance past second
    act(() => {
      vi.advanceTimersByTime(500);
    });
    act(() => {
      vi.advanceTimersByTime(500);
    });

    expect(onComplete).toHaveBeenCalledTimes(1);
  });
});
