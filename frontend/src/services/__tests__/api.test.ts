import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import axios from "axios";

// ---------------------------------------------------------------------------
// Strategy: The api.ts module registers interceptors on an axios instance at
// import time. We cannot easily re-import it to re-trigger initialization,
// so we test the interceptor logic in a different way.
//
// For the request interceptor, we directly call the real api instance and
// inspect the config it sends. For the response interceptor, we extract
// the interceptor handlers from the axios instance's interceptor manager
// and invoke them with controlled error objects.
//
// However, the simplest and most reliable approach is to test the real api
// module end-to-end by providing a custom axios adapter that captures the
// request config and returns controlled responses.
// ---------------------------------------------------------------------------

// Import the real api instance. Its interceptors are already registered.
import api from "../api";

// ---------------------------------------------------------------------------
// Helper: create a mock adapter function that we can control per-test
// ---------------------------------------------------------------------------

function createMockAdapter() {
  let handler: (config: Record<string, unknown>) => Promise<unknown>;

  const adapter = (config: Record<string, unknown>) => handler(config);
  const setHandler = (fn: (config: Record<string, unknown>) => Promise<unknown>) => {
    handler = fn;
  };

  // Default: return a generic success
  setHandler(async (config) => ({
    data: { success: true, data: {}, message: "ok" },
    status: 200,
    statusText: "OK",
    headers: {},
    config,
  }));

  return { adapter, setHandler };
}

