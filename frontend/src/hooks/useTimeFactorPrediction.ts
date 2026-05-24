/**
 * Shared hook for time-factor-prediction API requests.
 *
 * Deduplicates concurrent requests for the same parameters so that
 * EloProgressBar and SolvingTimeline on the same page share one API call
 * instead of firing two independent requests.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import api from "@/services/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TimePoint {
  minutes: number;
  time_factor: number;
  elo_change_estimate: number;
}

export interface PredictionData {
  expected_time_minutes: number;
  time_points: TimePoint[];
}

// ---------------------------------------------------------------------------
// In-flight dedup cache (module-level, shared across hook instances)
// ---------------------------------------------------------------------------

const _pendingRequests = new Map<string, Promise<PredictionData>>();

function makeCacheKey(
  problemId: string,
  problemRating: number,
  userElo: number,
): string {
  return `${problemId}:${problemRating}:${Math.round(userElo)}`;
}

async function fetchPrediction(
  problemId: string,
  problemRating: number,
  userElo: number,
): Promise<PredictionData> {
  const key = makeCacheKey(problemId, problemRating, userElo);

  // Reuse in-flight request if one already exists for the same params
  const pending = _pendingRequests.get(key);
  if (pending) return pending;

  const promise = (async () => {
    try {
      const res = await api.get("/time-factor-prediction", {
        params: {
          problem_id: problemId,
          problem_rating: problemRating,
          user_elo: Math.round(userElo),
        },
      });
      return res.data.data as PredictionData;
    } finally {
      // Clean up after settlement so a future call can retry
      _pendingRequests.delete(key);
    }
  })();

  _pendingRequests.set(key, promise);
  return promise;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export interface UsePredictionResult {
  prediction: PredictionData | null;
  loading: boolean;
  error: boolean;
  refetch: () => void;
}

export function useTimeFactorPrediction(
  problemId: string | null | undefined,
  problemRating: number | null | undefined,
  userElo: number | null | undefined,
): UsePredictionResult {
  const [prediction, setPrediction] = useState<PredictionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const fetchIdRef = useRef(0);

  const refetch = useCallback(() => {
    if (!problemId || !problemRating || userElo == null) return;

    const thisFetchId = ++fetchIdRef.current;
    setLoading(true);
    setError(false);

    fetchPrediction(problemId, problemRating, userElo)
      .then((data) => {
        if (fetchIdRef.current === thisFetchId) {
          setPrediction(data);
        }
      })
      .catch(() => {
        if (fetchIdRef.current === thisFetchId) {
          setError(true);
        }
      })
      .finally(() => {
        if (fetchIdRef.current === thisFetchId) {
          setLoading(false);
        }
      });
  }, [problemId, problemRating, userElo]);

  // Fetch on mount and when params change
  useEffect(() => {
    refetch();
  }, [refetch]);

  return { prediction, loading, error, refetch };
}
