/** Solving Timeline component.
 *
 * Displays a vertical timeline showing predicted Elo change at various
 * solve-time milestones. The current elapsed time is highlighted with a
 * live marker that advances every minute.
 *
 * Used during problem solving in PvP, PvE, and Free Play sessions.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Clock, Loader2, Star, TrendingDown, TrendingUp } from "lucide-react";
import { useTranslation } from "react-i18next";
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

export interface SolvingTimelineProps {
  /** Problem ID (e.g. "1920A") */
  problemId: string;
  /** Problem difficulty rating */
  problemRating: number;
  /** User's current Elo rating */
  userElo: number;
  /** When the solving session started */
  startTime: Date;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SolvingTimeline({
  problemId,
  problemRating,
  userElo,
  startTime,
}: SolvingTimelineProps) {
  const { t } = useTranslation("common");
  const [data, setData] = useState<PredictionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [currentMinutes, setCurrentMinutes] = useState(0);
  const minuteRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch prediction data on mount
  useEffect(() => {
    let cancelled = false;

    const fetchPrediction = async () => {
      setLoading(true);
      setError(false);
      try {
        const res = await api.get("/time-factor-prediction", {
          params: {
            problem_id: problemId,
            problem_rating: problemRating,
            user_elo: userElo,
          },
        });
        if (!cancelled) {
          setData(res.data.data as PredictionData);
        }
      } catch {
        if (!cancelled) {
          setError(true);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    fetchPrediction();
    return () => {
      cancelled = true;
    };
  }, [problemId, problemRating, userElo]);

  // Calculate initial elapsed and set up per-minute update
  useEffect(() => {
    const updateElapsed = () => {
      const elapsedMs = Date.now() - startTime.getTime();
      const minutes = Math.floor(elapsedMs / 60_000);
      setCurrentMinutes(minutes);
    };

    updateElapsed();
    minuteRef.current = setInterval(updateElapsed, 60_000);

    return () => {
      if (minuteRef.current) clearInterval(minuteRef.current);
    };
  }, [startTime]);

  // Determine the closest time point for the current time
  const getCurrentPointIndex = useCallback((): number => {
    if (!data) return -1;
    // Find the first point at or after currentMinutes
    for (let i = 0; i < data.time_points.length; i++) {
      if (data.time_points[i].minutes >= currentMinutes) {
        return i;
      }
    }
    return data.time_points.length - 1;
  }, [data, currentMinutes]);

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Clock className="size-4 text-muted-foreground" />
          {t("timeline.title")}
        </div>
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="size-3 rounded-full bg-muted animate-pulse" />
              <div className="flex-1">
                <div className="h-3 w-16 rounded bg-muted animate-pulse" />
              </div>
              <div className="h-3 w-10 rounded bg-muted animate-pulse" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Error or no data state -- show nothing (graceful degradation)
  if (error || !data || data.time_points.length === 0) {
    return null;
  }

  const currentIdx = getCurrentPointIndex();
  // Find the closest time point to the expected time
  const expectedIdx = data.time_points.reduce((bestIdx, point, idx) => {
    const diff = Math.abs(point.minutes - data.expected_time_minutes);
    const bestDiff = Math.abs(data.time_points[bestIdx].minutes - data.expected_time_minutes);
    return diff < bestDiff ? idx : bestIdx;
  }, 0);

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Clock className="size-4 text-muted-foreground" />
        {t("timeline.title")}
      </div>

      {/* Timeline */}
      <div className="relative pl-4">
        {/* Vertical line */}
        <div className="absolute left-[7px] top-2 bottom-2 w-px bg-border" />

        <div className="space-y-2.5">
          {data.time_points.map((point, idx) => {
            const isCurrentOrPast = idx <= currentIdx && currentMinutes > 0;
            const isCurrentPoint = idx === currentIdx && currentMinutes > 0;
            const isExpected = idx === expectedIdx;
            const isPositive = point.elo_change_estimate > 0;

            return (
              <div
                key={point.minutes}
                className={`relative flex items-center gap-3 transition-colors duration-300 ${
                  isCurrentOrPast ? "opacity-100" : "opacity-50"
                }`}
              >
                {/* Dot */}
                <div
                  className={`relative z-10 size-[7px] shrink-0 rounded-full transition-colors duration-300 ${
                    isCurrentPoint
                      ? "bg-primary ring-2 ring-primary/30"
                      : isExpected
                        ? "bg-yellow-400 ring-2 ring-yellow-400/30"
                        : isCurrentOrPast
                          ? "bg-foreground"
                          : "bg-muted-foreground"
                  }`}
                />

                {/* Time label */}
                <span
                  className={`w-14 shrink-0 text-xs font-mono ${
                    isCurrentPoint
                      ? "text-primary font-bold"
                      : isExpected
                        ? "text-yellow-400 font-semibold"
                        : isCurrentOrPast
                          ? "text-foreground"
                          : "text-muted-foreground"
                  }`}
                >
                  {point.minutes}m
                </span>

                {/* Elo change estimate */}
                <span
                  className={`flex items-center gap-1 text-xs font-semibold ${
                    isCurrentPoint
                      ? isPositive
                        ? "text-green-400"
                        : "text-red-400"
                      : isPositive
                        ? "text-green-400/70"
                        : "text-red-400/70"
                  }`}
                >
                  {isPositive ? (
                    <TrendingUp className="size-3" />
                  ) : (
                    <TrendingDown className="size-3" />
                  )}
                  {isPositive ? "+" : ""}
                  {point.elo_change_estimate}
                </span>

                {/* Expected time badge */}
                {isExpected && (
                  <span className="flex items-center gap-0.5 rounded-md bg-yellow-400/15 px-1.5 py-0.5 text-[10px] font-semibold text-yellow-400">
                    <Star className="size-2.5" />
                    {t("timeline.expected")}
                  </span>
                )}

                {/* Current time marker (arrow) */}
                {isCurrentPoint && currentMinutes > 0 && (
                  <span className="ml-auto rounded-md bg-primary/15 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                    {t("timeline.now")}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Footer: expected time summary */}
      <div className="border-t border-border pt-2">
        <p className="text-[11px] text-muted-foreground">
          {t("timeline.expectedTime", { minutes: data.expected_time_minutes.toFixed(0) })}
        </p>
      </div>
    </div>
  );
}
