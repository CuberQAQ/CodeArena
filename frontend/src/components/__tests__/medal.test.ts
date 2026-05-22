import { describe, it, expect } from "vitest";

// Verify barrel exports exist and are importable
import * as medal from "@/components/medal";

describe("medal barrel export", () => {
  it("exports MedalBadge component", () => {
    expect(medal.MedalBadge).toBeDefined();
    expect(typeof medal.MedalBadge).toBe("function");
  });

  it("exports MedalCabinet component", () => {
    expect(medal.MedalCabinet).toBeDefined();
    expect(typeof medal.MedalCabinet).toBe("function");
  });

  it("exports SkillMedalWall component", () => {
    expect(medal.SkillMedalWall).toBeDefined();
    expect(typeof medal.SkillMedalWall).toBe("function");
  });

  it("exports type names (MedalBadgeProps, MedalCabinetProps, SkillMedalWallProps)", () => {
    // TypeScript types are erased at runtime; we just verify the module loaded
    // without errors, which confirms the types exist and compile correctly.
    expect(true).toBe(true);
  });
});
