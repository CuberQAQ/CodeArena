import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const api = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
  timeout: 15_000,
});

// ---------------------------------------------------------------------------
// Request interceptor – attach JWT access token
// ---------------------------------------------------------------------------

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// ---------------------------------------------------------------------------
// Response interceptor – handle 401 & unwrap errors
// ---------------------------------------------------------------------------

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear stale credentials and redirect to login
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
      // Only redirect if we are in a browser context and not already on login/register
      if (
        typeof window !== "undefined" &&
        !window.location.pathname.startsWith("/login") &&
        !window.location.pathname.startsWith("/register")
      ) {
        window.location.href = "/";
      }
    }
    return Promise.reject(error);
  },
);

export default api;
