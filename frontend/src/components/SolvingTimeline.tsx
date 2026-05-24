/**
 * SolvingTimeline component.
 *
 * Displays a compact SVG area/line chart showing predicted Elo change over
 * solve time. Positive values are shaded green, negative values red. The
 * current elapsed time is shown as a vertical marker, and the expected solve
 * time is highlighted with a diamond marker.
 *
 * Uses the shared useTimeFactorPrediction hook so requests are deduplicated
 * when both EloProgressBar and SolvingTimeline are mounted for the same
 * problem.
 */

import { useEffect, useRef, useState } from "react";
import { Clock } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useTimeFactorPrediction } from "@/hooks/useTimeFactorPrediction";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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
// SVG chart dimensions (viewBox)
// ---------------------------------------------------------------------------

const VB_WIDTH = 220;
const VB_HEIGHT = 100;
const PADDING_LEFT = 4;
const PADDING_RIGHT = 4;
const PADDING_TOP = 8;
const PADDING_BOTTOM = 18;

const CHART_WIDTH = VB_WIDTH - PADDING_LEFT - PADDING_RIGHT;
const CHART_HEIGHT = VB_HEIGHT - PADDING_TOP - PADDING_BOTTOM;

// Colors
const GREEN_LINE = "#22c55e";
const GREEN_FILL = "rgba(34,197,94,0.15)";
const RED_LINE = "#ef4444";
const RED_FILL = "rgba(239,68,68,0.15)";

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
  const [currentMinutes, setCurrentMinutes] = useState(0);
  const minuteRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Shared prediction hook (deduplicated with EloProgressBar)
  const { prediction: data, loading, error } = useTimeFactorPrediction(
    problemId,
    problemRating,
    userElo,
  );

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
        {/* Skeleton: simplified wave shape */}
        <div className="relative h-[90px] w-full overflow-hidden rounded-md bg-muted/40">
          <div className="absolute inset-0 animate-pulse">
            <svg
              viewBox={`0 0 ${VB_WIDTH} ${VB_HEIGHT}`}
              className="h-full w-full"
              preserveAspectRatio="none"
            >
              <path
                d={`M${PADDING_LEFT},${VB_HEIGHT / 2} Q${VB_WIDTH * 0.25},${VB_HEIGHT * 0.25} ${VB_WIDTH * 0.5},${VB_HEIGHT * 0.4} T${VB_WIDTH - PADDING_RIGHT},${VB_HEIGHT * 0.55}`}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                opacity="0.2"
              />
            </svg>
          </div>
        </div>
      </div>
    );
  }

  // Error or no data state -- show nothing (graceful degradation)
  if (error || !data || data.time_points.length < 2) {
    return null;
  }

  // ---------------------------------------------------------------------------
  // Chart data processing
  // ---------------------------------------------------------------------------

  const points = data.time_points;
  const minMinutes = points[0].minutes;
  const maxMinutes = points[points.length - 1].minutes;
  const minutesRange = maxMinutes - minMinutes || 1; // avoid div-by-zero

  const eloValues = points.map((p) => p.elo_change_estimate);
  const maxElo = Math.max(...eloValues, 0);
  const minElo = Math.min(...eloValues, 0);
  const eloRange = maxElo - minElo || 1; // avoid div-by-zero

  // Map data points to SVG coordinates
  // Y: higher elo = higher on chart (lower y value)
  const mapX = (minutes: number) =>
    PADDING_LEFT + ((minutes - minMinutes) / minutesRange) * CHART_WIDTH;
  const mapY = (elo: number) =>
    PADDING_TOP + ((maxElo - elo) / eloRange) * CHART_HEIGHT;

  // Zero-line Y position
  const zeroY = mapY(0);

  // Current time X position (clamped to chart bounds)
  const currentX = (() => {
    if (currentMinutes <= 0) return null;
    const x = mapX(currentMinutes);
    if (x < PADDING_LEFT || x > VB_WIDTH - PADDING_RIGHT) return null;
    return x;
  })();

  // Find the closest point to expected time
  const expectedIdx = points.reduce((bestIdx, point, idx) => {
    const diff = Math.abs(point.minutes - data.expected_time_minutes);
    const bestDiff = Math.abs(points[bestIdx].minutes - data.expected_time_minutes);
    return diff < bestDiff ? idx : bestIdx;
  }, 0);
  const expectedPoint = points[expectedIdx];
  const expectedX = mapX(expectedPoint.minutes);
  const expectedY = mapY(expectedPoint.elo_change_estimate);

  // Build the SVG polyline path (for the line)
  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${mapX(p.minutes).toFixed(1)},${mapY(p.elo_change_estimate).toFixed(1)}`)
    .join(" ");

  // Build filled areas: split into positive and negative regions
  // We need to compute the area between the curve and the zero line.
  // For each segment, we create a closed path that fills from the line to zeroY.

  // Positive area path (green): segments where elo >= 0
  // Negative area path (red): segments where elo <= 0
  // For smooth visuals, we handle sign-crossing by interpolating the zero crossing point.

  function buildAreaPaths() {
    const svgPoints = points.map((p) => ({
      x: mapX(p.minutes),
      y: mapY(p.elo_change_estimate),
      elo: p.elo_change_estimate,
    }));

    const segments: Array<{ type: "positive" | "negative"; path: string }> = [];
    let currentSegment: Array<{ x: number; y: number }> = [];
    let currentType: "positive" | "negative" | null = null;

    function getZeroCrossing(
      p1: { x: number; y: number; elo: number },
      p2: { x: number; y: number; elo: number },
    ) {
      // Linear interpolation to find x where elo crosses zero
      const t = p1.elo / (p1.elo - p2.elo);
      return {
        x: p1.x + t * (p2.x - p1.x),
        y: zeroY,
      };
    }

    function flushSegment() {
      if (currentSegment.length < 1 || currentType === null) return;

      // Build closed area path: line on top, zero line on bottom (reversed)
      const areaPoints = [...currentSegment];
      // Close along the zero line
      areaPoints.push({ x: currentSegment[currentSegment.length - 1].x, y: zeroY });
      areaPoints.push({ x: currentSegment[0].x, y: zeroY });

      const path = areaPoints
        .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`)
        .join(" ");

      segments.push({ type: currentType, path });
      currentSegment = [];
    }

    for (let i = 0; i < svgPoints.length; i++) {
      const pt = svgPoints[i];
      const ptType: "positive" | "negative" = pt.elo >= 0 ? "positive" : "negative";

      if (currentType !== null && currentType !== ptType) {
        // Sign change: interpolate zero crossing
        const crossing = getZeroCrossing(svgPoints[i - 1], pt);
        currentSegment.push(crossing);
        flushSegment();
        // Start new segment from the crossing
        currentSegment = [crossing];
        currentType = ptType;
      }

      if (currentType === null) {
        currentType = ptType;
      }

      currentSegment.push(pt);
    }

    flushSegment();
    return segments;
  }

  const areaSegments = buildAreaPaths();

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
        <Clock className="size-4 text-muted-foreground" />
        {t("timeline.title")}
      </div>

      {/* SVG Chart */}
      <svg
        data-testid="elo-chart"
        viewBox={`0 0 ${VB_WIDTH} ${VB_HEIGHT}`}
        className="h-auto w-full"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={t("timeline.title")}
      >
        {/* Zero line (horizontal) */}
        <line
          x1={PADDING_LEFT}
          y1={zeroY}
          x2={VB_WIDTH - PADDING_RIGHT}
          y2={zeroY}
          stroke="currentColor"
          strokeWidth="0.5"
          strokeOpacity="0.2"
          strokeDasharray="3,3"
        />

        {/* Filled areas */}
        {areaSegments.map((seg, idx) => (
          <path
            key={`area-${idx}`}
            d={seg.path}
            fill={seg.type === "positive" ? GREEN_FILL : RED_FILL}
            stroke="none"
          />
        ))}

        {/* Line (on top of fills) */}
        <path
          d={linePath}
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeOpacity="0.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Colored line segments: split at zero crossings */}
        {(() => {
          const svgPoints = points.map((p) => ({
            x: mapX(p.minutes),
            y: mapY(p.elo_change_estimate),
            elo: p.elo_change_estimate,
          }));
          const segs: Array<{
            x1: number; y1: number; x2: number; y2: number;
            color: "green" | "red";
          }> = [];
          for (let i = 0; i < svgPoints.length - 1; i++) {
            const p1 = svgPoints[i];
            const p2 = svgPoints[i + 1];
            const sameSign = (p1.elo >= 0 && p2.elo >= 0) || (p1.elo < 0 && p2.elo < 0);
            if (sameSign) {
              segs.push({
                x1: p1.x, y1: p1.y, x2: p2.x, y2: p2.y,
                color: p1.elo >= 0 ? "green" : "red",
              });
            } else {
              const t = p1.elo / (p1.elo - p2.elo);
              const crossX = p1.x + t * (p2.x - p1.x);
              segs.push({
                x1: p1.x, y1: p1.y, x2: crossX, y2: zeroY,
                color: p1.elo >= 0 ? "green" : "red",
              });
              segs.push({
                x1: crossX, y1: zeroY, x2: p2.x, y2: p2.y,
                color: p2.elo >= 0 ? "green" : "red",
              });
            }
          }
          return segs.map((s, i) => (
            <line
              key={`${s.color}-${i}`}
              x1={s.x1.toFixed(1)}
              y1={s.y1.toFixed(1)}
              x2={s.x2.toFixed(1)}
              y2={s.y2.toFixed(1)}
              stroke={s.color === "green" ? GREEN_LINE : RED_LINE}
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          ));
        })()}

        {/* Data points */}
        {points.map((p, i) => {
          const cx = mapX(p.minutes);
          const cy = mapY(p.elo_change_estimate);
          const isExpected = i === expectedIdx;
          const color = p.elo_change_estimate >= 0 ? GREEN_LINE : RED_LINE;
          return (
            <circle
              key={`dot-${i}`}
              cx={cx.toFixed(1)}
              cy={cy.toFixed(1)}
              r={isExpected ? 2.5 : 1.5}
              fill={isExpected ? "var(--color-primary, currentColor)" : color}
              stroke={isExpected ? "var(--color-primary, currentColor)" : "none"}
              strokeWidth={0}
              opacity={isExpected ? 1 : 0.7}
            />
          );
        })}

        {/* Expected time diamond marker + label */}
        <g transform={`translate(${expectedX.toFixed(1)},${expectedY.toFixed(1)})`}>
          <polygon
            points="0,-4 4,0 0,4 -4,0"
            fill="var(--color-primary, currentColor)"
            opacity="0.85"
          />
          <line
            x1="0"
            y1="4"
            x2="0"
            y2={(VB_HEIGHT - PADDING_BOTTOM - expectedY).toFixed(1)}
            stroke="var(--color-primary, currentColor)"
            strokeWidth="0.5"
            strokeDasharray="2,2"
            strokeOpacity="0.4"
          />
        </g>

        {/* Current time vertical line */}
        {currentX !== null && (
          <line
            x1={currentX.toFixed(1)}
            y1={PADDING_TOP}
            x2={currentX.toFixed(1)}
            y2={VB_HEIGHT - PADDING_BOTTOM}
            stroke="currentColor"
            strokeWidth="1.5"
            strokeOpacity="0.6"
          />
        )}

        {/* X-axis time labels */}
        {(() => {
          const labelCount = Math.min(points.length, 6);
          const step = Math.max(1, Math.floor((points.length - 1) / (labelCount - 1)));
          const labels: Array<{ x: number; text: string }> = [];
          for (let i = 0; i < points.length; i += step) {
            labels.push({ x: mapX(points[i].minutes), text: `${points[i].minutes}m` });
          }
          // Always include last point
          const lastX = mapX(points[points.length - 1].minutes);
          if (labels[labels.length - 1].x !== lastX) {
            labels.push({ x: lastX, text: `${points[points.length - 1].minutes}m` });
          }
          return labels.map((l, i) => (
            <text
              key={`xlabel-${i}`}
              x={l.x.toFixed(1)}
              y={(VB_HEIGHT - 3).toFixed(1)}
              textAnchor="middle"
              fill="currentColor"
              opacity="0.4"
              fontSize="7"
              fontFamily="monospace"
            >
              {l.text}
            </text>
          ));
        })()}
      </svg>

      {/* Legend */}
      <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <svg width="8" height="8" viewBox="0 0 8 8"><polygon points="4,0 8,4 4,8 0,4" fill="var(--color-primary, currentColor)" opacity="0.85" /></svg>
          {t("timeline.expected")}
        </span>
        {currentX !== null && (
          <span className="flex items-center gap-1">
            <svg width="8" height="8" viewBox="0 0 8 8"><line x1="4" y1="0" x2="4" y2="8" stroke="currentColor" strokeWidth="1.5" /></svg>
          </span>
        )}
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
