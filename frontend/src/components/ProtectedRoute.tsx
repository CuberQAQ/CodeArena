import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/stores/auth";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import type { ReactNode } from "react";

interface ProtectedRouteProps {
  children: ReactNode;
}

/**
 * Route guard that requires the user to be authenticated.
 * Unauthenticated users are redirected to the login page.
 */
export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isLoading = useAuthStore((s) => s.isLoading);
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingSpinner size="lg" text="Loading..." />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/" state={{ from: location }} replace />;
  }

  return <>{children}</>;
}
