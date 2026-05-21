/** Training API client.
 *
 * Wraps the backend endpoints mounted at /api/v1/training/.
 */

import api from "@/services/api";
import type { ApiResponse, MEloListResponse, TrainingSessionInfo } from "@/types";

// ---------------------------------------------------------------------------
// M-Elo (per-tag Elo) for radar chart
// ---------------------------------------------------------------------------

export async function getMElo(): Promise<MEloListResponse> {
  const res = await api.get<ApiResponse<MEloListResponse>>("/training/melo");
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Get active session for a topic (session recovery)
// ---------------------------------------------------------------------------

export async function getActiveTrainingSession(
  topicId: string,
): Promise<TrainingSessionInfo | null> {
  const res = await api.get<ApiResponse<TrainingSessionInfo | null>>(
    `/training/topics/${topicId}/active-session`,
  );
  return res.data.data;
}
