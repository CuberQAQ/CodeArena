/** Contest API client.
 *
 * Wraps the backend endpoints mounted at /api/v1/contest/.
 * Also provides WebSocket connection management for live leaderboard updates.
 */

import api from "@/services/api";
import type {
  ApiResponse,
  LeaderboardResponse,
} from "@/types";

// ---------------------------------------------------------------------------
// REST: Get leaderboard for a contest
// ---------------------------------------------------------------------------

export async function getLeaderboard(contestId: string): Promise<LeaderboardResponse> {
  const res = await api.get<ApiResponse<LeaderboardResponse>>(
    `/contest/${contestId}/leaderboard`,
  );
  return res.data.data;
}

// ---------------------------------------------------------------------------
// WebSocket management
// ---------------------------------------------------------------------------

export type WsConnectionState = "disconnected" | "connecting" | "connected" | "error";

export interface ContestWsCallbacks {
  onLeaderboard: (data: LeaderboardResponse) => void;
  onContestEnded: (data: LeaderboardResponse) => void;
  onStateChange: (state: WsConnectionState) => void;
}

/** Build the WebSocket URL for a contest's live leaderboard endpoint. */
function buildWsUrl(contestId: string, token: string): string {
  const base = import.meta.env.VITE_WS_BASE_URL || "";
  // Determine protocol: wss for https, ws for http
  if (base.startsWith("https")) {
    return `${base.replace("https", "wss")}/api/v1/contest/${contestId}/live?token=${encodeURIComponent(token)}`;
  }
  if (base.startsWith("http")) {
    return `${base.replace("http", "ws")}/api/v1/contest/${contestId}/live?token=${encodeURIComponent(token)}`;
  }
  // Fallback: derive from current location
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  return `${proto}//${host}/api/v1/contest/${contestId}/live?token=${encodeURIComponent(token)}`;
}

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000];
const MAX_RECONNECT_ATTEMPTS = 5;

/**
 * Connect to the contest live leaderboard WebSocket.
 *
 * Returns a disconnect function. The WebSocket will auto-reconnect on failure
 * up to MAX_RECONNECT_ATTEMPTS times with exponential backoff.
 */
export function connectContestWs(
  contestId: string,
  callbacks: ContestWsCallbacks,
): () => void {
  let ws: WebSocket | null = null;
  let reconnectAttempt = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  function connect() {
    if (disposed) return;

    const token = localStorage.getItem("access_token");
    if (!token) {
      callbacks.onStateChange("error");
      return;
    }

    const url = buildWsUrl(contestId, token);
    callbacks.onStateChange("connecting");
    ws = new WebSocket(url);

    ws.onopen = () => {
      if (disposed) return;
      reconnectAttempt = 0;
      callbacks.onStateChange("connected");
    };

    ws.onmessage = (event) => {
      if (disposed) return;
      try {
        const payload = JSON.parse(event.data);

        // Check if this is a contest_ended message
        if (payload.type === "contest_ended" && payload.leaderboard) {
          callbacks.onContestEnded(payload.leaderboard);
          // Server will close the connection after this
          return;
        }

        // Regular leaderboard update
        if (payload.leaderboard !== undefined) {
          callbacks.onLeaderboard(payload as LeaderboardResponse);
        }
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = (event) => {
      if (disposed) return;
      ws = null;

      // Code 4001 = auth failed, 4003 = access denied -- do not reconnect
      if (event.code === 4001 || event.code === 4003) {
        callbacks.onStateChange("error");
        return;
      }

      // Attempt reconnect
      if (reconnectAttempt < MAX_RECONNECT_ATTEMPTS) {
        const delay = RECONNECT_DELAYS[reconnectAttempt] ?? 16000;
        reconnectAttempt++;
        callbacks.onStateChange("disconnected");
        reconnectTimer = setTimeout(connect, delay);
      } else {
        callbacks.onStateChange("error");
      }
    };

    ws.onerror = () => {
      // onclose will fire after onerror, so reconnect logic is handled there
    };
  }

  connect();

  // Return cleanup function
  return () => {
    disposed = true;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws !== null) {
      ws.close(1000, "Client disconnect");
      ws = null;
    }
    callbacks.onStateChange("disconnected");
  };
}
