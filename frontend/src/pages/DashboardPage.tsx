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
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { DashboardCharts } from "@/components/charts/DashboardCharts";
import { getRatingColor, getDifficultyLabelKey } from "@/utils";
import api from "@/services/api";
import type { ApiResponse, TransactionItem, ContestSessionInfo, ActiveChallengeInfo } from "@/types";

interface QuickAction {
  to: string;
  labelKey: string;
  descKey: string;
  icon: React.ElementType;
  color: string;
}

const quickActions: QuickAction[] = [
  {
    to: "/challenge",
    labelKey: "dashboard:randomChallenge",
    descKey: "dashboard:matchWithOpponent",
    icon: Swords,
    color: "text-red-400",
  },
  {
    to: "/training",
    labelKey: "dashboard:topicTraining",
    descKey: "dashboard:practiceByCategory",
    icon: Dumbbell,
    color: "text-green-400",
  },
  {
    to: "/contest",
    labelKey: "dashboard:virtualContest",
    descKey: "dashboard:timedCompetition",
    icon: Trophy,
    color: "text-yellow-400",
  },
  {
    to: "/leaderboard",
    labelKey: "dashboard:leaderboard",
    descKey: "dashboard:seeTopPlayers",
    icon: TrendingUp,
    color: "text-blue-400",
  },
];

export default function DashboardPage() {
  const navigate = useNavigate();
  const { user } = useAuthStore();
  const { t } = useTranslation(["dashboard", "common"]);
  const [transactions, setTransactions] = useState<TransactionItem[]>([]);
  const [loadingTx, setLoadingTx] = useState(true);
  const [activeContest, setActiveContest] = useState<ContestSessionInfo | null>(null);
  const [activeChallenge, setActiveChallenge] = useState<ActiveChallengeInfo | null>(null);

  useEffect(() => {
    // Fetch all transactions once (limit=100) — DashboardCharts reuses this data
    // via the transactions prop, eliminating a duplicate request.
    api
      .get<ApiResponse<{ items: TransactionItem[]; total: number }>>("/economy/transactions?limit=100")
      .then((res) => setTransactions(res.data.data.items ?? []))
      .catch(() => {})
      .finally(() => setLoadingTx(false));
    api
      .get<ApiResponse<ContestSessionInfo | null>>("/contest/active")
      .then((res) => setActiveContest((res.data.data as ContestSessionInfo | null) ?? null))
      .catch(() => {});
    api
      .get<ApiResponse<ActiveChallengeInfo | null>>("/challenge/active")
      .then((res) => setActiveChallenge((res.data.data as ActiveChallengeInfo | null) ?? null))
      .catch(() => {});
  }, []);

  if (!user) {
    return <LoadingSpinner text={t("dashboard:loadingDashboard")} className="py-20" />;
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">
          {t("dashboard:welcomeBack", { username: user.username })}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {t("dashboard:readyForChallenge")}
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
              <p className="text-xs font-medium text-muted-foreground">{t("dashboard:eloRating")}</p>
              <p
                className="text-2xl font-bold"
                style={{ color: getRatingColor(user.elo) }}
              >
                {user.elo} <span className="text-sm font-medium">/ {t(getDifficultyLabelKey(user.elo))}</span>
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
              <p className="text-xs font-medium text-muted-foreground">{t("dashboard:performancePoints")}</p>
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
              <p className="text-xs font-medium text-muted-foreground">{t("common:tokens")}</p>
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
                {t("dashboard:activeContest")}
              </p>
              <p className="text-xs text-muted-foreground capitalize">
                {t("dashboard:activeContestDetail", {
                  tier: activeContest.tier,
                  solved: activeContest.problems_solved,
                  total: activeContest.total_problems,
                })}
              </p>
            </div>
          </div>
          <Button onClick={() => navigate(`/contest/${activeContest.id}`)}>
            {t("dashboard:resumeContest")}
          </Button>
        </div>
      )}

      {/* Active Challenge Banner — only show for truly active sessions */}
      {activeChallenge && activeChallenge.status === "active" && (
        <div className="flex items-center justify-between rounded-xl border border-red-500/30 bg-red-500/5 p-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-red-500/10">
              <Swords className="size-5 text-red-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                {t("dashboard:activeChallenge")}
              </p>
              <p className="text-xs text-muted-foreground">
                {t("dashboard:activeChallengeDetail", {
                  opponent: activeChallenge.opponent_username ?? "???",
                  rating: activeChallenge.problem_rating,
                })}
              </p>
            </div>
          </div>
          <Button onClick={() => navigate(`/challenge/${activeChallenge.id}`)}>
            {t("dashboard:resumeChallenge")}
          </Button>
        </div>
      )}

      {/* CF Handle Status */}
      {!user.cf_handle && (
        <div className="flex items-center justify-between rounded-xl border border-border bg-card p-4">
          <div className="flex items-center gap-3">
            <Zap className="size-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium text-foreground">{t("dashboard:linkCF")}</p>
              <p className="text-xs text-muted-foreground">
                {t("dashboard:linkCFDesc")}
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => navigate("/profile/cf-bind")}>
            {t("dashboard:bindHandle")}
          </Button>
        </div>
      )}

      {/* Quick Actions */}
      <div>
        <h2 className="mb-3 text-lg font-semibold text-foreground">{t("dashboard:quickActions")}</h2>
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
                <p className="text-sm font-medium text-foreground">{t(action.labelKey)}</p>
                <p className="truncate text-xs text-muted-foreground">{t(action.descKey)}</p>
              </div>
              <ArrowRight className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
            </Link>
          ))}
        </div>
      </div>

      {/* Recent Activity */}
      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">{t("dashboard:recentTokenActivity")}</h2>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => {
              setLoadingTx(true);
              api
                .get<ApiResponse<{ items: TransactionItem[] }>>("/economy/transactions?limit=100")
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
              {t("dashboard:noRecentActivity")}
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
                      {t("common:balance")}: {tx.balance_after}
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
      <DashboardCharts transactions={transactions} />
    </div>
  );
}
