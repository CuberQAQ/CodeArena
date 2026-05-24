import { describe, it, expect } from "vitest";
import {
  getRatingTierInfo,
  getRatingColor,
  getDifficultyLabel,
  getDifficultyLabelKey,
  formatTime,
  formatDate,
  extractApiError,
  ratingToMedal,
  stripIndexPrefix,
  getNextRankName,
  RATING_TIERS,
} from "../index";

// ---------------------------------------------------------------------------
// getRatingTierInfo
// ---------------------------------------------------------------------------

describe("getRatingTierInfo", () => {
  it("returns Newbie for rating 1199", () => {
    const tier = getRatingTierInfo(1199);
    expect(tier.name).toBe("Newbie");
  });

  it("returns Pupil for rating 1200", () => {
    const tier = getRatingTierInfo(1200);
    expect(tier.name).toBe("Pupil");
  });

  it("returns Grandmaster for rating 2400", () => {
    const tier = getRatingTierInfo(2400);
    expect(tier.name).toBe("Grandmaster");
  });

  it("returns Legendary Grandmaster for rating 3000", () => {
    const tier = getRatingTierInfo(3000);
    expect(tier.name).toBe("Legendary Grandmaster");
    expect(tier.legendary).toBe(true);
  });

  it("returns Newbie for null", () => {
    const tier = getRatingTierInfo(null);
    expect(tier.name).toBe("Newbie");
  });

  it("returns Newbie for undefined", () => {
    const tier = getRatingTierInfo(undefined);
    expect(tier.name).toBe("Newbie");
  });

  it("returns Specialist for 1400", () => {
    const tier = getRatingTierInfo(1400);
    expect(tier.name).toBe("Specialist");
  });

  it("returns Expert for 1600", () => {
    const tier = getRatingTierInfo(1600);
    expect(tier.name).toBe("Expert");
  });

  it("returns Candidate Master for 1900", () => {
    const tier = getRatingTierInfo(1900);
    expect(tier.name).toBe("Candidate Master");
  });

  it("returns Master for 2100", () => {
    const tier = getRatingTierInfo(2100);
    expect(tier.name).toBe("Master");
  });

  it("returns International Master for 2300", () => {
    const tier = getRatingTierInfo(2300);
    expect(tier.name).toBe("International Master");
  });

  it("returns International Grandmaster for 2600", () => {
    const tier = getRatingTierInfo(2600);
    expect(tier.name).toBe("International Grandmaster");
  });

  it("returns correct boundary for upper edge of each tier", () => {
    // Test boundary values at tier edges
    expect(getRatingTierInfo(1399).name).toBe("Pupil");
    expect(getRatingTierInfo(1599).name).toBe("Specialist");
    expect(getRatingTierInfo(1899).name).toBe("Expert");
    expect(getRatingTierInfo(2099).name).toBe("Candidate Master");
    expect(getRatingTierInfo(2299).name).toBe("Master");
    expect(getRatingTierInfo(2399).name).toBe("International Master");
    expect(getRatingTierInfo(2599).name).toBe("Grandmaster");
    expect(getRatingTierInfo(2999).name).toBe("International Grandmaster");
  });
});

// ---------------------------------------------------------------------------
// getRatingColor
// ---------------------------------------------------------------------------

