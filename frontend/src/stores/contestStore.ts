/** Contest state management (Zustand).
 *
 * Manages the live leaderboard state and WebSocket connection lifecycle
 * for the AI contest feature.
 */

import { create } from "zustand";

import {
  connectContestWs,
  getLeaderboard,
  type WsConnectionState,
} from "@/services/contestApi";
import type {
  LeaderboardResponse,
  LeaderboardEntry,
} from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ContestLiveState {
  /** Current WebSocket connection state. */
  wsState: WsConnectionState;
  /** The most recent leaderboard data. */
  leaderboard: LeaderboardEntry[];
  /** Time elapsed in the contest (minutes). */
  timeElapsed: number;
  /** Total contest duration (minutes). */
  timeTotal: number;
  /** Whether the contest has ended (received contest_ended message). */
  contestEnded: boolean;
  /** Error message for display. */
  error: string;

  // Actions
  /** Connect to the live leaderboard WebSocket for a contest. */
  connect: (contestId: string) => void;
  /** Disconnect the WebSocket. */
  disconnect: () => void;
  /** Fetch leaderboard via REST (fallback or initial load). */
  fetchLeaderboard: (contestId: string) => Promise<void>;
  /** Reset all state. */
  reset: () => void;
}

// ---------------------------------------------------------------------------
// Internal: disconnect function holder
// ---------------------------------------------------------------------------

let _disconnectFn: (() => void) | null = null;

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

const initialState = {
  wsState: "disconnected" as WsConnectionState,
  leaderboard: [] as LeaderboardEntry[],
  timeElapsed: 0,
  timeTotal: 0,
  contestEnded: false,
  error: "",
};

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useContestLiveStore = create<ContestLiveState>((set) => ({
  ...initialState,

  connect: (contestId: string) => {
    // Disconnect any existing connection
    if (_disconnectFn) {
      _disconnectFn();
      _disconnectFn = null;
    }

    set({ ...initialState, wsState: "connecting" });

    _disconnectFn = connectContestWs(contestId, {
      onLeaderboard: (data: LeaderboardResponse) => {
        set({
          leaderboard: data.leaderboard,
          timeElapsed: data.time_elapsed,
          timeTotal: data.time_total,
        });
      },
      onContestEnded: (data: LeaderboardResponse) => {
        set({
          leaderboard: data.leaderboard,
          timeElapsed: data.time_elapsed,
          timeTotal: data.time_total,
          contestEnded: true,
          wsState: "disconnected",
        });
      },
      onStateChange: (state: WsConnectionState) => {
        set({ wsState: state });
      },
    });
  },

  disconnect: () => {
    if (_disconnectFn) {
      _disconnectFn();
      _disconnectFn = null;
    }
  },

  fetchLeaderboard: async (contestId: string) => {
    try {
      const data = await getLeaderboard(contestId);
      set({
        leaderboard: data.leaderboard,
        timeElapsed: data.time_elapsed,
        timeTotal: data.time_total,
      });
    } catch {
      // Non-critical, keep existing data
    }
  },

  reset: () => {
    if (_disconnectFn) {
      _disconnectFn();
      _disconnectFn = null;
    }
    set({ ...initialState });
  },
}));
