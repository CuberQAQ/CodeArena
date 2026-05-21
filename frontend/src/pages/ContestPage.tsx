import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Trophy, Loader2, Target, ShieldCheck, Crown, Play, Zap, Eye } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { PageHeader } from "@/components/PageHeader";
import { ErrorMessage } from "@/components/ErrorMessage";
import { extractApiError } from "@/utils";
import api from "@/services/api";
import type { ApiResponse, TierInfo, ContestHistoryItem, ContestSessionInfo } from "@/types";

const TIER_ICONS: Record<string, React.ElementType> = {
  beginner: ShieldCheck,
  pupil: Eye,
  advanced: Target,
  master: Crown,
  blitz: Zap,
};

const TIER_COLORS: Record<string, string> = {
  beginner: "text-green-400",
  pupil: "text-cyan-400",
  advanced: "text-blue-400",
  master: "text-yellow-400",
  blitz: "text-orange-400",
};

const TIER_BG: Record<string, string> = {
  beginner: "bg-green-500/10",
  pupil: "bg-cyan-500/10",
  advanced: "bg-blue-500/10",
  master: "bg-yellow-500/10",
  blitz: "bg-orange-500/10",
};

const TIER_BORDER: Record<string, string> = {
  blitz: "border-orange-500/40 hover:border-orange-400/60",
};

export default function ContestPage() {
  const navigate = useNavigate();
  const { t } = useTranslation("contest");
  const [tiers, setTiers] = useState<TierInfo[]>([]);
  const [history, setHistory] = useState<ContestHistoryItem[]>([]);
  const [activeContest, setActiveContest] = useState<ContestSessionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api.get<ApiResponse<TierInfo[]>>("/contest/tiers").catch(() => ({ data: { data: [] } })),
      api
        .get<ApiResponse<ContestHistoryItem[]>>("/contest/history?limit=5")
        .catch(() => ({ data: { data: [] } })),
      api
        .get<ApiResponse<ContestSessionInfo | null>>("/contest/active")
        .then((res) => (res.data.data as ContestSessionInfo | null) ?? null)
        .catch(() => null),
    ]).then(([tiersRes, historyRes, activeRes]) => {
      setTiers((tiersRes.data as ApiResponse<TierInfo[]>).data ?? []);
      setHistory((historyRes.data as ApiResponse<ContestHistoryItem[]>).data ?? []);
      setActiveContest(activeRes);
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
      setError(extractApiError(err, t("failedStart")));
      setStarting(null);
    }
  };

  if (loading) {
    return <LoadingSpinner text={t("loadingContests")} className="py-20" />;
  }

  const hasActiveContest = activeContest !== null;

  const formatRatingRange = (tier: TierInfo) => {
    if (tier.rating_range == null) {
      return t("allRatings");
    }
    return `${tier.rating_range[0]} - ${tier.rating_range[1]}`;
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader title={t("virtualContest")} description={t("virtualContestDesc")} />

      {error && (
        <ErrorMessage message={error} />
      )}

      {/* Active contest resume banner */}
      {hasActiveContest && (
        <div className="flex items-center justify-between rounded-xl border border-primary/30 bg-primary/5 p-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary/10">
              <Play className="size-5 text-primary" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">
                {t("activeContestRunning")}
              </p>
              <p className="text-xs text-muted-foreground capitalize">
                {t("activeContestDetail", {
                  tier: activeContest.tier,
                  solved: activeContest.problems_solved,
                  total: activeContest.total_problems,
                })}
              </p>
            </div>
          </div>
          <Button onClick={() => navigate(`/contest/${activeContest.id}`)}>
            {t("resumeContest")}
          </Button>
        </div>
      )}

      {/* Tier selection cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {tiers.length === 0 ? (
          <div className="col-span-full rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
            {t("noTiers")}
          </div>
        ) : (
          tiers.map((tier) => {
            const Icon = TIER_ICONS[tier.tier] ?? Trophy;
            const color = TIER_COLORS[tier.tier] ?? "text-primary";
            const bg = TIER_BG[tier.tier] ?? "bg-primary/10";
            const customBorder = TIER_BORDER[tier.tier];
            const isStarting = starting === tier.tier;
            const isBlitz = tier.tier === "blitz";

            return (
              <div
                key={tier.tier}
                className={`flex flex-col rounded-xl border bg-card p-5 transition-colors hover:border-primary/30 ${
                  customBorder ?? "border-border"
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`flex size-12 items-center justify-center rounded-xl ${bg}`}>
                    <Icon className={`size-6 ${color}`} />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="whitespace-nowrap text-lg font-bold text-foreground">
                        {tier.name}
                      </h3>
                      {tier.div != null && (
                        <span className="rounded-md bg-muted px-1.5 py-0.5 text-xs font-semibold text-muted-foreground">
                          {t("divLabel", { div: tier.div })}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <p className="text-xs text-muted-foreground capitalize">{tier.tier}</p>
                      {tier.is_rated ? (
                        <span className="rounded-sm bg-green-500/10 px-1.5 py-0.5 text-[10px] font-medium text-green-400">
                          {t("rated")}
                        </span>
                      ) : (
                        <span className="rounded-sm bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                          {t("unrated")}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {isBlitz && (
                  <p className="mt-2 text-xs italic text-orange-400/80">
                    {t("blitzDescription")}
                  </p>
                )}

                <div className="mt-4 space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t("duration")}</span>
                    <span className="text-foreground">{tier.duration_minutes} min</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t("problemsCount")}</span>
                    <span className="text-foreground">{tier.problem_count}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t("ratingRange")}</span>
                    <span className="text-foreground">{formatRatingRange(tier)}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">{t("minElo")}</span>
                    <span className="text-foreground">
                      {tier.min_elo != null ? tier.min_elo : t("noMinElo")}
                    </span>
                  </div>
                </div>

                <div className="mt-auto border-t border-border/50 pt-4" />

                <Button
                  className="w-full"
                  onClick={() => handleStart(tier.tier)}
                  disabled={isStarting || !tier.eligible || hasActiveContest}
                >
                  {isStarting ? (
                    <>
                      <Loader2 className="mr-2 size-4 animate-spin" />
                      {t("starting")}
                    </>
                  ) : hasActiveContest ? (
                    t("activeContestBtn")
                  ) : !tier.eligible ? (
                    t("eloRequired")
                  ) : (
                    t("startContest")
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
          <h2 className="mb-3 text-lg font-semibold text-foreground">{t("recentContests")}</h2>
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
                        ? new Date(item.started_at).toLocaleDateString(
                            localStorage.getItem("i18nextLng")?.startsWith("zh") ? "zh-CN" : "en-US",
                            {
                              month: "short",
                              day: "numeric",
                              hour: "2-digit",
                              minute: "2-digit",
                            },
                          )
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
                        {item.elo_change} {t("elo")}
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
