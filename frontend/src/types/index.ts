/** Shared TypeScript types used across the frontend application. */

// ---------------------------------------------------------------------------
// Auth / User
// ---------------------------------------------------------------------------

export interface UserInfo {
  id: string;
  username: string;
  email: string;
  cf_handle: string | null;
  cf_handle_verified: boolean;
  elo: number;
  pp: number;
  tokens: number;
  is_active: boolean;
  is_admin: boolean;
  created_at: string | null;
  updated_at: string | null;
  last_login_at: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface RegisterResponse {
  user: UserInfo;
  tokens: TokenPair;
}

// ---------------------------------------------------------------------------
// API response wrapper (matches backend's unified response format)
// ---------------------------------------------------------------------------

export interface ApiResponse<T = unknown> {
  success: boolean;
  data: T;
  message: string;
}

export interface ApiErrorResponse {
  success: false;
  error: {
    code: string;
    message: string;
  };
  detail?: string;
}
