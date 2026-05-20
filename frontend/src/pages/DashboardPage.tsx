import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Swords,
  Dumbbell,
  Trophy,
  TrendingUp,
  Coins,
  Zap,
  Star,
  ArrowRight,
  RefreshCw,
  Play,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { DashboardCharts } from "@/components/charts/DashboardCharts";
import { getRatingColor, getDifficultyLabel } from "@/utils";
import api from "@/services/api";
import type { ApiResponse, TransactionItem, ContestSessionInfo } from "@/types";

interface QuickAction {
  to: string;
  label: string;
  description: string;
  icon: React.ElementType;
  color: string;
}

const quickActions: QuickAction[] = [
  {
    to: "/challenge",
    label: "Random Challenge",
    description: "Match with an opponent",
    icon: Swords,
    color: "text-red-400",
  },
  {
    to: "/training",
    label: "Topic Training",
    description: "Practice by category",
    icon: Dumbbell,
    color: "text-green-400",
  },
  {
    to: "/contest",
    label: "Virtual Contest",
    description: "Timed competition",
    icon: Trophy,
    color: "text-yellow-400",
  },
  {
    to: "/leaderboard",
    label: "Leaderboard",
    description: "See top players",
    icon: TrendingUp,
    color: "text-blue-400",
  },
];

export default function DashboardPage() {
  const navigate = useNavigate();
  const { user, fetchUser } = useAuthStore();
  const [transactions, setTransactions] = useState<TransactionItem[]>([]);
  const [loadingTx, setLoadingTx] = useState(true);
  const [activeContest, setActiveContest] = useState<ContestSessionInfo | null>(null);

  useEffect(() => {
    fetchUser().catch(() => {});
    api
      .get<ApiResponse<{ items: TransactionItem[] }>>("/economy/transactions?limit=5")
      .then((res) => setTransactions(res.data.data.items ?? []))
      .catch(() => {})
      .finally(() => setLoadingTx(false));
    api
      .get<ApiResponse<ContestSessionInfo | null>>("/contest/active")
      .then((res) => setActiveContest((res.data.data as ContestSessionInfo | null) ?? null))
      .catch(() => {});
  }, [fetchUser]);

  if (!user) {
    return <LoadingSpinner text="Loading dashboard..." className="py-20" />;
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">
          Welcome back, {user.username}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Ready for your next challenge?
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        {/* Elo Card */}
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary/10">
              <TrendingUp className="size-5 text-primary" />
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">Elo Rating</p>
              <p
                className="text-2xl font-bold"
                style={{ color: getRatingColor(user.elo) }}
              >
                {user.elo} <span className="text-sm font-medium">/ {getDifficultyLabel(user.elo)}</span>
              </p>
            </div>
          </div>
        </div>

        {/* PP Card */}
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-yellow-500/10">
              <Star className="size-5 text-yellow-400" />
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">Performance Points</p>
              <p className="text-2xl font-bold text-yellow-400">{user.pp}</p>
            </div>
          </div>
        </div>

        {/* Tokens Card */}
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-amber-500/10">
              <Coins className="size-5 text-amber-400" />
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground">Tokens</p>
              <p className="text-2xl font-bold text-amber-400">{user.tokens}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Active Contest Banner */}
      {activeContest && (
        <div className="flex items-center justify-between rounded-xl border border-primary/30 bg-primary/5 p-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary/10">
              <Play className="size-5 text-primary" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                You have an active contest!
              </p>
              <p className="text-xs text-muted-foreground capitalize">
                {activeContest.tier} tier &middot; {activeContest.problems_solved}/{activeContest.total_problems} solved
              </p>
            </div>
          </div>
          <Button onClick={() => navigate(`/contest/${activeContest.id}`)}>
            Resume Contest
          </Button>
        </div>
      )}

      {/* CF Handle Status */}
      {!user.cf_handle && (
        <div className="flex items-center justify-between rounded-xl border border-border bg-card p-4">
          <div className="flex items-center gap-3">
            <Zap className="size-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium text-foreground">Link your Codeforces account</p>
              <p className="text-xs text-muted-foreground">
                Connect your CF handle to track submissions and get personalized problems
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => navigate("/profile/cf-bind")}>
            Bind Handle
          </Button>
        </div>
      )}

      {/* Quick Actions */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-foreground">Quick Actions</h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {quickActions.map((action) => (
            <Link
              key={action.to}
              to={action.to}
              className="group flex items-center gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-primary/30 hover:bg-card/80"
            >
              <div
                className={`flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted ${action.color}`}
              >
                <action.icon className="size-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-foreground">{action.label}</p>
                <p className="truncate text-xs text-muted-foreground">{action.description}</p>
              </div>
              <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </Link>
          ))}
        </div>
      </div>

      {/* Recent Activity */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">Recent Token Activity</h2>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => {
              setLoadingTx(true);
              api
                .get<ApiResponse<{ items: TransactionItem[] }>>("/economy/transactions?limit=5")
                .then((res) => setTransactions(res.data.data.items ?? []))
                .catch(() => {})
                .finally(() => setLoadingTx(false));
            }}
          >
            <RefreshCw className="size-3.5" />
          </Button>
        </div>
        <div className="rounded-xl border border-border bg-card">
          {loadingTx ? (
            <LoadingSpinner size="sm" className="py-8" />
          ) : transactions.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              No recent activity. Start a challenge or training session!
            </div>
          ) : (
            <div className="divide-y divide-border">
              {transactions.map((tx) => (
                <div key={tx.id} className="flex items-center justify-between px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground capitalize">
                      {tx.type.replace(/_/g, " ")}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Balance: {tx.balance_after}
                    </p>
                  </div>
                  <span
                    className={`text-sm font-semibold ${
                      tx.amount > 0 ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {tx.amount > 0 ? "+" : ""}
                    {tx.amount}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Analytics Charts */}
      <DashboardCharts />
    </div>
  );
}
