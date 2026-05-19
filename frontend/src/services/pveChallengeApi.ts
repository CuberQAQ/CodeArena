/** PvE Challenge API client.
 *
 * Wraps the backend endpoints mounted at /api/v1/pve-challenge/.
 */

import api from "@/services/api";
import type {
  ApiResponse,
  PvEStartResponse,
  PvEDetailResponse,
  PvESubmitResultResponse,
  PvEQuitResponse,
  PvEHistoryResponse,
} from "@/types";

// ---------------------------------------------------------------------------
// Start a new PvE challenge
// ---------------------------------------------------------------------------

export async function startChallenge(): Promise<PvEStartResponse> {
  const res = await api.post<ApiResponse<PvEStartResponse>>("/pve-challenge/start");
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Get challenge detail
// ---------------------------------------------------------------------------

export async function getChallenge(sessionId: string): Promise<PvEDetailResponse> {
  const res = await api.get<ApiResponse<PvEDetailResponse>>(`/pve-challenge/${sessionId}`);
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Submit challenge result
// ---------------------------------------------------------------------------

export interface SubmitResultParams {
  solved: boolean;
  time_spent: number;
  attempts: number;
  error_count?: number;
}

export async function submitResult(
  sessionId: string,
  params: SubmitResultParams,
): Promise<PvESubmitResultResponse> {
  const res = await api.post<ApiResponse<PvESubmitResultResponse>>(
    `/pve-challenge/${sessionId}/submit`,
    params,
  );
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Quit challenge
// ---------------------------------------------------------------------------

export async function quitChallenge(
  sessionId: string,
  submissions: number,
): Promise<PvEQuitResponse> {
  const res = await api.post<ApiResponse<PvEQuitResponse>>(
    `/pve-challenge/${sessionId}/quit`,
    { submissions },
  );
  return res.data.data;
}

// ---------------------------------------------------------------------------
// Get paginated history
// ---------------------------------------------------------------------------

export async function getHistory(
  page = 1,
  pageSize = 20,
): Promise<PvEHistoryResponse> {
  const res = await api.get<ApiResponse<PvEHistoryResponse>>("/pve-challenge/history", {
    params: { page, page_size: pageSize },
  });
  return res.data.data;
}
