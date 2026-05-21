import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAuthStore } from "../auth";
import type { UserInfo, ApiResponse, RegisterResponse } from "@/types";

// ---------------------------------------------------------------------------
// Mock the API module so no real HTTP requests are made
// ---------------------------------------------------------------------------

const mockPost = vi.fn();
const mockGet = vi.fn();

vi.mock("@/services/api", () => ({
  default: {
    post: (...args: unknown[]) => mockPost(...args),
    get: (...args: unknown[]) => mockGet(...args),
  },
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const fakeUser: UserInfo = {
  id: "user-1",
  username: "testuser",
  email: "test@example.com",
  cf_handle: null,
  cf_handle_verified: false,
  elo: 1500,
  pp: 100,
  tokens: 50,
  is_active: true,
  is_admin: false,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: null,
  last_login_at: null,
};

function makeApiReply<T>(data: T): { data: ApiResponse<T> } {
  return { data: { success: true, data, message: "ok" } };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useAuthStore", () => {
  beforeEach(() => {
    // Reset zustand store to initial state before each test
    useAuthStore.setState({
      user: null,
      isAuthenticated: false,
      isLoading: true,
    });

    // Clear all mocks
    mockPost.mockReset();
    mockGet.mockReset();
    localStorage.clear();
    vi.clearAllMocks();
  });

  // -----------------------------------------------------------------------
  // login
  // -----------------------------------------------------------------------

  describe("login", () => {
    it("calls api.post /auth/login then api.get /auth/me, and sets user + isAuthenticated", async () => {
      // Step 1: login returns tokens
      mockPost.mockResolvedValueOnce(
        makeApiReply({
          access_token: "at-123",
          refresh_token: "rt-456",
          token_type: "bearer",
        }),
      );
      // Step 2: fetch /auth/me returns user profile
      mockGet.mockResolvedValueOnce(makeApiReply(fakeUser));

      await useAuthStore.getState().login("test@example.com", "password123");

      // Verify API calls
      expect(mockPost).toHaveBeenCalledWith("/auth/login", {
        email: "test@example.com",
        password: "password123",
      });
      expect(mockGet).toHaveBeenCalledWith("/auth/me");

      // Verify store state
      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(true);
      expect(state.user).toEqual(fakeUser);

      // Verify tokens persisted to localStorage
      expect(localStorage.getItem("access_token")).toBe("at-123");
      expect(localStorage.getItem("refresh_token")).toBe("rt-456");
    });

    it("throws and does not set user when login API fails", async () => {
      mockPost.mockRejectedValueOnce(new Error("Invalid credentials"));

      await expect(
        useAuthStore.getState().login("bad@example.com", "wrong"),
      ).rejects.toThrow("Invalid credentials");

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.user).toBeNull();
    });
  });

  // -----------------------------------------------------------------------
  // register
  // -----------------------------------------------------------------------

  describe("register", () => {
    it("calls api.post /auth/register and sets user + isAuthenticated", async () => {
      const registerResponse: RegisterResponse = {
        user: fakeUser,
        tokens: {
          access_token: "at-reg",
          refresh_token: "rt-reg",
          token_type: "bearer",
        },
      };
      mockPost.mockResolvedValueOnce(makeApiReply(registerResponse));

      await useAuthStore
        .getState()
        .register("testuser", "test@example.com", "password123");

      expect(mockPost).toHaveBeenCalledWith("/auth/register", {
        username: "testuser",
        email: "test@example.com",
        password: "password123",
      });

      const state = useAuthStore.getState();
      expect(state.user).toEqual(fakeUser);
      expect(state.isAuthenticated).toBe(true);

      expect(localStorage.getItem("access_token")).toBe("at-reg");
      expect(localStorage.getItem("refresh_token")).toBe("rt-reg");
    });

    it("throws and does not set user when register API fails", async () => {
      mockPost.mockRejectedValueOnce(new Error("Email already taken"));

      await expect(
        useAuthStore.getState().register("testuser", "dup@example.com", "pass"),
      ).rejects.toThrow("Email already taken");

      const state = useAuthStore.getState();
      expect(state.isAuthenticated).toBe(false);
      expect(state.user).toBeNull();
    });
  });

  // -----------------------------------------------------------------------
  // logout
  // -----------------------------------------------------------------------

  describe("logout", () => {
    it("clears user, sets isAuthenticated=false, and removes tokens from localStorage", () => {
      // Set up authenticated state
      localStorage.setItem("access_token", "at-123");
      localStorage.setItem("refresh_token", "rt-456");
      useAuthStore.setState({ user: fakeUser, isAuthenticated: true });

      useAuthStore.getState().logout();

      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
      expect(localStorage.getItem("access_token")).toBeNull();
      expect(localStorage.getItem("refresh_token")).toBeNull();
    });
  });

  // -----------------------------------------------------------------------
  // fetchUser
  // -----------------------------------------------------------------------

  describe("fetchUser", () => {
    it("calls api.get /auth/me and updates user + isAuthenticated + isLoading", async () => {
      mockGet.mockResolvedValueOnce(makeApiReply(fakeUser));

      await useAuthStore.getState().fetchUser();

      expect(mockGet).toHaveBeenCalledWith("/auth/me");

      const state = useAuthStore.getState();
      expect(state.user).toEqual(fakeUser);
      expect(state.isAuthenticated).toBe(true);
      expect(state.isLoading).toBe(false);
    });
  });

  // -----------------------------------------------------------------------
  // hydrate
  // -----------------------------------------------------------------------

  describe("hydrate", () => {
    it("sets isLoading=false and isAuthenticated=false when no token in localStorage", async () => {
      useAuthStore.setState({ isLoading: true });

      await useAuthStore.getState().hydrate();

      const state = useAuthStore.getState();
      expect(state.isLoading).toBe(false);
      expect(state.isAuthenticated).toBe(false);
      expect(state.user).toBeNull();
      // Should not call /auth/me at all
      expect(mockGet).not.toHaveBeenCalled();
    });

    it("fetches user and sets state when token is present and valid", async () => {
      localStorage.setItem("access_token", "valid-at");
      mockGet.mockResolvedValueOnce(makeApiReply(fakeUser));

      await useAuthStore.getState().hydrate();

      const state = useAuthStore.getState();
      expect(state.user).toEqual(fakeUser);
      expect(state.isAuthenticated).toBe(true);
      expect(state.isLoading).toBe(false);
    });

    it("clears tokens when token is present but expired/invalid", async () => {
      localStorage.setItem("access_token", "expired-at");
      localStorage.setItem("refresh_token", "expired-rt");
      mockGet.mockRejectedValueOnce({
        response: { status: 401, data: { success: false } },
        message: "401 Unauthorized",
      });

      await useAuthStore.getState().hydrate();

      const state = useAuthStore.getState();
      expect(state.user).toBeNull();
      expect(state.isAuthenticated).toBe(false);
      expect(state.isLoading).toBe(false);
      // Tokens should be cleared
      expect(localStorage.getItem("access_token")).toBeNull();
      expect(localStorage.getItem("refresh_token")).toBeNull();
    });

    it("preserves tokens when /auth/me returns 429 (rate limited)", async () => {
      localStorage.setItem("access_token", "valid-at");
      localStorage.setItem("refresh_token", "valid-rt");
      mockGet.mockRejectedValueOnce({
        response: { status: 429, data: { success: false } },
        message: "Too Many Requests",
      });

      await useAuthStore.getState().hydrate();

      const state = useAuthStore.getState();
      expect(state.isLoading).toBe(false);
      // Tokens must NOT be cleared on 429
      expect(localStorage.getItem("access_token")).toBe("valid-at");
      expect(localStorage.getItem("refresh_token")).toBe("valid-rt");
    });
  });
});
