/**
 * Radar chart data utilities (FR-22.1 / FR-25.1).
 *
 * Shared between DashboardCharts and TrainingPage.
 * Aggregates per-tag M-Elo into 8 radar dimensions.
 */

import type { RadarDataPoint } from "@/types";

// ---------------------------------------------------------------------------
// 8 core radar dimensions
// ---------------------------------------------------------------------------

export const RADAR_DIMENSIONS = [
  { key: "dp", tags: ["dp"] },
  { key: "graphs", tags: ["graphs", "trees"] },
  { key: "math", tags: ["math", "number theory"] },
  { key: "ds", tags: ["data structures"] },
  { key: "strings", tags: ["strings"] },
  { key: "greedy", tags: ["greedy", "constructive algorithms"] },
  { key: "search", tags: ["binary search", "sortings"] },
  { key: "geometry", tags: ["geometry"] },
] as const;

export type RadarDimensionKey = (typeof RADAR_DIMENSIONS)[number]["key"];

// ---------------------------------------------------------------------------
// Topic slug -> radar dimension mapping
// ---------------------------------------------------------------------------

/**
 * Maps a CF tag to the radar dimension key that contains it.
 * Returns undefined if the tag does not belong to any dimension.
 */
export function cfTagToDimensionKey(tag: string): RadarDimensionKey | undefined {
  for (const dim of RADAR_DIMENSIONS) {
    if ((dim.tags as readonly string[]).includes(tag)) return dim.key;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Build radar data from M-Elo entries
// ---------------------------------------------------------------------------

/**
 * Build radar chart data points from per-tag M-Elo entries.
 *
 * Each dimension averages the available tag M-Elos (with shield fallback).
 * If no tags are available for a dimension, the global Elo (or 1200) is used.
 */
export function buildRadarDataFromMElo(
  melos: { tag: string; elo: number; shield_active: boolean }[],
  globalElo: number,
  t: (key: string) => string,
): RadarDataPoint[] {
  if (melos.length === 0) return [];

  // Build lookup: CF tag -> effective elo
  const eloByTag = new Map<string, number>();
  for (const m of melos) {
    eloByTag.set(m.tag, m.shield_active ? globalElo : m.elo);
  }

  const fallbackElo = globalElo || 1200;

  // Aggregate each dimension: average of available tags, fallback if none
  const raw: RadarDataPoint[] = RADAR_DIMENSIONS.map((dim) => {
    const values = dim.tags
      .map((tag) => eloByTag.get(tag))
      .filter((v): v is number => v !== undefined);

    const value = values.length > 0
      ? values.reduce((a, b) => a + b, 0) / values.length
      : fallbackElo;

    return {
      topic: t(`training:radar.dim.${dim.key}`),
      value,
      fullMark: 0, // placeholder, computed below
    };
  });

  const maxVal = Math.max(...raw.map((r) => r.value), 0.1);
  const fullMark = Math.max(maxVal * 1.3, maxVal + 0.1);
  return raw.map((r) => ({ ...r, fullMark }));
}
