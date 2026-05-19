/** PvE Challenge state management (Zustand).
 *
 * Manages the current PvE challenge session lifecycle:
 *   idle -> loading -> in_progress -> result
 *
 * Includes blind-box state: problem rating/tags are hidden until the
 * challenge is completed (revealed = true).
 */

import { create } from "zustand";

import * as pveApi from "@/services/pveChallengeApi";
import type {
  PvEStartResponse,
  PvEDetailResponse,
  PvESubmitResultResponse,
  PvEQuitResponse,
  PvEHistoryResponse,
} from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type PvEPhase = "idle" | "loading" | "in_progress" | "result";

interface PvEChallengeState {
  /** Current UI phase. */
  phase: PvEPhase;
  /** Error message to display. */
  error: string;

  // Session data
  sessionId: string;
  challenge: PvEDetailResponse | null;
  startResponse: PvEStartResponse | null;

  // Blind-box state
  revealed: boolean;

  // Result data
  submitResult: PvESubmitResultResponse | null;
  quitResult: PvEQuitResponse | null;

  // History
  history: PvEHistoryResponse | null;
  historyLoading: boolean;

  // Actions
  startChallenge: () => Promise<void>;
  fetchChallenge: (sessionId: string) => Promise<void>;
  submitResultAction: (
    solved: boolean,
    timeSpent: number,
    attempts: number,
    errorCount?: number,
  ) => Promise<void>;
  quitChallengeAction: (submissions: number) => Promise<void>;
  fetchHistory: (page?: number, pageSize?: number) => Promise<void>;
  reset: () => void;
}

// ---------------------------------------------------------------------------
// Initial state factory
// ---------------------------------------------------------------------------

const initialState = {
  phase: "idle" as PvEPhase,
  error: "",
  sessionId: "",
  challenge: null as PvEDetailResponse | null,
  startResponse: null as PvEStartResponse | null,
  revealed: false,
  submitResult: null as PvESubmitResultResponse | null,
  quitResult: null as PvEQuitResponse | null,
  history: null as PvEHistoryResponse | null,
  historyLoading: false,
};

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const usePvEChallengeStore = create<PvEChallengeState>((set, get) => ({
  ...initialState,

  startChallenge: async () => {
    set({ phase: "loading", error: "", sessionId: "", challenge: null, startResponse: null, revealed: false, submitResult: null, quitResult: null });
    try {
      const data = await pveApi.startChallenge();
      set({
        sessionId: data.session_id,
        startResponse: data,
        phase: "in_progress",
      });
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { error?: { message?: string }; detail?: string } } })
          ?.response?.data?.error?.message ??
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to start PvE challenge";
      set({ phase: "idle", error: message });
    }
  },

  fetchChallenge: async (sessionId: string) => {
    try {
      const data = await pveApi.getChallenge(sessionId);
      set({ challenge: data, sessionId });
      // Auto-reveal if challenge is completed
      if (data.status === "completed" || data.status === "quit") {
        set({ revealed: true, phase: "result" });
      }
    } catch {
      // Non-critical fetch, ignore
    }
  },

  submitResultAction: async (solved, timeSpent, attempts, errorCount = 0) => {
    set({ error: "" });
    const { sessionId } = get();
    try {
      const data = await pveApi.submitResult(sessionId, {
        solved,
        time_spent: timeSpent,
        attempts,
        error_count: errorCount,
      });
      // Fetch full challenge details for result display
      const detail = await pveApi.getChallenge(sessionId);
      set({
        submitResult: data,
        challenge: detail,
        revealed: true,
        phase: "result",
      });
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { error?: { message?: string }; detail?: string } } })
          ?.response?.data?.error?.message ??
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to submit result";
      set({ error: message });
    }
  },

  quitChallengeAction: async (submissions) => {
    set({ error: "" });
    const { sessionId } = get();
    try {
      const data = await pveApi.quitChallenge(sessionId, submissions);
      const detail = await pveApi.getChallenge(sessionId);
      set({
        quitResult: data,
        challenge: detail,
        revealed: true,
        phase: "result",
      });
    } catch (err: unknown) {
      const message =
        (err as { response?: { data?: { error?: { message?: string }; detail?: string } } })
          ?.response?.data?.error?.message ??
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to quit challenge";
      set({ error: message });
    }
  },

  fetchHistory: async (page = 1, pageSize = 20) => {
    set({ historyLoading: true });
    try {
      const data = await pveApi.getHistory(page, pageSize);
      set({ history: data, historyLoading: false });
    } catch {
      set({ historyLoading: false });
    }
  },

  reset: () => {
    set({ ...initialState });
  },
}));