describe("getRatingColor", () => {
  it("returns gray (#808080) for Newbie", () => {
    expect(getRatingColor(800)).toBe("#808080");
  });

  it("returns green (#008000) for Pupil", () => {
    expect(getRatingColor(1200)).toBe("#008000");
  });

  it("returns cyan (#03A89E) for Specialist", () => {
    expect(getRatingColor(1400)).toBe("#03A89E");
  });

  it("returns blue (#0000FF) for Expert", () => {
    expect(getRatingColor(1600)).toBe("#0000FF");
  });

  it("returns purple (#AA00AA) for Candidate Master", () => {
    expect(getRatingColor(1900)).toBe("#AA00AA");
  });

  it("returns orange (#FF8C00) for Master", () => {
    expect(getRatingColor(2100)).toBe("#FF8C00");
  });

  it("returns orange (#FF8C00) for International Master", () => {
    expect(getRatingColor(2300)).toBe("#FF8C00");
  });

  it("returns red (#FF0000) for Grandmaster", () => {
    expect(getRatingColor(2400)).toBe("#FF0000");
  });

  it("returns red (#FF0000) for International Grandmaster", () => {
    expect(getRatingColor(2600)).toBe("#FF0000");
  });

  it("returns red (#FF0000) for Legendary Grandmaster", () => {
    expect(getRatingColor(3000)).toBe("#FF0000");
  });

  it("returns gray for null/undefined", () => {
    expect(getRatingColor(null)).toBe("#808080");
    expect(getRatingColor(undefined)).toBe("#808080");
  });
});

// ---------------------------------------------------------------------------
// getDifficultyLabel
// ---------------------------------------------------------------------------

describe("getDifficultyLabel", () => {
  it("returns 'Unrated' for null", () => {
    expect(getDifficultyLabel(null)).toBe("Unrated");
  });

  it("returns 'Unrated' for undefined", () => {
    expect(getDifficultyLabel(undefined)).toBe("Unrated");
  });

  it("returns the tier name for a valid rating", () => {
    expect(getDifficultyLabel(1200)).toBe("Pupil");
    expect(getDifficultyLabel(2400)).toBe("Grandmaster");
  });
});

// ---------------------------------------------------------------------------
// formatTime
// ---------------------------------------------------------------------------

describe("formatTime", () => {
  it("formats 3661 seconds as 1:01:01", () => {
    expect(formatTime(3661)).toBe("1:01:01");
  });

  it("formats 125 seconds as 02:05", () => {
    expect(formatTime(125)).toBe("02:05");
  });

  it("formats 0 seconds as 00:00", () => {
    expect(formatTime(0)).toBe("00:00");
  });

  it("formats 59 seconds as 00:59", () => {
    expect(formatTime(59)).toBe("00:59");
  });

  it("formats exactly 1 hour as 1:00:00", () => {
    expect(formatTime(3600)).toBe("1:00:00");
  });

  it("formats 10 hours as 10:00:00", () => {
    expect(formatTime(36000)).toBe("10:00:00");
  });

  it("pads single-digit minutes in hour format", () => {
    expect(formatTime(3665)).toBe("1:01:05");
  });
});

// ---------------------------------------------------------------------------
// extractApiError
// ---------------------------------------------------------------------------

describe("extractApiError", () => {
  it("extracts error.message from business error response", () => {
    const err = {
      response: {
        data: {
          error: { code: "BUSINESS_ERROR", message: "Insufficient tokens" },
        },
      },
    };
    expect(extractApiError(err)).toBe("Insufficient tokens");
  });

  it("extracts detail for VALIDATION_ERROR", () => {
    const err = {
      response: {
        data: {
          error: { code: "VALIDATION_ERROR", message: "Validation failed" },
          detail: "body -> password: String should have at least 8 characters",
        },
      },
    };
    expect(extractApiError(err)).toBe(
      "body -> password: String should have at least 8 characters",
    );
  });

  it("prefers error.message over detail for non-validation errors", () => {
    const err = {
      response: {
        data: {
          error: { code: "SOME_ERROR", message: "Business error message" },
          detail: "Some detail",
        },
      },
    };
    expect(extractApiError(err)).toBe("Business error message");
  });

  it("returns detail as fallback when no error.message", () => {
    const err = {
      response: {
        data: {
          error: { code: "SOME_ERROR" },
          detail: "Detail fallback",
        },
      },
    };
    expect(extractApiError(err)).toBe("Detail fallback");
  });

  it("returns fallback string when nothing else matches", () => {
    expect(extractApiError({})).toBe("An unexpected error occurred");
  });

  it("returns custom fallback when provided", () => {
    expect(extractApiError({}, "Custom fallback")).toBe("Custom fallback");
  });

  it("handles null/undefined response data", () => {
    expect(extractApiError({ response: {} })).toBe("An unexpected error occurred");
    expect(extractApiError({ response: { data: null } })).toBe(
      "An unexpected error occurred",
    );
  });
});

