/**
 * EloProgressBar -- displays the user's M-Elo for a training topic with:
 *   - Medal color context
 *   - Progress bar toward the next rank threshold
 *   - Predicted Elo change overlay from shared prediction hook
 *
 * Gracefully degrades when prediction API is unavailable.
 */

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { getRatingColor, getNextRankName } from "@/utils";
import { useTimeFactorPrediction } from "@/hooks/useTimeFactorPrediction";
import api from "@/services/api";
import type { ApiResponse, UserSettingsData } from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
  /** Optional topic name to display in the header */
  topicName?: string;
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
  topicName,
}: EloProgressBarProps) {
  const { t } = useTranslation("training");
  const [displayMode, setDisplayMode] = useState<"medal" | "cf_tier">("medal");

  // Fetch display_mode setting once on mount
  useEffect(() => {
    let cancelled = false;
    api
      .get<ApiResponse<UserSettingsData>>("/auth/settings")
      .then((res) => {
        if (!cancelled) setDisplayMode(res.data.data.display_mode);
      })
      .catch(() => {
        // Fallback to medal mode on error
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Shared prediction hook (deduplicated with SolvingTimeline)
  const { prediction, refetch } = useTimeFactorPrediction(
    problemId ?? null,
    problemRating ?? null,
    melo,
  );

  // Auto-refresh prediction every 60 seconds
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (!problemId || !problemRating) return;
    intervalRef.current = setInterval(refetch, 60_000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [refetch, problemId, problemRating]);

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

  // Distance to next rank
  const distanceToNext = progressMax !== null ? Math.max(0, progressMax - melo) : null;

  // Whether prediction overlay is visible (used for separator logic)
  const hasPredictionOverlay =
    predictedPercent !== null && Math.abs(predictedPercent - progressPercent) > 0.5;

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-2.5">
      {/* Header: Topic name + M-Elo label, predicted change */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-muted-foreground">
            {topicName ? `${topicName} ` : ""}
            {t("eloProgress.meloLabel")}
          </span>
          <span className="text-lg font-bold" style={{ color }}>
            {Math.round(melo)}
          </span>
        </div>
        {/* Predicted change -- compact text, no icon */}
        {eloChange !== null && (
          <span
            className={`text-sm font-semibold ${
              eloChange >= 0 ? "text-green-400" : "text-red-400"
            }`}
          >
            {eloChange >= 0 ? "+" : ""}
            {eloChange}
          </span>
        )}
      </div>

      {/* Progress bar */}
      <div className="space-y-1">
        <div className="relative h-2 w-full overflow-hidden rounded-full bg-muted">
          {/* Base progress (current position) -- white/black adaptive */}
          <div
            className={`absolute left-0 top-0 h-full bg-foreground transition-all duration-500 ${
              hasPredictionOverlay ? "rounded-l-full" : "rounded-full"
            }`}
            style={{ width: `${progressPercent}%` }}
          />

          {/* Prediction overlay */}
          {hasPredictionOverlay && (
            <div
              className="absolute top-0 h-full rounded-r-full transition-all duration-500"
              style={{
                left: `${Math.min(progressPercent, predictedPercent!)}%`,
                width: `${Math.abs(predictedPercent! - progressPercent)}%`,
                backgroundColor: eloChange !== null && eloChange >= 0 ? "#22c55e" : "#ef4444",
                opacity: 0.4,
              }}
            >
              {/* Separator line at the boundary between base bar and overlay */}
              <div
                className="absolute top-0 bottom-0 w-px"
                style={{
                  left: eloChange !== null && eloChange >= 0 ? 0 : "auto",
                  right: eloChange !== null && eloChange < 0 ? 0 : "auto",
                  backgroundColor: "var(--foreground)",
                  opacity: 0.6,
                }}
              />
            </div>
          )}
        </div>

        {/* Labels below the bar -- only left and right numeric endpoints */}
        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <span>{progressMin}</span>
          {isMaxTier && (
            <span className="font-medium text-foreground">
              {t("eloProgressMax")}
            </span>
          )}
          {progressMax !== null && <span>{progressMax}</span>}
        </div>
      </div>

      {/* Distance to next rank with specific name */}
      {!isMaxTier && distanceToNext !== null && (
        <p className="text-[11px] text-muted-foreground">
          {t(
            displayMode === "medal"
              ? "eloProgress.untilNextMedal"
              : "eloProgress.untilNextTier",
            {
              name: getNextRankName(nextMedalThreshold!, t, displayMode),
              amount: Math.ceil(distanceToNext),
            },
          )}
        </p>
      )}
    </div>
  );
}
