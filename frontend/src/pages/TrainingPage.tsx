import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Dumbbell, BookOpen, Sparkles, Target } from "lucide-react";
import { useTranslation } from "react-i18next";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import { MedalBadge } from "@/components/medal/MedalBadge";
import { TrainingRadarChart } from "@/components/charts/TrainingRadarChart";
import api from "@/services/api";
import { getMElo, getRecommendedTopics } from "@/services/trainingApi";
import { buildRadarDataFromMElo } from "@/utils/radar";
import type { ApiResponse, TopicInfo, RecommendedTopic, RadarDataPoint } from "@/types";

// ---------------------------------------------------------------------------
// Medal threshold label helper
// ---------------------------------------------------------------------------

function getMedalLabelForThreshold(threshold: number): { level: string; type: string } | null {
  const map: [number, string, string][] = [
    [2800, "worldFinals", "gold"],
    [2600, "ecFinal", "gold"],
    [2200, "regional", "gold"],
    [1600, "provincial", "gold"],
    [1400, "provincial", "silver"],
    [1200, "provincial", "bronze"],
  ];
  for (const [t, level, type] of map) {
    if (threshold === t) return { level, type };
  }
  return null;
}

// ---------------------------------------------------------------------------
// Elo Progress Bar (FR-26.2)
// ---------------------------------------------------------------------------

interface EloProgressBarProps {
  melo: number | null;
  currentThreshold: number | null;
  nextThreshold: number | null;
  t: (key: string, params?: Record<string, unknown>) => string;
}