// ---------------------------------------------------------------------------
// RATING_TIERS constant integrity
// ---------------------------------------------------------------------------

describe("RATING_TIERS", () => {
  it("has exactly 10 tiers", () => {
    expect(RATING_TIERS).toHaveLength(10);
  });

  it("first tier has min -Infinity", () => {
    expect(RATING_TIERS[0].min).toBe(-Infinity);
  });

  it("last tier has legendary flag", () => {
    expect(RATING_TIERS[RATING_TIERS.length - 1].legendary).toBe(true);
  });

  it("only last tier has legendary flag", () => {
    const legendaryCount = RATING_TIERS.filter((t) => t.legendary).length;
    expect(legendaryCount).toBe(1);
  });

  it("tiers are in ascending order by min", () => {
    for (let i = 1; i < RATING_TIERS.length; i++) {
      expect(RATING_TIERS[i].min).toBeGreaterThan(RATING_TIERS[i - 1].min);
    }
  });
});

// ---------------------------------------------------------------------------
// getDifficultyLabelKey
// ---------------------------------------------------------------------------

describe("getDifficultyLabelKey", () => {
  it("returns unrated key for null", () => {
    expect(getDifficultyLabelKey(null)).toBe("rating:unrated");
  });

  it("returns unrated key for undefined", () => {
    expect(getDifficultyLabelKey(undefined)).toBe("rating:unrated");
  });

  it("returns correct i18n key for Pupil rating", () => {
    expect(getDifficultyLabelKey(1200)).toBe("rating:pupil");
  });

  it("returns correct i18n key for Expert rating", () => {
    expect(getDifficultyLabelKey(1600)).toBe("rating:expert");
  });

  it("returns correct i18n key for Grandmaster rating", () => {
    expect(getDifficultyLabelKey(2400)).toBe("rating:grandmaster");
  });
});

// ---------------------------------------------------------------------------
// formatDate
// ---------------------------------------------------------------------------

describe("formatDate", () => {
  it("returns dash for null", () => {
    expect(formatDate(null)).toBe("-");
  });

  it("returns dash for undefined", () => {
    expect(formatDate(undefined)).toBe("-");
  });

  it("returns dash for empty string", () => {
    expect(formatDate("")).toBe("-");
  });

  it("formats a valid date string in English", () => {
    const result = formatDate("2025-06-15T10:30:00Z", "en-US");
    expect(result).toContain("2025");
    expect(result).toContain("Jun");
  });

  it("formats a valid date string in Chinese", () => {
    const result = formatDate("2025-06-15T10:30:00Z", "zh-CN");
    expect(result).toContain("2025");
  });

  it("formats without explicit locale (uses default)", () => {
    const result = formatDate("2025-06-15T10:30:00Z");
    expect(result).toBeTruthy();
    expect(result).not.toBe("-");
  });
});

// ---------------------------------------------------------------------------
// ratingToMedal
// ---------------------------------------------------------------------------