describe("API service", () => {
  const { adapter, setHandler } = createMockAdapter();
  const originalAdapter = api.defaults.adapter;

  beforeEach(() => {
    localStorage.clear();
    // Install our mock adapter on the real api instance
    api.defaults.adapter = adapter as never;
  });

  afterEach(() => {
    api.defaults.adapter = originalAdapter;
    localStorage.clear();
    vi.restoreAllMocks();
  });

  // -----------------------------------------------------------------------
  // Request interceptor — attach Bearer token
  // -----------------------------------------------------------------------

  describe("request interceptor", () => {
    it("attaches Bearer token when access_token exists in localStorage", async () => {
      localStorage.setItem("access_token", "my-jwt-token");

      let capturedConfig: Record<string, unknown> = {};
      setHandler(async (config) => {
        capturedConfig = config;
        return { data: { success: true, data: {}, message: "ok" }, status: 200, statusText: "OK", headers: {}, config };
      });

      await api.get("/test");

      expect(capturedConfig.headers).toHaveProperty("Authorization", "Bearer my-jwt-token");
    });

    it("does not attach Authorization header when no token in localStorage", async () => {
      let capturedConfig: Record<string, unknown> = {};
      setHandler(async (config) => {
        capturedConfig = config;
        return { data: { success: true, data: {}, message: "ok" }, status: 200, statusText: "OK", headers: {}, config };
      });

      await api.get("/test");

      // Axios default headers may exist, but no Authorization
      const authHeader = (capturedConfig.headers as Record<string, unknown>)?.Authorization;
      expect(authHeader).toBeUndefined();
    });
  });

  // -----------------------------------------------------------------------
  // Response interceptor — 401 handling
  // -----------------------------------------------------------------------

  describe("response interceptor — 401 handling", () => {
    it("clears tokens and rejects when no refresh token is available", async () => {
      localStorage.setItem("access_token", "expired-at");

      setHandler(async (config) => {
        // First call: return 401
        const err: Record<string, unknown> = {
          response: { status: 401, data: { success: false } },
          config,
          code: "ERR_BAD_RESPONSE",
        };
        return Promise.reject(Object.assign(new Error("401"), err));
      });

      await expect(api.get("/protected")).rejects.toThrow();
      expect(localStorage.getItem("access_token")).toBeNull();
      expect(localStorage.getItem("refresh_token")).toBeNull();
    });

    it("refreshes token and retries original request on 401", async () => {
      localStorage.setItem("access_token", "expired-at");
      localStorage.setItem("refresh_token", "valid-rt");

      let callCount = 0;

      // Spy on axios.post for the refresh call (it uses the raw axios, not our instance)
      const postSpy = vi.spyOn(axios, "post").mockResolvedValue({
        data: { data: { access_token: "new-at" } },
      });

      setHandler(async (config) => {
        callCount++;
        // First call: reject with 401
        if (callCount === 1) {
          const err: Record<string, unknown> = {
            response: { status: 401, data: { success: false } },
            config,
            code: "ERR_BAD_RESPONSE",
          };
          return Promise.reject(Object.assign(new Error("401"), err));
        }
        // Retry after refresh: succeed
        return { data: { success: true, data: { retried: true }, message: "ok" }, status: 200, statusText: "OK", headers: {}, config };
      });

      await api.get("/protected");

      // Refresh was called with the refresh token
      expect(postSpy).toHaveBeenCalledWith(
        expect.stringContaining("/auth/refresh"),
        { refresh_token: "valid-rt" },
      );

      // New token stored
      expect(localStorage.getItem("access_token")).toBe("new-at");

      // The retry succeeded (adapter was called twice)
      expect(callCount).toBe(2);

      postSpy.mockRestore();
    });

    it("clears tokens when refresh fails", async () => {
      localStorage.setItem("access_token", "expired-at");
      localStorage.setItem("refresh_token", "bad-rt");

      const postSpy = vi.spyOn(axios, "post").mockRejectedValue(new Error("Refresh failed"));

      setHandler(async (config) => {
        // First call: reject with 401
        const err: Record<string, unknown> = {
          response: { status: 401, data: { success: false } },
          config,
          code: "ERR_BAD_RESPONSE",
        };
        return Promise.reject(Object.assign(new Error("401"), err));
      });

      await expect(api.get("/protected")).rejects.toThrow("Refresh failed");

      expect(localStorage.getItem("access_token")).toBeNull();
      expect(localStorage.getItem("refresh_token")).toBeNull();

      postSpy.mockRestore();
    });

    it("does not try to refresh for failed login requests", async () => {
      localStorage.setItem("access_token", "some-at");
      localStorage.setItem("refresh_token", "some-rt");

      const postSpy = vi.spyOn(axios, "post").mockResolvedValue({
        data: { data: { access_token: "new-at" } },
      });

      setHandler(async (config) => {
        const err: Record<string, unknown> = {
          response: { status: 401, data: { success: false } },
          config,
          code: "ERR_BAD_RESPONSE",
        };
        return Promise.reject(Object.assign(new Error("401"), err));
      });

      await expect(api.post("/auth/login", { email: "a@b.com", password: "x" })).rejects.toThrow();

      // Should NOT have called refresh
      expect(postSpy).not.toHaveBeenCalledWith(
        expect.stringContaining("/auth/refresh"),
        expect.anything(),
      );

      postSpy.mockRestore();
    });

    it("shares a single refresh request among concurrent 401s", async () => {
      localStorage.setItem("access_token", "expired-at");
      localStorage.setItem("refresh_token", "valid-rt");

      let resolveRefresh: (value: unknown) => void;
      const refreshPromise = new Promise((resolve) => {
        resolveRefresh = resolve;
      });

      const postSpy = vi.spyOn(axios, "post").mockReturnValue(refreshPromise);

      setHandler(async (config) => {
        // All calls: reject with 401
        const err: Record<string, unknown> = {
          response: { status: 401, data: { success: false } },
          config,
          code: "ERR_BAD_RESPONSE",
        };
        return Promise.reject(Object.assign(new Error("401"), err));
      });

      // Fire two concurrent requests
      const promise1 = api.get("/a");
      const promise2 = api.get("/b");

      // Allow microtasks to run so both 401s are processed
      await new Promise((r) => setTimeout(r, 0));

      // Only one refresh call should have been made
      expect(postSpy).toHaveBeenCalledTimes(1);

      // Resolve the refresh - this will retry both requests
      resolveRefresh!({ data: { data: { access_token: "shared-at" } } });

      // Now update the handler to succeed on retries
      let retryCount = 0;
      setHandler(async (config) => {
        retryCount++;
        return { data: { success: true, data: { retry: retryCount }, message: "ok" }, status: 200, statusText: "OK", headers: {}, config };
      });

      // Both should eventually resolve (they retry with the shared token)
      const results = await Promise.allSettled([promise1, promise2]);

      // At least one of them should have fulfilled (the retry with new token)
      const fulfilled = results.filter((r) => r.status === "fulfilled");
      expect(fulfilled.length).toBeGreaterThanOrEqual(1);

      postSpy.mockRestore();
    });
  });
});
