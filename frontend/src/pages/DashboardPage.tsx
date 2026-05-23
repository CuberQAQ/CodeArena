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
import { getRatingColor, getDifficultyLabelKey, RATING_TIERS } from "@/utils";
import { MedalBadge } from "@/components/medal";
import { Avatar } from "@/components/Avatar";
import { CheckInCard } from "@/components/CheckInCard";
import api from "@/services/api";
import { freePlayGetActive } from "@/services/freePlayApi";
import type { ApiResponse, TransactionItem, ContestSessionInfo, ActiveChallengeInfo, UserSettingsData, MedalInfo, FreePlayStartResponse, PPRankData } from "@/types";

/** Medal thresholds (low→high), mirrors backend MedalService. */
const FLAT_MEDAL_MAP_ASC: [number, string, string][] = [
  [1200, "provincial", "bronze"],
  [1400, "provincial", "silver"],
  [1600, "provincial", "gold"],
  [1800, "regional", "bronze"],
  [2000, "regional", "silver"],
  [2200, "regional", "gold"],
  [2400, "world_finals", "bronze"],
  [2600, "world_finals", "silver"],
  [2800, "world_finals", "gold"],
];

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
    to: "/ranking",
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
  const [activeFreePlay, setActiveFreePlay] = useState<FreePlayStartResponse | null>(null);
  const [displayMode, setDisplayMode] = useState<"medal" | "cf_tier">("medal");
  const [overallMedal, setOverallMedal] = useState<MedalInfo | null>(null);
  const [ppRankData, setPpRankData] = useState<PPRankData | null>(null);

  useEffect(() => {
    // Fetch all transactions once (limit=100) — DashboardCharts reuses this data
    // via the transactions prop, eliminating a duplicate request.
    api
      .get<ApiResponse<UserSettingsData>>("/auth/settings")
      .then((res) => setDisplayMode(res.data.data.display_mode))
      .catch(() => {});
    api
      .get<ApiResponse<{ elo: number; medal: MedalInfo }>>("/medal/overall")
      .then((res) => setOverallMedal(res.data.data.medal))
      .catch(() => {});
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
    freePlayGetActive()
      .then((data) => setActiveFreePlay(data))
      .catch(() => {});
    api
      .get<ApiResponse<PPRankData>>("/auth/pp-rank")
      .then((res) => setPpRankData(res.data.data))
      .catch(() => {});
  }, []);

  if (!user) {
    return <LoadingSpinner text={t("dashboard:loadingDashboard")} className="py-20" />;
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Avatar userId={user.id} size={44} />
        <div>
          <h1 className="text-2xl font-bold text-foreground">
            {t("dashboard:welcomeBack", { username: user.username })}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {t("dashboard:readyForChallenge")}
          </p>
        </div>
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
              {displayMode === "medal" && overallMedal ? (
                <div className="flex items-center gap-2">
                  <span
                    className="text-2xl font-bold"
                    style={{ color: getRatingColor(user.elo) }}
                  >
                    {user.elo}
                  </span>
                  <MedalBadge level={overallMedal.level} type={overallMedal.type} size="sm" />
                </div>
              ) : (
                <p
                  className="text-2xl font-bold"
                  style={{ color: getRatingColor(user.elo) }}
                >
                  {user.elo} <span className="text-sm font-medium">/ {t(getDifficultyLabelKey(user.elo))}</span>
                </p>
              )}
              {/* Elo Progress Bar */}
              {(() => {
                const elo = user.elo;
                let currentThreshold = 0;
                let nextThreshold: number | null = null;
                let nextNameKey = "";

                if (displayMode === "medal") {
                  // Find current and next medal thresholds (ascending order)
                  for (let i = 0; i < FLAT_MEDAL_MAP_ASC.length; i++) {
                    if (elo < FLAT_MEDAL_MAP_ASC[i][0]) {
                      currentThreshold = i > 0 ? FLAT_MEDAL_MAP_ASC[i - 1][0] : 0;
                      nextThreshold = FLAT_MEDAL_MAP_ASC[i][0];
                      const level = FLAT_MEDAL_MAP_ASC[i][1].replace(/_([a-z])/g, (_, c) => c.toUpperCase());
                      const medalType = FLAT_MEDAL_MAP_ASC[i][2];
                      nextNameKey = `${t(`medal:levels.${level}`)} ${t(`medal:types.${medalType}`)}`;
                      break;
                    }
                  }
                  if (nextThreshold === null) {
                    // Already at highest medal (world_finals gold), no progress bar
                    return null;
                  }
                } else {
                  // CF tier mode
                  for (let i = 0; i < RATING_TIERS.length; i++) {
                    if (elo < RATING_TIERS[i].min) {
                      currentThreshold = i > 0 ? Math.max(0, RATING_TIERS[i - 1].min) : 0;
                      nextThreshold = RATING_TIERS[i].min;
                      nextNameKey = getDifficultyLabelKey(RATING_TIERS[i].min);
                      break;
                    }
                  }
                  if (nextThreshold === null) {
                    // Already at Legendary Grandmaster, no progress bar
                    return null;
                  }
                }

                const range = nextThreshold! - currentThreshold;
                const progress = range > 0
                  ? Math.max(0, Math.min(1, (elo - currentThreshold) / range))
                  : 0;
                const eloNeeded = nextThreshold! - elo;

                return (
                  <div className="mt-3">
                    <div className="h-1.5 w-full rounded-full bg-muted">
                      <div
                        className="h-1.5 rounded-full bg-primary transition-all"
                        style={{ width: `${progress * 100}%` }}
                      />
                    </div>
                    <p className="mt-1.5 text-xs text-muted-foreground">
                      {t("dashboard:eloProgress", {
                        name: displayMode === "medal" ? nextNameKey : t(nextNameKey),
                        needed: eloNeeded,
                      })}
                    </p>
                  </div>
                );
              })()}
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
              {ppRankData && ppRankData.rank != null && (
                <p className="text-sm font-medium text-white">
                  #{ppRankData.rank}
                </p>
              )}
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

      {/* Daily Check-in */}
      <CheckInCard />

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

      {/* Active Free Play Banner */}
      {activeFreePlay && (
        <div className="flex items-center justify-between rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-emerald-500/10">
              <Dumbbell className="size-5 text-emerald-400" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                {t("dashboard:activeFreePlay")}
              </p>
              <p className="text-xs text-muted-foreground">
                {activeFreePlay.problem.rating
                  ? `${activeFreePlay.problem.contest_id}${activeFreePlay.problem.index} (${activeFreePlay.problem.rating})`
                  : `${activeFreePlay.problem.contest_id}${activeFreePlay.problem.index}`}
              </p>
            </div>
          </div>
          <Button onClick={() => navigate(`/free-play/session/${activeFreePlay.session_id}`)}>
            {t("dashboard:resumeFreePlay")}
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
