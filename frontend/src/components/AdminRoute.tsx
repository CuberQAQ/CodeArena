import { Navigate, useLocation } from "react-router-dom";
import { useAuthStore } from "@/stores/auth";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import type { ReactNode } from "react";

interface AdminRouteProps {
  children: ReactNode;
}

/**
 * Route guard that requires the user to be authenticated AND an admin.
 * Non-admin users are redirected to the dashboard.
 */
export function AdminRoute({ children }: AdminRouteProps) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
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

  if (!user?.is_admin) {
    return <Navigate to="/dashboard" replace />;
  }

  return <>{children}</>;
}
