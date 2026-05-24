/**
 * EloProgressBar -- displays the user's M-Elo for a training topic with:
 *   - Medal color context
 *   - Progress bar toward the next medal threshold
 *   - Predicted Elo change overlay from /time-factor-prediction API
 *
 * Refreshes prediction every 60 seconds (or when the problem changes).
 * Gracefully degrades when prediction API is unavailable.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { getRatingColor } from "@/utils";
import api from "@/services/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TimePoint {
  minutes: number;
  time_factor: number;
  elo_change_estimate: number;
}

interface PredictionData {
  expected_time_minutes: number;
  time_points: TimePoint[];
}

export interface EloProgressBarProps {
  /** Current M-Elo for the topic */
  melo: number;
  /** Current medal threshold (e.g. 1200 for provincial bronze) */
  currentMedalThreshold: number | null;
  /** Next medal threshold (e.g. 1400 for provincial silver) */
  nextMedalThreshold: number | null;
  /** Current problem ID (triggers prediction refresh when changed) */
  problemId?: string | null;
  /** Current problem rating */
  problemRating?: number | null;
}

// ---------------------------------------------------------------------------
// Medal threshold label helper
// ---------------------------------------------------------------------------

function getMedalLabelForThreshold(threshold: number): { level: string; type: string } | null {
  const map: [number, string, string][] = [
    [2800, "worldFinals", "gold"],
    [2600, "ecFinal", "gold"],
    [2200, "regional", "gold"],
    [1600, "provincial", "gold"],
    [1400, "provincial", "silver"],
    [1200, "provincial", "bronze"],
  ];
  for (const [t, level, type] of map) {
    if (threshold === t) return { level, type };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EloProgressBar({
  melo,
  currentMedalThreshold,
  nextMedalThreshold,
  problemId,
  problemRating,
}: EloProgressBarProps) {
  const { t, i18n } = useTranslation("training");
  const isZh = i18n.language?.startsWith("zh");
  const [prediction, setPrediction] = useState<PredictionData | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // -------------------------------------------------------------------------
  // Fetch prediction
  // -------------------------------------------------------------------------
  const fetchPrediction = useCallback(async () => {
    if (!problemId || !problemRating) return;
    try {
      const res = await api.get("/time-factor-prediction", {
        params: {
          problem_id: problemId,
          problem_rating: problemRating,
          user_elo: Math.round(melo),
        },
      });
      setPrediction(res.data.data as PredictionData);
    } catch {
      // Graceful degradation: prediction API unavailable
    }
  }, [problemId, problemRating, melo]);

  // Fetch on mount and when problem changes
  /* eslint-disable react-hooks/set-state-in-effect -- fetches prediction data from API */
  useEffect(() => {
    fetchPrediction();
  }, [fetchPrediction]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Refresh prediction every 60 seconds
  useEffect(() => {
    if (!problemId || !problemRating) return;
    intervalRef.current = setInterval(fetchPrediction, 60_000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchPrediction, problemId, problemRating]);

  // -------------------------------------------------------------------------
  // Derived values
  // -------------------------------------------------------------------------

  const color = getRatingColor(melo);

  // Progress bar boundaries
  const progressMin = currentMedalThreshold ?? 0;
  const progressMax = nextMedalThreshold ?? null;

  // Whether we're at the highest tier
  const isMaxTier = nextMedalThreshold === null;

  // Calculate progress percentage (0-100)
  const progressPercent =
    progressMax !== null
      ? Math.min(
          100,
          Math.max(0, ((melo - progressMin) / (progressMax - progressMin)) * 100),
        )
      : 100;

  // Predicted Elo change from first time point
  const eloChange =
    prediction && prediction.time_points.length > 0
      ? prediction.time_points[0].elo_change_estimate
      : null;

  // Predicted position for overlay
  const predictedMelo = eloChange !== null ? melo + eloChange : null;

  // Predicted position as percentage of the progress bar
  const predictedPercent =
    predictedMelo !== null && progressMax !== null
      ? Math.min(
          100,
          Math.max(0, ((predictedMelo - progressMin) / (progressMax - progressMin)) * 100),
        )
      : null;

  // Distance to next medal
  const distanceToNext = progressMax !== null ? Math.max(0, progressMax - melo) : null;

  // Medal label for the next threshold
  const nextMedalInfo = nextMedalThreshold !== null
    ? getMedalLabelForThreshold(nextMedalThreshold)
    : null;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2.5">
      {/* Header: M-Elo value with color */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            {t("eloProgress.meloLabel")}
          </span>
          <span className="text-lg font-bold" style={{ color }}>
            {Math.round(melo)}
          </span>
        </div>
        {/* Predicted change badge */}
        {eloChange !== null && (
          <div
            className={`flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold ${
              eloChange >= 0
                ? "bg-green-500/10 text-green-400"
                : "bg-red-500/10 text-red-400"
            }`}
          >
            {eloChange >= 0 ? (
              <TrendingUp className="size-3" />
            ) : (
              <TrendingDown className="size-3" />
            )}
            {eloChange >= 0 ? "+" : ""}
            {eloChange}
          </div>
        )}
      </div>

      {/* Progress bar */}
      <div className="space-y-1">
        <div className="relative h-2 w-full overflow-hidden rounded-full bg-muted">
          {/* Base progress (current position) */}
          <div
            className="absolute left-0 top-0 h-full rounded-full transition-all duration-500"
            style={{
              width: `${progressPercent}%`,
              backgroundColor: color,
              opacity: 0.6,
            }}
          />

          {/* Prediction overlay */}
          {predictedPercent !== null && Math.abs(predictedPercent - progressPercent) > 0.5 && (
            <div
              className="absolute top-0 h-full rounded-full transition-all duration-500"
              style={{
                left: `${Math.min(progressPercent, predictedPercent)}%`,
                width: `${Math.abs(predictedPercent - progressPercent)}%`,
                backgroundColor: eloChange !== null && eloChange >= 0 ? "#22c55e" : "#ef4444",
                opacity: 0.4,
              }}
            />
          )}

          {/* Current position marker */}
          <div
            className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 rounded-full bg-foreground shadow-sm"
            style={{ left: `${progressPercent}%` }}
          />
        </div>

        {/* Labels below the bar */}
        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <span>{progressMin}</span>
          {isMaxTier ? (
            <span className="font-medium text-foreground">
              {t("eloProgressMax")}
            </span>
          ) : nextMedalInfo ? (
            <span>
              {isZh
                ? `${t("medal:levels." + nextMedalInfo.level)}${t("medal:types." + nextMedalInfo.type)}`
                : `${t("medal:types." + nextMedalInfo.type)} ${t("medal:levels." + nextMedalInfo.level)}`}
            </span>
          ) : null}
          {progressMax !== null && <span>{progressMax}</span>}
        </div>
      </div>

      {/* Distance to next */}
      {!isMaxTier && distanceToNext !== null && (
        <p className="text-[11px] text-muted-foreground">
          {t("eloProgress.untilNext", { amount: Math.ceil(distanceToNext) })}
        </p>
      )}
    </div>
  );
}
