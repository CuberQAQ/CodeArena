import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Settings, Users, Activity, Database, BarChart3 } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import api from "@/services/api";
import type { ApiResponse } from "@/types";

interface SystemStatus {
  status: string;
  uptime?: number;
  version?: string;
}

export default function AdminOverviewPage() {
  const [health, setHealth] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<ApiResponse<SystemStatus>>("/health")
      .then((res) => setHealth(res.data.data))
      .catch(() => setError("Failed to fetch system status"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Admin Overview</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          System administration and monitoring dashboard.
        </p>
      </div>

      {loading ? (
        <LoadingSpinner text="Loading system info..." className="py-20" />
      ) : (
        <>
          {error && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {/* System Status */}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-lg bg-green-500/10">
                  <Activity className="size-5 text-green-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">System Status</p>
                  <p className="text-sm font-semibold text-green-400">
                    {health?.status ?? "Unknown"}
                  </p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-lg bg-blue-500/10">
                  <Users className="size-5 text-blue-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Total Users</p>
                  <p className="text-sm font-semibold text-foreground">--</p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-lg bg-yellow-500/10">
                  <BarChart3 className="size-5 text-yellow-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Active Sessions</p>
                  <p className="text-sm font-semibold text-foreground">--</p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-border bg-card p-5">
              <div className="flex items-center gap-3">
                <div className="flex size-10 items-center justify-center rounded-lg bg-purple-500/10">
                  <Database className="size-5 text-purple-400" />
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Database</p>
                  <p className="text-sm font-semibold text-green-400">Connected</p>
                </div>
              </div>
            </div>
          </div>

          {/* Quick Links */}
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="text-sm font-semibold text-foreground">Quick Actions</h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Link
                to="/admin/config"
                className="flex items-center gap-3 rounded-lg border border-border p-3 transition-colors hover:bg-muted"
              >
                <Settings className="size-5 text-muted-foreground" />
                <div>
                  <p className="text-sm font-medium text-foreground">Configuration</p>
                  <p className="text-xs text-muted-foreground">Manage system settings</p>
                </div>
              </Link>
            </div>
          </div>

          {/* System Info */}
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="text-sm font-semibold text-foreground">System Information</h2>
            <div className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between border-b border-border pb-2">
                <span className="text-muted-foreground">API Version</span>
                <span className="text-foreground">v1</span>
              </div>
              <div className="flex justify-between border-b border-border pb-2">
                <span className="text-muted-foreground">Environment</span>
                <span className="text-foreground">Production</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Status</span>
                <span className="text-green-400">
                  {health?.status === "healthy" ? "All systems operational" : "Checking..."}
                </span>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
