/** Free Play API client.
 *
 * Wraps the backend endpoints mounted at /api/v1/free-play/.
 */

import api from "@/services/api";
import type {
  ApiResponse,
  FreePlaySearchResponse,
  FreePlayRecommendResponse,
  FreePlayStartResponse,
  FreePlaySubmitResponse,
  FreePlayQuitResponse,
} from "@/types";

// ---------------------------------------------------------------------------
// Search problems
// ---------------------------------------------------------------------------

export async function freePlaySearch(
  minRating: number,
  maxRating: number,
  tags: string[],
): Promise<FreePlaySearchResponse> {
  const res = await api.post<ApiResponse<FreePlaySearchResponse>>("/free-play/search", {
    min_rating: minRating,
    max_rating: maxRating,
    tags,
  });
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Get adaptive recommendation
// ---------------------------------------------------------------------------

export async function freePlayRecommend(): Promise<FreePlayRecommendResponse> {
  const res = await api.post<ApiResponse<FreePlayRecommendResponse>>("/free-play/recommend");
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Start a free play session
// ---------------------------------------------------------------------------

export interface FreePlayStartParams {
  problem_contest_id: number;
  problem_index: string;
  problem_rating: number;
  problem_tags: string[];
  problem_name: string;
}

export async function freePlayStart(params: FreePlayStartParams): Promise<FreePlayStartResponse> {
  const res = await api.post<ApiResponse<FreePlayStartResponse>>("/free-play/start", params);
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Submit result (manual fallback -- auto-tracking is preferred)
// ---------------------------------------------------------------------------

export interface FreePlaySubmitParams {
  solved: boolean;
  time_spent: number;
  attempts: number;
  error_count: number;
}

export async function freePlaySubmit(
  sessionId: string,
  params: FreePlaySubmitParams,
): Promise<FreePlaySubmitResponse> {
  const res = await api.post<ApiResponse<FreePlaySubmitResponse>>(
    `/free-play/${sessionId}/submit`,
    params,
  );
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Quit session
// ---------------------------------------------------------------------------

export async function freePlayQuit(sessionId: string): Promise<FreePlayQuitResponse> {
  const res = await api.post<ApiResponse<FreePlayQuitResponse>>(
    `/free-play/${sessionId}/quit`,
  );
  return res.data.data;
}
