import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { LeaderboardResponse, LeaderboardEntry } from "@/types";

// ---------------------------------------------------------------------------
// Mock the api module so no real HTTP requests are made
// ---------------------------------------------------------------------------

const mockGet = vi.fn();

vi.mock("@/services/api", () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}));

// Mock WebSocket constructor
const mockWsInstances: Array<{
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onclose: ((event: { code: number; reason?: string }) => void) | null;
  onerror: (() => void) | null;
  close: ReturnType<typeof vi.fn>;
  readyState: number;
}> = [];

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { code: number; reason?: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  readyState = MockWebSocket.CONNECTING;

  constructor(public url: string) {
    mockWsInstances.push(this);
  }
}

// Import after mocks are set up
import { getLeaderboard, connectContestWs } from "../contestApi";

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

function makeApiReply<T>(data: T) {
  return { data: { success: true, data, message: "ok" } };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("contestApi", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockGet.mockReset();
    mockWsInstances.length = 0;
    localStorage.clear();

    // Replace global WebSocket with mock
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  // -----------------------------------------------------------------------
  // getLeaderboard
  // -----------------------------------------------------------------------

  describe("getLeaderboard", () => {
    it("calls api.get with correct URL and returns leaderboard data", async () => {
      mockGet.mockResolvedValueOnce(makeApiReply(fakeLeaderboardResponse));

      const result = await getLeaderboard("contest-123");

      expect(mockGet).toHaveBeenCalledWith("/contest/contest-123/leaderboard");
      expect(result).toEqual(fakeLeaderboardResponse);
    });

    it("propagates errors from api.get", async () => {
      mockGet.mockRejectedValueOnce(new Error("Network error"));

      await expect(getLeaderboard("contest-123")).rejects.toThrow("Network error");
    });
  });

  // -----------------------------------------------------------------------
  // connectContestWs
  // -----------------------------------------------------------------------

  describe("connectContestWs", () => {
    it("sets state to error when no token in localStorage", () => {
      localStorage.clear();

      const onStateChange = vi.fn();
      const onLeaderboard = vi.fn();
      const onContestEnded = vi.fn();

      connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard,
        onContestEnded,
      });

      expect(onStateChange).toHaveBeenCalledWith("error");
    });

    it("creates a WebSocket connection with correct URL", () => {
      localStorage.setItem("access_token", "my-token");

      const onStateChange = vi.fn();
      connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      expect(mockWsInstances.length).toBe(1);
      expect(mockWsInstances[0].url).toContain("/api/v1/contest/contest-123/live");
      expect(mockWsInstances[0].url).toContain("token=my-token");
      expect(onStateChange).toHaveBeenCalledWith("connecting");
    });

    it("uses fallback protocol derivation when no VITE_WS_BASE_URL is set", () => {
      // In test env, import.meta.env.VITE_WS_BASE_URL is empty, so buildWsUrl
      // falls through to the window.location-based derivation.
      // jsdom sets window.location.protocol to "http:" by default,
      // so we should see ws: protocol.
      localStorage.setItem("access_token", "my-token");

      connectContestWs("contest-456", {
        onStateChange: vi.fn(),
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      const wsInstance = mockWsInstances[mockWsInstances.length - 1];
      expect(wsInstance.url).toContain("ws:");
      expect(wsInstance.url).toContain("/api/v1/contest/contest-456/live");
    });

    it("fires onStateChange('connected') on ws open and resets reconnect attempt", () => {
      localStorage.setItem("access_token", "my-token");

      const onStateChange = vi.fn();
      connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];
      ws.onopen!();

      expect(onStateChange).toHaveBeenCalledWith("connected");
    });

    it("fires onLeaderboard when receiving leaderboard message", () => {
      localStorage.setItem("access_token", "my-token");

      const onLeaderboard = vi.fn();
      connectContestWs("contest-123", {
        onStateChange: vi.fn(),
        onLeaderboard,
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];
      ws.onopen!();

      const payload = JSON.stringify({
        leaderboard: fakeLeaderboard,
        time_elapsed: 30,
        time_total: 120,
      });
      ws.onmessage!({ data: payload });

      expect(onLeaderboard).toHaveBeenCalledWith({
        leaderboard: fakeLeaderboard,
        time_elapsed: 30,
        time_total: 120,
      });
    });

    it("fires onContestEnded when receiving contest_ended message", () => {
      localStorage.setItem("access_token", "my-token");

      const onContestEnded = vi.fn();
      const onStateChange = vi.fn();
      connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded,
      });

      const ws = mockWsInstances[0];
      ws.onopen!();

      const payload = JSON.stringify({
        type: "contest_ended",
        leaderboard: {
          leaderboard: fakeLeaderboard,
          time_elapsed: 60,
          time_total: 120,
        },
      });
      ws.onmessage!({ data: payload });

      expect(onContestEnded).toHaveBeenCalledWith({
        leaderboard: fakeLeaderboard,
        time_elapsed: 60,
        time_total: 120,
      });
    });

    it("ignores malformed JSON messages", () => {
      localStorage.setItem("access_token", "my-token");

      const onLeaderboard = vi.fn();
      connectContestWs("contest-123", {
        onStateChange: vi.fn(),
        onLeaderboard,
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];
      ws.onopen!();

      // Should not throw
      ws.onmessage!({ data: "not valid json {{{" });
      expect(onLeaderboard).not.toHaveBeenCalled();
    });

    it("ignores messages without leaderboard field", () => {
      localStorage.setItem("access_token", "my-token");

      const onLeaderboard = vi.fn();
      connectContestWs("contest-123", {
        onStateChange: vi.fn(),
        onLeaderboard,
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];
      ws.onopen!();

      ws.onmessage!({ data: JSON.stringify({ type: "heartbeat" }) });
      expect(onLeaderboard).not.toHaveBeenCalled();
    });

    it("attempts reconnection with exponential backoff on close", () => {
      localStorage.setItem("access_token", "my-token");

      const onStateChange = vi.fn();
      connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];
      ws.onopen!();

      // Simulate close with a normal code
      ws.onclose!({ code: 1000 });

      expect(onStateChange).toHaveBeenCalledWith("disconnected");

      // Advance timers for first reconnect delay (1000ms)
      vi.advanceTimersByTime(1000);

      // Should have created a new WebSocket instance
      expect(mockWsInstances.length).toBe(2);
    });

    it("does not reconnect on auth failure codes (4001, 4003)", () => {
      localStorage.setItem("access_token", "my-token");

      const onStateChange = vi.fn();
      connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];

      // Auth failure code 4001
      ws.onclose!({ code: 4001 });
      expect(onStateChange).toHaveBeenCalledWith("error");

      // Advance timers - should not reconnect
      vi.advanceTimersByTime(20000);
      expect(mockWsInstances.length).toBe(1);
    });

    it("does not reconnect on access denied code 4003", () => {
      localStorage.setItem("access_token", "my-token");

      const onStateChange = vi.fn();
      connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];

      ws.onclose!({ code: 4003 });
      expect(onStateChange).toHaveBeenCalledWith("error");

      vi.advanceTimersByTime(20000);
      expect(mockWsInstances.length).toBe(1);
    });

    it("stops reconnecting after MAX_RECONNECT_ATTEMPTS (5)", () => {
      localStorage.setItem("access_token", "my-token");

      const onStateChange = vi.fn();
      connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      // Simulate 5 reconnect cycles. The initial connect creates WS #1.
      // Each onclose increments reconnectAttempt and schedules a new connect.
      // After 5 successful reconnects (reconnectAttempt=5), the next onclose
      // hits the else branch and calls onStateChange("error").
      const delays = [1000, 2000, 4000, 8000, 16000];
      for (let i = 0; i < 5; i++) {
        const ws = mockWsInstances[mockWsInstances.length - 1];
        ws.onclose!({ code: 1000 }); // Normal close, trigger reconnect
        vi.advanceTimersByTime(delays[i] + 100); // Advance past the delay
      }

      // Now reconnectAttempt is 5. The last connect() created WS #6.
      // Fire onclose on it to trigger the "max attempts exceeded" branch.
      const lastWs = mockWsInstances[mockWsInstances.length - 1];
      lastWs.onclose!({ code: 1000 });

      // Should have called error
      expect(onStateChange).toHaveBeenCalledWith("error");

      // No more reconnections after error
      const countAfterMax = mockWsInstances.length;
      vi.advanceTimersByTime(30000);
      expect(mockWsInstances.length).toBe(countAfterMax);
    });

    it("returns a disconnect function that closes ws and cleans up", () => {
      localStorage.setItem("access_token", "my-token");

      const onStateChange = vi.fn();
      const disconnect = connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];

      disconnect();

      expect(ws.close).toHaveBeenCalledWith(1000, "Client disconnect");
      expect(onStateChange).toHaveBeenCalledWith("disconnected");
    });

    it("disconnect function prevents pending reconnects", () => {
      localStorage.setItem("access_token", "my-token");

      const onStateChange = vi.fn();
      const disconnect = connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];
      ws.onclose!({ code: 1000 }); // Triggers reconnect timer

      disconnect();

      // Advance timers - should not reconnect since we disconnected
      const countBefore = mockWsInstances.length;
      vi.advanceTimersByTime(2000);
      expect(mockWsInstances.length).toBe(countBefore);
    });

    it("ignores onopen/onmessage/onclose after disposal", () => {
      localStorage.setItem("access_token", "my-token");

      const onLeaderboard = vi.fn();
      const onStateChange = vi.fn();
      const disconnect = connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard,
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];
      disconnect();

      // These should be no-ops after disposal
      ws.onopen!();
      ws.onmessage!({ data: JSON.stringify({ leaderboard: fakeLeaderboard }) });
      ws.onclose!({ code: 1000 });

      // Only the "disconnected" from disconnect(), nothing else
      expect(onStateChange).toHaveBeenCalledWith("disconnected");
      expect(onLeaderboard).not.toHaveBeenCalled();
    });

    it("onerror does not directly change state (onclose handles it)", () => {
      localStorage.setItem("access_token", "my-token");

      const onStateChange = vi.fn();
      connectContestWs("contest-123", {
        onStateChange,
        onLeaderboard: vi.fn(),
        onContestEnded: vi.fn(),
      });

      const ws = mockWsInstances[0];

      // onerror by itself does not call onStateChange beyond what was already called
      const callsBefore = onStateChange.mock.calls.length;
      ws.onerror!();
      // Should not have added any new state change calls from onerror alone
      expect(onStateChange.mock.calls.length).toBe(callsBefore);
    });
  });
});
