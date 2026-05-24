/** Training API client.
 *
 * Wraps the backend endpoints mounted at /api/v1/training/.
 */

import api from "@/services/api";
import type {
  ApiResponse,
  CuratedProblemsResponse,
  MEloListResponse,
  RecommendedProblem,
  RecommendedTopic,
  TrainingSessionInfo,
} from "@/types";

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

// ---------------------------------------------------------------------------
// Recommended topics (FR-3.5)
// ---------------------------------------------------------------------------

export async function getRecommendedTopics(
  limit = 3,
): Promise<RecommendedTopic[]> {
  const res = await api.get<ApiResponse<RecommendedTopic[]>>(
    "/training/recommended-topics",
    { params: { limit } },
  );
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Adaptive problem recommendation (FR-3.5)
// ---------------------------------------------------------------------------

export async function getRecommendedProblem(
  topicId: string,
): Promise<RecommendedProblem | null> {
  const res = await api.get<ApiResponse<RecommendedProblem | null>>(
    `/training/topics/${topicId}/recommend`,
  );
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Curated problem list with pagination (FR-3.5)
// ---------------------------------------------------------------------------

export async function getCuratedProblems(
  topicId: string,
  params?: {
    limit?: number;
    offset?: number;
    min_rating?: number;
    max_rating?: number;
  },
): Promise<CuratedProblemsResponse> {
  const res = await api.get<ApiResponse<CuratedProblemsResponse>>(
    `/training/topics/${topicId}/curated-problems`,
    { params },
  );
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Skip problem (FR-28.3) — skip current problem with optional Elo penalty
// ---------------------------------------------------------------------------

export async function skipProblem(
  sessionId: string,
  problemId: string,
): Promise<void> {
  await api.post(`/training/session/${sessionId}/skip-problem`, {
    problem_id: problemId,
  });
}
