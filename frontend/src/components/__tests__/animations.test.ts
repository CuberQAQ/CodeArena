import { describe, it, expect } from "vitest";

// Verify barrel exports exist and are importable
import * as animations from "@/components/animations";

describe("animations barrel export", () => {
  it("exports EloChange", () => {
    expect(animations.EloChange).toBeDefined();
    expect(typeof animations.EloChange).toBe("function");
  });

  it("exports CoinAnimation", () => {
    expect(animations.CoinAnimation).toBeDefined();
    expect(typeof animations.CoinAnimation).toBe("function");
  });

  it("exports StreakEffect", () => {
    expect(animations.StreakEffect).toBeDefined();
    expect(typeof animations.StreakEffect).toBe("function");
  });

  it("exports LevelUpEffect", () => {
    expect(animations.LevelUpEffect).toBeDefined();
    expect(typeof animations.LevelUpEffect).toBe("function");
  });

  it("exports MatchWaiting", () => {
    expect(animations.MatchWaiting).toBeDefined();
    expect(typeof animations.MatchWaiting).toBe("function");
  });

  it("exports AcceptedCelebration", () => {
    expect(animations.AcceptedCelebration).toBeDefined();
    expect(typeof animations.AcceptedCelebration).toBe("function");
  });

  it("exports AchievementPopup", () => {
    expect(animations.AchievementPopup).toBeDefined();
    expect(typeof animations.AchievementPopup).toBe("function");
  });
});
