import { useEffect, useRef, useState } from "react";
import { BarChart3, TrendingUp, Medal } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { getRatingColor } from "@/utils";
import api from "@/services/api";
import type { ApiResponse, UserInfo } from "@/types";

type SortKey = "elo" | "pp";

export default function LeaderboardPage() {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortBy, setSortBy] = useState<SortKey>("elo");
  const hasFetchedRef = useRef(false);

  useEffect(() => {
    if (hasFetchedRef.current) return;
    hasFetchedRef.current = true;
    // Use the auth/me endpoint approach; for leaderboard we need a dedicated endpoint
    // Since no /leaderboard endpoint exists, we show a placeholder with empty data
    // that will be replaced when the backend endpoint is available
    api
      .get<ApiResponse<UserInfo[]>>("/auth/leaderboard")
      .then((res) => setUsers(res.data.data ?? []))
      .catch(() => {
        // No leaderboard endpoint yet - show empty state
        setUsers([]);
      })
      .finally(() => setLoading(false));
  }, []);

  const sorted = [...users].sort((a, b) =>
    sortBy === "elo" ? b.elo - a.elo : b.pp - a.pp,
  );

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Leaderboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Top players ranked by their competitive performance.
        </p>
      </div>

      {/* Sort tabs */}
      <div className="flex gap-2">
        <button
          onClick={() => setSortBy("elo")}
          className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            sortBy === "elo"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:text-foreground"
          }`}
        >
          <TrendingUp className="size-4" />
          By Elo
        </button>
        <button
          onClick={() => setSortBy("pp")}
          className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            sortBy === "pp"
              ? "bg-primary text-primary-foreground"
              : "bg-muted text-muted-foreground hover:text-foreground"
          }`}
        >
          <Medal className="size-4" />
          By PP
        </button>
      </div>

      {loading ? (
        <LoadingSpinner text="Loading leaderboard..." className="py-20" />
      ) : sorted.length === 0 ? (
        <div className="rounded-xl border border-border bg-card px-4 py-12 text-center">
          <BarChart3 className="mx-auto size-10 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">
            No leaderboard data available yet. Be the first to compete!
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card">
          {/* Header row */}
          <div className="grid grid-cols-[3rem_1fr_5rem_5rem_5rem] items-center border-b border-border px-5 py-2.5 text-xs font-medium text-muted-foreground">
            <span>#</span>
            <span>Player</span>
            <span className="text-right">Elo</span>
            <span className="text-right">PP</span>
            <span className="text-right">Tokens</span>
          </div>
          <div className="divide-y divide-border">
            {sorted.map((user, index) => (
              <div
                key={user.id}
                className="grid grid-cols-[3rem_1fr_5rem_5rem_5rem] items-center px-5 py-3 transition-colors hover:bg-muted/50"
              >
                <span className="text-sm font-medium text-muted-foreground">
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-foreground">{user.username}</p>
                  {user.cf_handle && (
                    <p className="truncate text-xs text-muted-foreground">
                      CF: {user.cf_handle}
                    </p>
                  )}
                </div>
                <span
                  className="text-right text-sm font-bold"
                  style={{ color: getRatingColor(user.elo) }}
                >
                  {user.elo}
                </span>
                <span className="text-right text-sm font-semibold text-yellow-400">
                  {user.pp}
                </span>
                <span className="text-right text-sm text-muted-foreground">{user.tokens}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
