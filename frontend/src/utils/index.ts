/** Difficulty color mapping for competitive programming ratings. */

const DIFFICULTY_COLORS: Record<string, string> = {
  gray: "#999999",
  green: "#00AA00",
  blue: "#6666FF",
  purple: "#CC00CC",
  yellow: "#FFBB00",
  red: "#FF0000",
};

export function getRatingColor(rating: number | null | undefined): string {
  if (rating == null) return DIFFICULTY_COLORS.gray;
  if (rating < 1200) return DIFFICULTY_COLORS.gray;
  if (rating < 1400) return DIFFICULTY_COLORS.green;
  if (rating < 1600) return DIFFICULTY_COLORS.blue;
  if (rating < 2000) return DIFFICULTY_COLORS.purple;
  if (rating < 2400) return DIFFICULTY_COLORS.yellow;
  return DIFFICULTY_COLORS.red;
}

export function getDifficultyLabel(rating: number | null | undefined): string {
  if (rating == null) return "Unrated";
  if (rating < 1200) return "Newbie";
  if (rating < 1400) return "Pupil";
  if (rating < 1600) return "Specialist";
  if (rating < 2000) return "Expert";
  if (rating < 2400) return "Candidate Master";
  return "Grandmaster";
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

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "-";
  return new Date(dateStr).toLocaleDateString("en-US", {
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
