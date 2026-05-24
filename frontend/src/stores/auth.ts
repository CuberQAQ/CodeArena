import { create } from "zustand";

import api from "@/services/api";
import type { ApiResponse, RegisterResponse, UserInfo } from "@/types";

// ---------------------------------------------------------------------------
// Store state shape
// ---------------------------------------------------------------------------

interface AuthState {
  user: UserInfo | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  /** ISO 8601 UTC timestamp of when the user logged in (for online-time timer). */
  loginTime: string | null;

  // Actions
  login: (email: string, password: string) => Promise<void>;
  register: (username: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  fetchUser: () => Promise<void>;
  hydrate: () => Promise<void>;
}

// ---------------------------------------------------------------------------
// Helper – persist / clear tokens
// ---------------------------------------------------------------------------

function storeTokens(access_token: string, refresh_token: string, loginTime?: string) {
  localStorage.setItem("access_token", access_token);
  localStorage.setItem("refresh_token", refresh_token);
  if (loginTime) {
    localStorage.setItem("login_time", loginTime);
  }
}

function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("login_time");
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true, // starts true so the initial hydrate can show a loading state
  loginTime: null,

  login: async (email, password) => {
    const res = await api.post<ApiResponse<TokenPair & { login_time: string }>>("/auth/login", { email, password });
    const { access_token, refresh_token, login_time } = res.data.data;
    storeTokens(access_token, refresh_token, login_time);
    set({ isAuthenticated: true, loginTime: login_time });
    // Fetch full user profile after login
    const meRes = await api.get<ApiResponse<UserInfo>>("/auth/me");
    set({ user: meRes.data.data });
  },

  register: async (username, email, password) => {
    const res = await api.post<ApiResponse<RegisterResponse>>("/auth/register", {
      username,
      email,
      password,
    });
    const { access_token, refresh_token } = res.data.data.tokens;
    const loginTime = new Date().toISOString();
    storeTokens(access_token, refresh_token, loginTime);
    set({ user: res.data.data.user, isAuthenticated: true, loginTime });
  },

  logout: () => {
    clearTokens();
    set({ user: null, isAuthenticated: false, loginTime: null });
  },

  fetchUser: async () => {
    const res = await api.get<ApiResponse<UserInfo>>("/auth/me");
    set({ user: res.data.data, isAuthenticated: true, isLoading: false });
  },

  hydrate: async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      set({ isLoading: false, isAuthenticated: false, user: null, loginTime: null });
      return;
    }
    try {
      const res = await api.get<ApiResponse<UserInfo>>("/auth/me");
      // Restore loginTime from localStorage (survives page refresh)
      const storedLoginTime = localStorage.getItem("login_time");
      set({ user: res.data.data, isAuthenticated: true, isLoading: false, loginTime: storedLoginTime });
    } catch (err: unknown) {
      // Only clear tokens on 401 (auth failure). 429/5xx are transient —
      // keep existing state so the user is not logged out due to rate limiting.
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 401) {
        clearTokens();
        set({ user: null, isAuthenticated: false, isLoading: false, loginTime: null });
      } else {
        // Transient error (429, 500, network failure, etc.): keep tokens,
        // mark loading done but leave user null so the UI can retry later.
        set({ isLoading: false });
      }
    }
  },
}));

// Re-export TokenPair for convenience in components
import type { TokenPair } from "@/types";
export type { TokenPair };
