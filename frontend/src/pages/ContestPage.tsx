import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Trophy, Loader2, Target, ShieldCheck, Crown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { extractApiError } from "@/utils";
import api from "@/services/api";
import type { ApiResponse, TierInfo, ContestHistoryItem } from "@/types";

const TIER_ICONS: Record<string, React.ElementType> = {
  beginner: ShieldCheck,
  advanced: Target,
  master: Crown,
};

const TIER_COLORS: Record<string, string> = {
  beginner: "text-green-400",
  advanced: "text-blue-400",
  master: "text-yellow-400",
};

const TIER_BG: Record<string, string> = {
  beginner: "bg-green-500/10",
  advanced: "bg-blue-500/10",
  master: "bg-yellow-500/10",
};

export default function ContestPage() {
  const navigate = useNavigate();
  const [tiers, setTiers] = useState<TierInfo[]>([]);
  const [history, setHistory] = useState<ContestHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.get<ApiResponse<TierInfo[]>>("/contest/tiers").catch(() => ({ data: { data: [] } })),
      api
        .get<ApiResponse<ContestHistoryItem[]>>("/contest/history?limit=5")
        .catch(() => ({ data: { data: [] } })),
    ]).then(([tiersRes, historyRes]) => {
      setTiers((tiersRes.data as ApiResponse<TierInfo[]>).data ?? []);
      setHistory((historyRes.data as ApiResponse<ContestHistoryItem[]>).data ?? []);
      setLoading(false);
    });
  }, []);

  const handleStart = async (tier: string) => {
    setError("");
    setStarting(tier);
    try {
      const res = await api.post<ApiResponse<{ id: string }>>("/contest/start", { tier });
      const contestId = res.data.data.id ?? (res.data.data as Record<string, string>).id;
      navigate(`/contest/${contestId}`);
    } catch (err) {
      setError(extractApiError(err, "Failed to start contest"));
      setStarting(null);
    }
  };

  if (loading) {
    return <LoadingSpinner text="Loading contests..." className="py-20" />;
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Virtual Contest</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose your tier and compete against the clock. Solve as many problems as you can!
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Tier selection cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        {tiers.length === 0 ? (
          <div className="col-span-full rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
            No contest tiers available.
          </div>
        ) : (
          tiers.map((tier) => {
            const Icon = TIER_ICONS[tier.tier] ?? Trophy;
            const color = TIER_COLORS[tier.tier] ?? "text-primary";
            const bg = TIER_BG[tier.tier] ?? "bg-primary/10";
            const isStarting = starting === tier.tier;

            return (
              <div
                key={tier.tier}
                className="rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30"
              >
                <div className="flex items-center gap-3">
                  <div className={`flex size-12 items-center justify-center rounded-xl ${bg}`}>
                    <Icon className={`size-6 ${color}`} />
                  </div>
                  <div>
                    <h3 className="text-lg font-bold text-foreground">{tier.name}</h3>
                    <p className="text-xs text-muted-foreground capitalize">{tier.tier}</p>
                  </div>
                </div>

                <div className="mt-4 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Duration</span>
                    <span className="text-foreground">{tier.duration_minutes} min</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Problems</span>
                    <span className="text-foreground">{tier.problem_count}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Rating Range</span>
                    <span className="text-foreground">
                      {tier.rating_range[0]} - {tier.rating_range[1]}
                    </span>
                  </div>
                  {tier.min_elo != null && (
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Min Elo</span>
                      <span className="text-foreground">{tier.min_elo}</span>
                    </div>
                  )}
                </div>

                <Button
                  className="mt-4 w-full"
                  onClick={() => handleStart(tier.tier)}
                  disabled={isStarting || !tier.eligible}
                >
                  {isStarting ? (
                    <>
                      <Loader2 className="mr-2 size-4 animate-spin" />
                      Starting...
                    </>
                  ) : !tier.eligible ? (
                    "Elo Required"
                  ) : (
                    "Start Contest"
                  )}
                </Button>
              </div>
            );
          })
        )}
      </div>

      {/* Recent contest history */}
      {history.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold text-foreground">Recent Contests</h2>
          <div className="rounded-xl border border-border bg-card">
            <div className="divide-y divide-border">
              {history.map((item) => (
                <div
                  key={item.id}
                  className="flex cursor-pointer items-center justify-between px-5 py-3 transition-colors hover:bg-muted/50"
                  onClick={() => navigate(`/contest/${item.id}`)}
                >
                  <div>
                    <p className="text-sm font-medium capitalize text-foreground">{item.tier}</p>
                    <p className="text-xs text-muted-foreground">
                      {item.started_at
                        ? new Date(item.started_at).toLocaleDateString("en-US", {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "-"}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-medium text-foreground">
                      {item.problems_solved}/{item.total_problems}
                    </p>
                    {item.elo_change != null && (
                      <p
                        className={`text-xs font-semibold ${
                          item.elo_change > 0
                            ? "text-green-400"
                            : item.elo_change < 0
                              ? "text-red-400"
                              : "text-muted-foreground"
                        }`}
                      >
                        {item.elo_change > 0 ? "+" : ""}
                        {item.elo_change} Elo
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
