/** Training API client.
 *
 * Wraps the backend endpoints mounted at /api/v1/training/.
 */

import api from "@/services/api";
import type { ApiResponse, MEloListResponse } from "@/types";

// ---------------------------------------------------------------------------
// M-Elo (per-tag Elo) for radar chart
// ---------------------------------------------------------------------------

export async function getMElo(): Promise<MEloListResponse> {
  const res = await api.get<ApiResponse<MEloListResponse>>("/training/melo");
  return res.data.data;
}
