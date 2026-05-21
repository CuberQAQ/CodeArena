import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useContestLiveStore } from "../contestStore";
import type { LeaderboardResponse, LeaderboardEntry } from "@/types";

// ---------------------------------------------------------------------------
// Mock the contestApi module
// ---------------------------------------------------------------------------

const mockGetLeaderboard = vi.fn();
const mockConnectContestWs = vi.fn();

vi.mock("@/services/contestApi", () => ({
  getLeaderboard: (...args: unknown[]) => mockGetLeaderboard(...args),
  connectContestWs: (...args: unknown[]) => mockConnectContestWs(...args),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const fakeLeaderboard: LeaderboardEntry[] = [
  {
    rank: 1,
    user_id: "u1",
    username: "alice",
    score: 100,
    solved: 5,
    penalty: 0,
  },
  {
    rank: 2,
    user_id: "u2",
    username: "bob",
    score: 80,
    solved: 4,
    penalty: 10,
  },
];

const fakeLeaderboardResponse: LeaderboardResponse = {
  leaderboard: fakeLeaderboard,
  time_elapsed: 30,
  time_total: 120,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useContestLiveStore", () => {
  beforeEach(() => {
    // Reset store to initial state
    useContestLiveStore.getState().reset();

    // Clear all mocks
    mockGetLeaderboard.mockReset();
    mockConnectContestWs.mockReset();
    vi.clearAllMocks();
  });

  afterEach(() => {
    useContestLiveStore.getState().reset();
  });

  // -----------------------------------------------------------------------
  // Initial state
  // -----------------------------------------------------------------------

  describe("initial state", () => {
    it("has correct default values", () => {
      const state = useContestLiveStore.getState();

      expect(state.wsState).toBe("disconnected");
      expect(state.leaderboard).toEqual([]);
      expect(state.timeElapsed).toBe(0);
      expect(state.timeTotal).toBe(0);
      expect(state.contestEnded).toBe(false);
      expect(state.error).toBe("");
    });
  });

  // -----------------------------------------------------------------------
  // reset
  // -----------------------------------------------------------------------

  describe("reset", () => {
    it("resets all state to initial values and disconnects ws", () => {
      const disconnectFn = vi.fn();
      mockConnectContestWs.mockReturnValueOnce(disconnectFn);

      useContestLiveStore.getState().connect("contest-1");

      // Simulate some state
      useContestLiveStore.setState({
        wsState: "connected",
        leaderboard: fakeLeaderboard,
        timeElapsed: 30,
        timeTotal: 120,
        contestEnded: false,
      });

      useContestLiveStore.getState().reset();

      const state = useContestLiveStore.getState();
      expect(state.wsState).toBe("disconnected");
      expect(state.leaderboard).toEqual([]);
      expect(state.timeElapsed).toBe(0);
      expect(state.timeTotal).toBe(0);
      expect(state.contestEnded).toBe(false);
      expect(state.error).toBe("");
      // The disconnect function from the first connect should have been called
      expect(disconnectFn).toHaveBeenCalled();
    });
  });

  // -----------------------------------------------------------------------
  // connect
  // -----------------------------------------------------------------------

  describe("connect", () => {
    it("disconnects existing connection before creating a new one", () => {
      const firstDisconnect = vi.fn();
      const secondDisconnect = vi.fn();
      mockConnectContestWs
        .mockReturnValueOnce(firstDisconnect)
        .mockReturnValueOnce(secondDisconnect);

      useContestLiveStore.getState().connect("contest-1");
      expect(firstDisconnect).not.toHaveBeenCalled();

      useContestLiveStore.getState().connect("contest-2");
      expect(firstDisconnect).toHaveBeenCalledOnce();
    });

    it("resets state and sets wsState to connecting", () => {
      mockConnectContestWs.mockReturnValueOnce(vi.fn());

      // Set some prior state
      useContestLiveStore.setState({
        leaderboard: fakeLeaderboard,
        timeElapsed: 50,
        contestEnded: true,
        error: "old error",
      });

      useContestLiveStore.getState().connect("contest-1");

      const state = useContestLiveStore.getState();
      expect(state.wsState).toBe("connecting");
      expect(state.leaderboard).toEqual([]);
      expect(state.timeElapsed).toBe(0);
      expect(state.timeTotal).toBe(0);
      expect(state.contestEnded).toBe(false);
      expect(state.error).toBe("");
    });

    it("passes contestId and callbacks to connectContestWs", () => {
      mockConnectContestWs.mockReturnValueOnce(vi.fn());

      useContestLiveStore.getState().connect("contest-abc");

      expect(mockConnectContestWs).toHaveBeenCalledOnce();
      const [contestId, callbacks] = mockConnectContestWs.mock.calls[0];
      expect(contestId).toBe("contest-abc");
      expect(callbacks).toHaveProperty("onLeaderboard");
      expect(callbacks).toHaveProperty("onContestEnded");
      expect(callbacks).toHaveProperty("onStateChange");
    });

    it("onLeaderboard callback updates leaderboard, timeElapsed, timeTotal", () => {
      mockConnectContestWs.mockImplementationOnce((_id: string, callbacks: Record<string, (...args: unknown[]) => void>) => {
        // Immediately fire a leaderboard update
        callbacks.onLeaderboard(fakeLeaderboardResponse);
        return vi.fn();
      });

      useContestLiveStore.getState().connect("contest-1");

      const state = useContestLiveStore.getState();
      expect(state.leaderboard).toEqual(fakeLeaderboard);
      expect(state.timeElapsed).toBe(30);
      expect(state.timeTotal).toBe(120);
    });

    it("onContestEnded callback sets contestEnded=true and wsState=disconnected", () => {
      const endedResponse: LeaderboardResponse = {
        leaderboard: fakeLeaderboard,
        time_elapsed: 120,
        time_total: 120,
      };

      mockConnectContestWs.mockImplementationOnce((_id: string, callbacks: Record<string, (...args: unknown[]) => void>) => {
        callbacks.onContestEnded(endedResponse);
        return vi.fn();
      });

      useContestLiveStore.getState().connect("contest-1");

      const state = useContestLiveStore.getState();
      expect(state.contestEnded).toBe(true);
      expect(state.wsState).toBe("disconnected");
      expect(state.leaderboard).toEqual(fakeLeaderboard);
      expect(state.timeElapsed).toBe(120);
      expect(state.timeTotal).toBe(120);
    });

    it("onStateChange callback updates wsState", () => {
      mockConnectContestWs.mockImplementationOnce((_id: string, callbacks: Record<string, (...args: unknown[]) => void>) => {
        callbacks.onStateChange("connected");
        return vi.fn();
      });

      useContestLiveStore.getState().connect("contest-1");

      expect(useContestLiveStore.getState().wsState).toBe("connected");
    });
  });

  // -----------------------------------------------------------------------
  // disconnect
  // -----------------------------------------------------------------------

  describe("disconnect", () => {
    it("calls the stored disconnect function and clears it", () => {
      const disconnectFn = vi.fn();
      mockConnectContestWs.mockReturnValueOnce(disconnectFn);

      useContestLiveStore.getState().connect("contest-1");
      expect(disconnectFn).not.toHaveBeenCalled();

      useContestLiveStore.getState().disconnect();
      expect(disconnectFn).toHaveBeenCalledOnce();
    });

    it("does nothing when no connection exists", () => {
      // reset() first to clear any state
      useContestLiveStore.getState().reset();

      // Should not throw
      useContestLiveStore.getState().disconnect();
    });
  });

  // -----------------------------------------------------------------------
  // fetchLeaderboard
  // -----------------------------------------------------------------------

  describe("fetchLeaderboard", () => {
    it("fetches and sets leaderboard data via REST", async () => {
      mockGetLeaderboard.mockResolvedValueOnce(fakeLeaderboardResponse);

      await useContestLiveStore.getState().fetchLeaderboard("contest-1");

      expect(mockGetLeaderboard).toHaveBeenCalledWith("contest-1");

      const state = useContestLiveStore.getState();
      expect(state.leaderboard).toEqual(fakeLeaderboard);
      expect(state.timeElapsed).toBe(30);
      expect(state.timeTotal).toBe(120);
    });

    it("silently handles errors and preserves existing data", async () => {
      // Set some existing data
      useContestLiveStore.setState({
        leaderboard: fakeLeaderboard,
        timeElapsed: 10,
        timeTotal: 60,
      });

      mockGetLeaderboard.mockRejectedValueOnce(new Error("Network error"));

      // Should not throw
      await useContestLiveStore.getState().fetchLeaderboard("contest-1");

      // Existing data should be preserved
      const state = useContestLiveStore.getState();
      expect(state.leaderboard).toEqual(fakeLeaderboard);
      expect(state.timeElapsed).toBe(10);
      expect(state.timeTotal).toBe(60);
    });
  });
});
