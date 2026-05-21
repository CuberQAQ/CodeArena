/** Problem Statement API client.
 *
 * Wraps the backend endpoints mounted at /api/v1/problem/.
 */

import api from "@/services/api";
import type { ApiResponse } from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SampleTest {
  input: string;
  output: string;
}

export interface ProblemStatementData {
  problem_id: string;
  contest_id: number;
  index: string;
  title: string;
  time_limit: string | null;
  memory_limit: string | null;
  body_html: string;
  input_spec_html: string | null;
  output_spec_html: string | null;
  samples: SampleTest[];
  note_html: string | null;
  full_html: string;
  scraped_at: string;
  cached: boolean;
  fallback_url: string;
}

export interface CacheCheckResult {
  cached: string[];
  not_cached: string[];
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

/**
 * Fetch a problem statement by problem_id.
 *
 * The backend will return from cache or scrape on demand.
 * On scrape failure the backend returns HTTP 503.
 */
export async function getProblemStatement(
  problemId: string,
): Promise<ProblemStatementData> {
  const res = await api.get<ApiResponse<ProblemStatementData>>(
    `/problem/${problemId}/statement`,
  );
  return res.data.data;
}

/**
 * Batch-check which problem statements are already cached.
 *
 * @param problemIds - Array of problem IDs (e.g. ["1920A", "1920B"])
 */
export async function checkProblemCache(
  problemIds: string[],
): Promise<CacheCheckResult> {
  const ids = problemIds.join(",");
  const res = await api.get<ApiResponse<CacheCheckResult>>(
    `/problem/statements/check`,
    { params: { problem_ids: ids } },
  );
  return res.data.data;
}
