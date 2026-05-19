import { Outlet } from "react-router-dom";

/**
 * Centered card layout for login / register pages.
 */
export function AuthLayout() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Code Arena</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Competitive Programming Gamification Platform
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
