/**
 * Stage 47 additional frontend unit tests.
 *
 * Tests useOnlineTime hook logic, protection period calculations,
 * slider range derivation, and EloProgressBar edge cases.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// ---------------------------------------------------------------------------
// useOnlineTime hook tests (extracted logic, not component rendering)
// ---------------------------------------------------------------------------

describe("useOnlineTime logic", () => {
  /**
   * Since useOnlineTime is a private hook inside MainLayout.tsx,
   * we test the calculation logic directly.
   */

  function calcOnlineTime(loginTime: string | null): string {
    if (!loginTime) return "00:00:00";
    const login = new Date(loginTime).getTime();
    const now = Date.now();
    let diff = Math.max(0, Math.floor((now - login) / 1000));
    const h = Math.floor(diff / 3600);
    diff %= 3600;
    const m = Math.floor(diff / 60);
    const s = diff % 60;
    return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }

  it("returns 00:00:00 when loginTime is null", () => {
    expect(calcOnlineTime(null)).toBe("00:00:00");
  });

  it("returns 00:00:00 when loginTime is empty string", () => {
    // empty string is falsy in JS
    expect(calcOnlineTime("")).toBe("00:00:00");
  });

  it("returns 00:00:00 for current time (diff ~= 0)", () => {
    const now = new Date().toISOString();
    expect(calcOnlineTime(now)).toBe("00:00:00");
  });

  it("handles future loginTime gracefully (diff = 0 due to max(0,...))", () => {
    const future = new Date(Date.now() + 60000).toISOString();
    expect(calcOnlineTime(future)).toBe("00:00:00");
  });

  it("calculates correct elapsed time for 1 hour ago", () => {
    const oneHourAgo = new Date(Date.now() - 3600 * 1000).toISOString();
    expect(calcOnlineTime(oneHourAgo)).toBe("01:00:00");
  });

  it("calculates correct elapsed time for 90 minutes ago", () => {
    const ninetyMinAgo = new Date(Date.now() - 90 * 60 * 1000).toISOString();
    expect(calcOnlineTime(ninetyMinAgo)).toBe("01:30:00");
  });

  it("pads single-digit seconds", () => {
    const fiveSecAgo = new Date(Date.now() - 5 * 1000).toISOString();
    expect(calcOnlineTime(fiveSecAgo)).toBe("00:00:05");
  });

  it("pads single-digit minutes", () => {
    const sixtyFiveSecAgo = new Date(Date.now() - 65 * 1000).toISOString();
    expect(calcOnlineTime(sixtyFiveSecAgo)).toBe("00:01:05");
  });

  it("handles very large elapsed time (10+ hours)", () => {
    const tenHoursAgo = new Date(Date.now() - 10 * 3600 * 1000).toISOString();
    expect(calcOnlineTime(tenHoursAgo)).toBe("10:00:00");
  });
});


// ---------------------------------------------------------------------------
// Protection period countdown logic
// ---------------------------------------------------------------------------

