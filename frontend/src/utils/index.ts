/** Rating tier definitions aligned with Codeforces 10-tier system.
 *
 * Each tier has:
 *  - name: English tier name (e.g. "Newbie", "Expert")
 *  - nameZh: Chinese tier name (for future i18n, Task 23.3)
 *  - min: minimum rating (inclusive). The first tier has min = -Infinity.
 *  - color: official CF hex color
 *  - legendary: true only for Legendary Grandmaster (>= 3000)
 *
 * Boundary reference (CF standard):
 *   < 1200   Newbie              #808080
 *   1200-1399  Pupil             #008000
 *   1400-1599  Specialist        #03A89E
 *   1600-1899  Expert            #0000FF
 *   1900-2099  Candidate Master  #AA00AA
 *   2100-2299  Master            #FF8C00
 *   2300-2399  International Master   #FF8C00
 *   2400-2599  Grandmaster       #FF0000
 *   2600-2999  International Grandmaster  #FF0000
 *   >= 3000    Legendary Grandmaster      #FF0000 (legendary: true)
 */

export interface RatingTier {
  name: string;
  nameZh: string;
  min: number;
  color: string;
  legendary?: boolean;
}

export const RATING_TIERS: RatingTier[] = [
  { name: "Newbie", nameZh: "新手", min: -Infinity, color: "#808080" },
  { name: "Pupil", nameZh: "学徒", min: 1200, color: "#008000" },
  { name: "Specialist", nameZh: "专家", min: 1400, color: "#03A89E" },
  { name: "Expert", nameZh: "精通", min: 1600, color: "#0000FF" },
  { name: "Candidate Master", nameZh: "候补大师", min: 1900, color: "#AA00AA" },
  { name: "Master", nameZh: "大师", min: 2100, color: "#FF8C00" },
  { name: "International Master", nameZh: "国际大师", min: 2300, color: "#FF8C00" },
  { name: "Grandmaster", nameZh: "宗师", min: 2400, color: "#FF0000" },
  { name: "International Grandmaster", nameZh: "国际宗师", min: 2600, color: "#FF0000" },
  { name: "Legendary Grandmaster", nameZh: "传奇宗师", min: 3000, color: "#FF0000", legendary: true },
];

/**
 * Return the full tier info object for a given rating.
 * Iterates RATING_TIERS in reverse (highest first) to find the matching tier.
 */
export function getRatingTierInfo(rating: number | null | undefined): RatingTier {
  if (rating == null) return RATING_TIERS[0];
  for (let i = RATING_TIERS.length - 1; i >= 0; i--) {
    if (rating >= RATING_TIERS[i].min) {
      return RATING_TIERS[i];
    }
  }
  return RATING_TIERS[0];
}

/** Return the CF color for a given rating. */
export function getRatingColor(rating: number | null | undefined): string {
  return getRatingTierInfo(rating).color;
}

/** Rating tier name -> i18n key mapping for the rating namespace. */
export const RATING_KEY_MAP: Record<string, string> = {
  "Newbie": "rating:newbie",
  "Pupil": "rating:pupil",
  "Specialist": "rating:specialist",
  "Expert": "rating:expert",
  "Candidate Master": "rating:candidateMaster",
  "Master": "rating:master",
  "International Master": "rating:internationalMaster",
  "Grandmaster": "rating:grandmaster",
  "International Grandmaster": "rating:internationalGrandmaster",
  "Legendary Grandmaster": "rating:legendaryGrandmaster",
};

/** Return the i18n key for a rating tier name (for use with t()). */
export function getDifficultyLabelKey(rating: number | null | undefined): string {
  if (rating == null) return "rating:unrated";
  const name = getRatingTierInfo(rating).name;
  return RATING_KEY_MAP[name] ?? "rating:unrated";
}

/** Return the CF English tier name for a given rating. */
export function getDifficultyLabel(rating: number | null | undefined): string {
  if (rating == null) return "Unrated";
  return getRatingTierInfo(rating).name;
}

export function formatTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export function formatDate(dateStr: string | null | undefined, locale?: string): string {
  if (!dateStr) return "-";
  const loc = locale ?? (typeof window !== "undefined" && localStorage.getItem("i18nextLng")?.startsWith("zh") ? "zh-CN" : "en-US");
  return new Date(dateStr).toLocaleDateString(loc, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function extractApiError(err: unknown, fallback = "An unexpected error occurred"): string {
  const axiosErr = err as {
    response?: { data?: { error?: { code?: string; message?: string }; detail?: string } };
  };
  const data = axiosErr?.response?.data;
  const errorCode = data?.error?.code;
  const errorMsg = data?.error?.message;
  const detail = data?.detail;

  // VALIDATION_ERROR: detail contains the specific field error (e.g. "body -> password: String should have at least 8 characters")
  if (errorCode === "VALIDATION_ERROR" && detail) return detail;
  // Business errors: error.message is the user-facing message
  if (errorMsg) return errorMsg;
  // Fallback chain
  return detail ?? fallback;
}

// ---------------------------------------------------------------------------
// Medal calculation (client-side, mirrors backend MedalService._rating_to_medal)
// ---------------------------------------------------------------------------

const FLAT_MEDAL_MAP: [number, string, string][] = [
  [2800, "world_finals", "gold"],
  [2600, "world_finals", "silver"],
  [2400, "world_finals", "bronze"],
  [2200, "regional", "gold"],
  [2000, "regional", "silver"],
  [1800, "regional", "bronze"],
  [1600, "provincial", "gold"],
  [1400, "provincial", "silver"],
  [1200, "provincial", "bronze"],
];

/**
 * Map a numeric rating to a medal tier + type (client-side).
 * Mirrors backend MedalService._rating_to_medal exactly.
 */
export function ratingToMedal(rating: number): { level: string; type?: string } {
  for (const [threshold, level, medalType] of FLAT_MEDAL_MAP) {
    if (rating >= threshold) {
      return { level, type: medalType };
    }
  }
  return { level: "unranked" };
}