describe("ratingToMedal", () => {
  // Mirrors backend MedalService._FLAT_MEDAL_MAP exactly:
  // 2800+ -> world_finals/gold, 2600+ -> ec_final/gold, 2200+ -> regional/gold,
  // 1600+ -> provincial/gold, 1400+ -> provincial/silver, 1200+ -> provincial/bronze, <1200 -> unranked

  it("returns unranked for low rating", () => {
    expect(ratingToMedal(1000)).toEqual({ level: "unranked" });
  });

  it("returns unranked just below 1200", () => {
    expect(ratingToMedal(1199)).toEqual({ level: "unranked" });
  });

  it("returns provincial bronze at 1200", () => {
    expect(ratingToMedal(1200)).toEqual({ level: "provincial", type: "bronze" });
  });

  it("returns provincial silver at 1400", () => {
    expect(ratingToMedal(1400)).toEqual({ level: "provincial", type: "silver" });
  });

  it("returns provincial gold at 1600", () => {
    expect(ratingToMedal(1600)).toEqual({ level: "provincial", type: "gold" });
  });

  it("returns provincial gold at 1800", () => {
    expect(ratingToMedal(1800)).toEqual({ level: "provincial", type: "gold" });
  });

  it("returns provincial gold at 2000", () => {
    expect(ratingToMedal(2000)).toEqual({ level: "provincial", type: "gold" });
  });

  it("returns regional gold at 2200", () => {
    expect(ratingToMedal(2200)).toEqual({ level: "regional", type: "gold" });
  });

  it("returns regional gold at 2400", () => {
    expect(ratingToMedal(2400)).toEqual({ level: "regional", type: "gold" });
  });

  it("returns ec_final gold at 2600", () => {
    expect(ratingToMedal(2600)).toEqual({ level: "ec_final", type: "gold" });
  });

  it("returns world finals gold at 2800", () => {
    expect(ratingToMedal(2800)).toEqual({ level: "world_finals", type: "gold" });
  });

  it("returns highest medal for extreme rating", () => {
    expect(ratingToMedal(3000)).toEqual({ level: "world_finals", type: "gold" });
  });
});

// ---------------------------------------------------------------------------
// stripIndexPrefix
// ---------------------------------------------------------------------------

describe("stripIndexPrefix", () => {
  it("strips simple letter prefix like 'A. '", () => {
    expect(stripIndexPrefix("A. Theatre Square")).toBe("Theatre Square");
  });

  it("strips letter+digit prefix like 'C1. '", () => {
    expect(stripIndexPrefix("C1. Increasing Subsequence")).toBe(
      "Increasing Subsequence",
    );
  });

  it("strips letter+multi-digit prefix like 'E2. '", () => {
    expect(stripIndexPrefix("E2. Array and Segments")).toBe(
      "Array and Segments",
    );
  });

  it("strips 'B. ' prefix", () => {
    expect(stripIndexPrefix("B. Two Tables")).toBe("Two Tables");
  });

  it("does not strip lowercase prefix", () => {
    expect(stripIndexPrefix("a. Some Problem")).toBe("a. Some Problem");
  });

  it("does not strip prefix without dot-space", () => {
    expect(stripIndexPrefix("A problem name")).toBe("A problem name");
  });

  it("does not strip prefix embedded in text", () => {
    expect(stripIndexPrefix("Problem A. Test")).toBe("Problem A. Test");
  });

  it("returns name unchanged when no prefix present", () => {
    expect(stripIndexPrefix("Two Tables")).toBe("Two Tables");
  });

  it("handles single letter prefix 'Z. '", () => {
    expect(stripIndexPrefix("Z. Hard Problem")).toBe("Hard Problem");
  });

  it("handles prefix with multiple digits 'F12. '", () => {
    expect(stripIndexPrefix("F12. Very Hard")).toBe("Very Hard");
  });
});

// ---------------------------------------------------------------------------
// getNextRankName
// ---------------------------------------------------------------------------