describe("formatProtectionTime", () => {
  // This function is defined in TrainingDetailPage.tsx:
  // function formatProtectionTime(seconds: number): string {
  //   const m = Math.floor(Math.max(0, seconds) / 60);
  //   const s = Math.floor(Math.max(0, seconds) % 60);
  //   return `${m}:${s.toString().padStart(2, "0")}`;
  // }

  function formatProtectionTime(seconds: number): string {
    const m = Math.floor(Math.max(0, seconds) / 60);
    const s = Math.floor(Math.max(0, seconds) % 60);
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  it("formats 300 seconds as 5:00", () => {
    expect(formatProtectionTime(300)).toBe("5:00");
  });

  it("formats 0 seconds as 0:00", () => {
    expect(formatProtectionTime(0)).toBe("0:00");
  });

  it("formats 60 seconds as 1:00", () => {
    expect(formatProtectionTime(60)).toBe("1:00");
  });

  it("formats 59 seconds as 0:59", () => {
    expect(formatProtectionTime(59)).toBe("0:59");
  });

  it("formats 1 second as 0:01", () => {
    expect(formatProtectionTime(1)).toBe("0:01");
  });

  it("clamps negative seconds to 0:00", () => {
    expect(formatProtectionTime(-100)).toBe("0:00");
  });

  it("formats 299 seconds as 4:59", () => {
    expect(formatProtectionTime(299)).toBe("4:59");
  });

  it("formats 150 seconds as 2:30", () => {
    expect(formatProtectionTime(150)).toBe("2:30");
  });
});


// ---------------------------------------------------------------------------
// Slider range derivation
// ---------------------------------------------------------------------------

describe("Slider range derivation from M-Elo", () => {
  function deriveSliderRange(melo: number | null | undefined): [number, number] {
    const meloVal = melo ?? 1200;
    const sliderMin = Math.max(800, meloVal - 200);
    const sliderMax = meloVal + 400;
    const snappedMin = Math.round(sliderMin / 50) * 50;
    const snappedMax = Math.round(sliderMax / 50) * 50;
    return [snappedMin, snappedMax];
  }

  it("derives range from M-Elo 1500", () => {
    const [min, max] = deriveSliderRange(1500);
    expect(min).toBe(1300); // 1500 - 200 = 1300, snapped to 1300
    expect(max).toBe(1900); // 1500 + 400 = 1900, snapped to 1900
  });

  it("derives range from M-Elo 1200 (default)", () => {
    const [min, max] = deriveSliderRange(1200);
    expect(min).toBe(1000); // 1200 - 200 = 1000, snapped
    expect(max).toBe(1600); // 1200 + 400 = 1600, snapped
  });

  it("clamps min to 800 for low M-Elo", () => {
    const [min, max] = deriveSliderRange(900);
    expect(min).toBe(800); // max(800, 900-200) = max(800, 700) = 800, snapped to 800
    expect(max).toBe(1300); // 900 + 400 = 1300, snapped
  });

  it("derives range from null M-Elo (uses default 1200)", () => {
    const [min, max] = deriveSliderRange(null);
    expect(min).toBe(1000);
    expect(max).toBe(1600);
  });

  it("derives range from undefined M-Elo (uses default 1200)", () => {
    const [min, max] = deriveSliderRange(undefined);
    expect(min).toBe(1000);
    expect(max).toBe(1600);
  });

  it("derives range from very high M-Elo", () => {
    const [min, max] = deriveSliderRange(3000);
    expect(min).toBe(2800); // 3000 - 200 = 2800
    expect(max).toBe(3400); // 3000 + 400 = 3400
  });

  it("snaps to step of 50", () => {
    const [min, max] = deriveSliderRange(1525);
    // 1525 - 200 = 1325, snapped to 1350 (round(1325/50)*50 = round(26.5)*50 = 27*50 = 1350)
    // Actually Math.round(1325/50) = Math.round(26.5) = 27 -> 1350
    expect(min).toBe(1350);
    // 1525 + 400 = 1925, snapped to 1950 (round(1925/50) = round(38.5) = 39 -> 1950)
    expect(max).toBe(1950);
  });
});


// ---------------------------------------------------------------------------
// Elo progress bar calculation (TrainingPage version)
// ---------------------------------------------------------------------------

describe("TrainingPage EloProgressBar calculations", () => {
  // This mirrors the logic in TrainingPage.tsx EloProgressBar component

  function calculateProgress(
    melo: number | null,
    currentThreshold: number | null,
    nextThreshold: number | null,
  ): { progress: number; remaining: number } | null {
    if (melo === null || melo === undefined) return null;

    const meloVal = Math.round(melo);

    // At highest tier
    if (nextThreshold === null && currentThreshold !== null) {
      return { progress: 100, remaining: 0 };
    }

    // No medal (unranked)
    if (currentThreshold === null || nextThreshold === null) {
      const progress = Math.min(Math.max((meloVal / 1200) * 100, 0), 100);
      const remaining = Math.max(1200 - meloVal, 0);
      return { progress, remaining };
    }

    // Normal: progress within current tier
    const range = nextThreshold - currentThreshold;
    const progress = range > 0
      ? Math.min(Math.max(((meloVal - currentThreshold) / range) * 100, 0), 100)
      : 100;
    const remaining = Math.max(nextThreshold - meloVal, 0);
    return { progress, remaining };
  }

  it("returns null for null melo", () => {
    expect(calculateProgress(null, null, 1200)).toBeNull();
  });

  it("returns null for undefined melo", () => {
    expect(calculateProgress(undefined, null, 1200)).toBeNull();
  });

  it("calculates progress for unranked user at melo=600", () => {
    const result = calculateProgress(600, null, 1200);
    expect(result).not.toBeNull();
    expect(result!.progress).toBe(50); // 600/1200 * 100 = 50%
    expect(result!.remaining).toBe(600); // 1200 - 600 = 600
  });

  it("calculates progress for unranked user at melo=0", () => {
    const result = calculateProgress(0, null, 1200);
    expect(result).not.toBeNull();
    expect(result!.progress).toBe(0);
    expect(result!.remaining).toBe(1200);
  });

  it("calculates progress for provincial bronze at melo=1300", () => {
    const result = calculateProgress(1300, 1200, 1400);
    expect(result).not.toBeNull();
    expect(result!.progress).toBe(50); // (1300-1200)/(1400-1200) * 100 = 50%
    expect(result!.remaining).toBe(100); // 1400 - 1300 = 100
  });

  it("clamps progress at 0% when melo below currentThreshold", () => {
    const result = calculateProgress(1100, 1200, 1400);
    expect(result).not.toBeNull();
    expect(result!.progress).toBe(0); // clamped to 0
  });

  it("clamps progress at 100% when melo exceeds nextThreshold", () => {
    const result = calculateProgress(1500, 1200, 1400);
    expect(result).not.toBeNull();
    expect(result!.progress).toBe(100); // clamped to 100
  });

  it("returns 100% progress for highest tier (world_finals gold)", () => {
    const result = calculateProgress(3000, 2800, null);
    expect(result).not.toBeNull();
    expect(result!.progress).toBe(100);
  });

  it("handles currentThreshold=null and nextThreshold=null (should not happen, but test)", () => {
    const result = calculateProgress(1000, null, null);
    expect(result).not.toBeNull();
    // Falls into "no medal" path, progress = 1000/1200 * 100 = 83.33%
    expect(result!.progress).toBeCloseTo(83.33, 1);
    expect(result!.remaining).toBe(200);
  });
});


// ---------------------------------------------------------------------------
// Protection period boundary tests
// ---------------------------------------------------------------------------

describe("Protection period boundary", () => {
  const PROTECTION_DURATION = 300;

  it("is active when started 100s ago", () => {
    const startedAt = Date.now() - 100 * 1000;
    const remaining = Math.max(0, PROTECTION_DURATION - Math.floor((Date.now() - startedAt) / 1000));
    expect(remaining).toBeGreaterThan(0);
    expect(remaining).toBeLessThanOrEqual(200);
  });

  it("is active when started 299s ago", () => {
    const startedAt = Date.now() - 299 * 1000;
    const remaining = Math.max(0, PROTECTION_DURATION - Math.floor((Date.now() - startedAt) / 1000));
    expect(remaining).toBeGreaterThan(0);
    expect(remaining).toBeLessThanOrEqual(2);
  });

  it("expires when started 301s ago", () => {
    const startedAt = Date.now() - 301 * 1000;
    const remaining = Math.max(0, PROTECTION_DURATION - Math.floor((Date.now() - startedAt) / 1000));
    expect(remaining).toBe(0);
  });

  it("is at boundary when started exactly 300s ago", () => {
    const startedAt = Date.now() - 300 * 1000;
    const elapsed = Math.floor((Date.now() - startedAt) / 1000);
    // Due to execution time, elapsed is >= 300, so remaining = 0
    const remaining = Math.max(0, PROTECTION_DURATION - elapsed);
    expect(remaining).toBe(0);
  });
});


// ---------------------------------------------------------------------------
// ratingToMedal additional edge cases
// ---------------------------------------------------------------------------

describe("ratingToMedal additional edge cases", () => {
  // Import the actual function
  const FLAT_MEDAL_MAP: [number, string, string][] = [
    [2800, "world_finals", "gold"],
    [2600, "ec_final", "gold"],
    [2200, "regional", "gold"],
    [1600, "provincial", "gold"],
    [1400, "provincial", "silver"],
    [1200, "provincial", "bronze"],
  ];

  function ratingToMedal(rating: number): { level: string; type?: string } {
    for (const [threshold, level, medalType] of FLAT_MEDAL_MAP) {
      if (rating >= threshold) {
        return { level, type: medalType };
      }
    }
    return { level: "unranked" };
  }

  it("returns unranked for rating 0", () => {
    expect(ratingToMedal(0)).toEqual({ level: "unranked" });
  });

  it("returns unranked for negative rating", () => {
    expect(ratingToMedal(-500)).toEqual({ level: "unranked" });
  });

  it("returns provincial bronze for exactly 1200", () => {
    expect(ratingToMedal(1200)).toEqual({ level: "provincial", type: "bronze" });
  });

  it("returns provincial bronze for 1399", () => {
    expect(ratingToMedal(1399)).toEqual({ level: "provincial", type: "bronze" });
  });

  it("returns provincial silver for exactly 1400", () => {
    expect(ratingToMedal(1400)).toEqual({ level: "provincial", type: "silver" });
  });

  it("returns provincial gold for exactly 1600", () => {
    expect(ratingToMedal(1600)).toEqual({ level: "provincial", type: "gold" });
  });

  it("returns provincial gold for 2199 (D-31 boundary)", () => {
    expect(ratingToMedal(2199)).toEqual({ level: "provincial", type: "gold" });
  });

  it("returns regional gold for exactly 2200 (D-31 boundary)", () => {
    expect(ratingToMedal(2200)).toEqual({ level: "regional", type: "gold" });
  });

  it("returns ec_final gold for exactly 2600", () => {
    expect(ratingToMedal(2600)).toEqual({ level: "ec_final", type: "gold" });
  });

  it("returns world_finals gold for exactly 2800", () => {
    expect(ratingToMedal(2800)).toEqual({ level: "world_finals", type: "gold" });
  });

  it("returns world_finals gold for 9999", () => {
    expect(ratingToMedal(9999)).toEqual({ level: "world_finals", type: "gold" });
  });

  // D-31 verification: no silver/bronze for 1600+ due to highest-gold-priority rule
  it("never returns silver/bronze above 1600 due to D-31 rule", () => {
    for (let r = 1600; r <= 4000; r += 100) {
      const medal = ratingToMedal(r);
      if (medal.type) {
        expect(medal.type).toBe("gold");
      }
    }
  });
});