function EloProgressBar({ melo, currentThreshold, nextThreshold, t }: EloProgressBarProps) {
  // No data: nothing to show
  if (melo === null || melo === undefined) {
    return null;
  }

  const meloVal = Math.round(melo);

  // At highest tier (nextThreshold is null, but currentThreshold exists)
  if (nextThreshold === null && currentThreshold !== null) {
    return (
      <div className="mt-2 space-y-1">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-gradient-to-r from-green-500 to-emerald-400"
            style={{ width: "100%" }}
          />
        </div>
        <p className="text-[10px] text-muted-foreground">{t("eloProgressMax")}</p>
      </div>
    );
  }

  // No medal (unranked): use 0 -> 1200 range, target is "provincial bronze"
  if (currentThreshold === null || nextThreshold === null) {
    const progress = Math.min(Math.max((meloVal / 1200) * 100, 0), 100);
    const remaining = Math.max(1200 - meloVal, 0);
    return (
      <div className="mt-2 space-y-1">
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-gradient-to-r from-green-500 to-emerald-400 transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
        <div className="flex items-center justify-between">
          <p className="text-[10px] text-muted-foreground">
            {t("eloProgressTarget", { target: `${t("medal:levels.provincial")} ${t("medal:types.bronze")}` })}
          </p>
          <p className="text-[10px] font-medium text-muted-foreground">
            {t("eloUntilNext", { amount: remaining })}
          </p>
        </div>
      </div>
    );
  }

  // Normal: progress within current tier
  const range = nextThreshold - currentThreshold;
  const progress = range > 0
    ? Math.min(Math.max(((meloVal - currentThreshold) / range) * 100, 0), 100)
    : 100;
  const remaining = Math.max(nextThreshold - meloVal, 0);

  // Resolve next medal level name from threshold
  const nextMedalLabel = getMedalLabelForThreshold(nextThreshold);

  return (
    <div className="mt-2 space-y-1">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-gradient-to-r from-green-500 to-emerald-400 transition-all duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="flex items-center justify-between">
        <p className="text-[10px] text-muted-foreground">
          {nextMedalLabel
            ? `${t("medal:levels." + nextMedalLabel.level)} ${t("medal:types." + nextMedalLabel.type)}`
            : `M-Elo: ${meloVal}`}
        </p>
        <p className="text-[10px] font-medium text-muted-foreground">
          {t("eloUntilNext", { amount: remaining })}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function TrainingPage() {
  const { t, i18n } = useTranslation(["training", "medal"]);
  const [topics, setTopics] = useState<TopicInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [recommendedTopics, setRecommendedTopics] = useState<RecommendedTopic[]>([]);
  const [radarData, setRadarData] = useState<RadarDataPoint[]>([]);

  useEffect(() => {
    api
      .get<ApiResponse<TopicInfo[]>>("/training/topics")
      .then((res) => setTopics(res.data.data))
      .catch((err) => {
        const msg = (err as { response?: { data?: { error?: { message?: string } } } })?.response
          ?.data?.error?.message;
        setError(msg ?? t("failedLoadTopics"));
      })
      .finally(() => setLoading(false));

    getRecommendedTopics(3)
      .then((data) => setRecommendedTopics(data))
      .catch(() => {});

    // Fetch M-Elo data for radar chart
    getMElo()
      .then((meloResult) => {
        if (meloResult.melos.length > 0) {
          const radar = buildRadarDataFromMElo(meloResult.melos, meloResult.global_elo, t);
          setRadarData(radar);
        }
      })
      .catch(() => {});
  }, [t]);

  const isZh = i18n.language?.startsWith("zh");

  if (loading) {
    return <LoadingSpinner text={t("loadingTopics")} className="py-20" />;
  }

  if (error) {
    return (
      <div className="mx-auto max-w-4xl">
        <ErrorMessage message={error} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader title={t("topicTraining")} description={t("topicTrainingDesc")} />

      {/* Skill Radar (FR-25.1) */}
      <TrainingRadarChart data={radarData} topics={topics} />

      {/* Recommended topics section */}
      {recommendedTopics.length > 0 && (
        <div className="rounded-xl border border-primary/20 bg-primary/5 p-5">
          <div className="flex items-center gap-2 mb-3">
            <Sparkles className="size-5 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">
              {t("recommendedTopics.title")}
            </h2>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {recommendedTopics.map((rec) => {
              const matchedTopic = topics.find((tp) => tp.slug === rec.slug);
              const displayName = isZh && rec.name_zh ? rec.name_zh : rec.name;
              return (
                <Link
                  key={rec.slug}
                  to={matchedTopic ? `/training/${matchedTopic.id}` : "#"}
                  className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/30"
                >
                  <p className="text-sm font-semibold text-foreground">{displayName}</p>
                  <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
                    {rec.melo === null
                      ? t("recommendedTopics.notStarted", { topic: displayName })
                      : t("recommendedTopics.improve", { topic: displayName, melo: Math.round(rec.melo) })}
                  </p>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      {/* Today's training goal hint */}
      <div className="flex items-center gap-2 rounded-lg bg-muted/50 px-4 py-2.5">
        <Target className="size-4 text-primary shrink-0" />
        <p className="text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{t("todayGoal.title")}</span>
          {" - "}
          {t("todayGoal.hint")}
        </p>
      </div>

      {topics.length === 0 ? (
        <div className="rounded-xl border border-border bg-card px-4 py-12 text-center">
          <BookOpen className="mx-auto size-10 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">{t("noTopics")}</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {topics.map((topic) => {
            const displayName = isZh && topic.name_zh ? topic.name_zh : topic.name;

            return (
              <Link
                key={topic.id}
                to={`/training/${topic.id}`}
                className="group relative rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-green-500/10">
                      <Dumbbell className="size-5 text-green-400" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-foreground group-hover:text-primary truncate">
                          {t(`topic.${topic.slug}`, displayName)}
                        </h3>
                        {/* Medal Badge (FR-26.1) */}
                        {topic.medal && (
                          <MedalBadge
                            level={topic.medal.level}
                            type={topic.medal.type}
                            size="sm"
                          />
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {t("progress")}: {topic.solved_count}/{topic.total_problems}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Elo Progress Bar (FR-26.2) */}
                <EloProgressBar
                  melo={topic.melo}
                  currentThreshold={topic.current_medal_threshold}
                  nextThreshold={topic.next_medal_threshold}
                  t={t}
                />

                {/* Hover-only secondary info */}
                <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                  <span>{t("solvedCount", { count: topic.solved_count })}</span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