describe("getNextRankName", () => {
  // Simple translation function that returns the key for testing
  const t = (key: string) => key;

  describe("medal mode", () => {
    it("returns medal name for threshold 1200 (provincial bronze)", () => {
      const result = getNextRankName(1200, t, "medal");
      expect(result).toBe("medal:levels.provincialmedal:types.bronze");
    });

    it("returns medal name for threshold 1400 (provincial silver)", () => {
      const result = getNextRankName(1400, t, "medal");
      expect(result).toBe("medal:levels.provincialmedal:types.silver");
    });

    it("returns medal name for threshold 1600 (provincial gold)", () => {
      const result = getNextRankName(1600, t, "medal");
      expect(result).toBe("medal:levels.provincialmedal:types.gold");
    });

    it("returns medal name for threshold 2200 (regional gold)", () => {
      const result = getNextRankName(2200, t, "medal");
      expect(result).toBe("medal:levels.regionalmedal:types.gold");
    });

    it("returns medal name for threshold 2600 (ec_final gold)", () => {
      const result = getNextRankName(2600, t, "medal");
      expect(result).toBe("medal:levels.ecFinalmedal:types.gold");
    });

    it("returns medal name for threshold 2800 (world_finals gold)", () => {
      const result = getNextRankName(2800, t, "medal");
      expect(result).toBe("medal:levels.worldFinalsmedal:types.gold");
    });

    it("returns numeric threshold for unmapped value", () => {
      const result = getNextRankName(999, t, "medal");
      expect(result).toBe("999");
    });

    it("returns numeric threshold for 3000 (not in medal map)", () => {
      const result = getNextRankName(3000, t, "medal");
      expect(result).toBe("3000");
    });
  });

  describe("cf_tier mode", () => {
    it("returns CF tier name for threshold 1200 (Pupil)", () => {
      const result = getNextRankName(1200, t, "cf_tier");
      expect(result).toBe("rating:pupil");
    });

    it("returns CF tier name for threshold 1400 (Specialist)", () => {
      const result = getNextRankName(1400, t, "cf_tier");
      expect(result).toBe("rating:specialist");
    });

    it("returns CF tier name for threshold 1600 (Expert)", () => {
      const result = getNextRankName(1600, t, "cf_tier");
      expect(result).toBe("rating:expert");
    });

    it("returns CF tier name for threshold 1900 (Candidate Master)", () => {
      const result = getNextRankName(1900, t, "cf_tier");
      expect(result).toBe("rating:candidateMaster");
    });

    it("returns CF tier name for threshold 2100 (Master)", () => {
      const result = getNextRankName(2100, t, "cf_tier");
      expect(result).toBe("rating:master");
    });

    it("returns CF tier name for threshold 2300 (International Master)", () => {
      const result = getNextRankName(2300, t, "cf_tier");
      expect(result).toBe("rating:internationalMaster");
    });

    it("returns CF tier name for threshold 2400 (Grandmaster)", () => {
      const result = getNextRankName(2400, t, "cf_tier");
      expect(result).toBe("rating:grandmaster");
    });

    it("returns CF tier name for threshold 2600 (International Grandmaster)", () => {
      const result = getNextRankName(2600, t, "cf_tier");
      expect(result).toBe("rating:internationalGrandmaster");
    });

    it("returns CF tier name for threshold 3000 (Legendary Grandmaster)", () => {
      const result = getNextRankName(3000, t, "cf_tier");
      expect(result).toBe("rating:legendaryGrandmaster");
    });

    it("returns numeric threshold for unmapped value", () => {
      const result = getNextRankName(999, t, "cf_tier");
      expect(result).toBe("999");
    });
  });

  describe("integration with t() function", () => {
    it("passes medal keys through t() for localization", () => {
      const calls: string[] = [];
      const mockT = (key: string) => {
        calls.push(key);
        return key.replace("medal:", "").replace("rating:", "");
      };
      getNextRankName(1600, mockT, "medal");
      expect(calls).toContain("medal:types.gold");
      expect(calls).toContain("medal:levels.provincial");
    });

    it("passes CF tier key through t() for localization", () => {
      const calls: string[] = [];
      const mockT = (key: string) => {
        calls.push(key);
        return key.replace("rating:", "");
      };
      getNextRankName(2400, mockT, "cf_tier");
      expect(calls).toContain("rating:grandmaster");
    });
  });
});
