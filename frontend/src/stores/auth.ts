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

function storeTokens(access_token: string, refresh_token: string) {
  localStorage.setItem("access_token", access_token);
  localStorage.setItem("refresh_token", refresh_token);
}

function clearTokens() {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: true, // starts true so the initial hydrate can show a loading state

  login: async (email, password) => {
    const res = await api.post<ApiResponse<TokenPair>>("/auth/login", { email, password });
    const { access_token, refresh_token } = res.data.data;
    storeTokens(access_token, refresh_token);
    set({ isAuthenticated: true });
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
    storeTokens(access_token, refresh_token);
    set({ user: res.data.data.user, isAuthenticated: true });
  },

  logout: () => {
    clearTokens();
    set({ user: null, isAuthenticated: false });
  },

  fetchUser: async () => {
    const res = await api.get<ApiResponse<UserInfo>>("/auth/me");
    set({ user: res.data.data, isAuthenticated: true, isLoading: false });
  },

  hydrate: async () => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      set({ isLoading: false, isAuthenticated: false, user: null });
      return;
    }
    try {
      const res = await api.get<ApiResponse<UserInfo>>("/auth/me");
      set({ user: res.data.data, isAuthenticated: true, isLoading: false });
    } catch {
      clearTokens();
      set({ user: null, isAuthenticated: false, isLoading: false });
    }
  },
}));

// Re-export TokenPair for convenience in components
import type { TokenPair } from "@/types";
export type { TokenPair };
