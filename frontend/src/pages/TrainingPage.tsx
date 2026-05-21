import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Dumbbell, BookOpen, Sparkles, Target } from "lucide-react";
import { useTranslation } from "react-i18next";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";
import { PageHeader } from "@/components/PageHeader";
import api from "@/services/api";
import { getRecommendedTopics } from "@/services/trainingApi";
import type { ApiResponse, TopicInfo, UserSettingsData, RecommendedTopic } from "@/types";

function ProgressRing({ percent }: { percent: number }) {
  const radius = 16;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percent / 100) * circumference;

  return (
    <svg width="40" height="40" className="shrink-0">
      <circle
        cx="20" cy="20" r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        className="text-muted-foreground/20"
      />
      <circle
        cx="20" cy="20" r={radius}
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        className="text-green-400"
        transform="rotate(-90 20 20)"
      />
      <text
        x="20" y="20"
        textAnchor="middle"
        dominantBaseline="central"
        className="fill-foreground text-[10px] font-semibold"
      >
        {percent}%
      </text>
    </svg>
  );
}

export default function TrainingPage() {
  const { t, i18n } = useTranslation("training");
  const [topics, setTopics] = useState<TopicInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [recommendedTopics, setRecommendedTopics] = useState<RecommendedTopic[]>([]);

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
            const progress = topic.total_problems > 0
              ? Math.round((topic.solved_count / topic.total_problems) * 100)
              : 0;
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
                      <h3 className="text-sm font-semibold text-foreground group-hover:text-primary truncate">
                        {t(`topic.${topic.slug}`, displayName)}
                      </h3>
                      <p className="mt-0.5 text-xs text-muted-foreground">
                        {t("progress")}: {topic.solved_count}/{topic.total_problems}
                      </p>
                    </div>
                  </div>
                  <ProgressRing percent={progress} />
                </div>

                {/* Hover-only secondary info */}
                <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                  {topic.melo !== null && (
                    <span>{t("meloLabel")}: {Math.round(topic.melo)}</span>
                  )}
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
