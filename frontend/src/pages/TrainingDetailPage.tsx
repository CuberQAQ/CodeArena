import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  ExternalLink,
  Loader2,
  Play,
  StopCircle,
  Clock,
  Trophy,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { StreakEffect } from "@/components/animations/StreakEffect";
import { CoinAnimation } from "@/components/animations/CoinAnimation";
import { AchievementPopup } from "@/components/animations";
import { ProblemViewer } from "@/components/ProblemViewer";
import { extractApiError, formatTime, getRatingColor } from "@/utils";
import api from "@/services/api";
import type {
  ApiResponse,
  AchievementEvent,
  TopicDetail,
  TrainingSessionInfo,
} from "@/types";

type Phase = "loading" | "topic" | "session" | "result";

export default function TrainingDetailPage() {
  const { id: topicId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation(["training", "common"]);
  const [phase, setPhase] = useState<Phase>("loading");
  const [topic, setTopic] = useState<TopicDetail | null>(null);
  const [session, setSession] = useState<TrainingSessionInfo | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const trackingPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastTokensEarned = 0;
  const tokenTriggerKey = 0;
  const [achievements, setAchievements] = useState<AchievementEvent[]>([]);
  const [showAchievements, setShowAchievements] = useState(false);
  const [selectedProblemId, setSelectedProblemId] = useState<string | null>(null);
  const hasAutoSelected = useRef(false);

  useEffect(() => {
    if (!topicId) return;
    api
      .get<ApiResponse<TopicDetail>>(`/training/topics/${topicId}`)
      .then((res) => {
        setTopic(res.data.data);
        setPhase("topic");
      })
      .catch(() => {
        setError(t("training:failedLoadTopic"));
        setPhase("topic");
      });
  }, [topicId, t]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (trackingPollRef.current) clearInterval(trackingPollRef.current);
    };
  }, []);

  // Poll submission tracking status during active training session
  useEffect(() => {
    if (!session || phase !== "session") return;

    const pollTracking = async () => {
      try {
        const res = await api.get(
          `/submission-tracking/status?session_type=training&session_id=${session.id}`,
        );
        const tracking = res.data?.data;
        if (tracking && tracking.status === "timeout") {
          if (trackingPollRef.current) clearInterval(trackingPollRef.current);
          setError(t("training:trackingTimedOut"));
          return;
        }
        if (tracking && (tracking.status === "matched" || tracking.status === "settled")) {
          if (trackingPollRef.current) clearInterval(trackingPollRef.current);
          // Refresh topic details to show updated solved status
          if (topicId) {
            try {
              const topicRes = await api.get<ApiResponse<TopicDetail>>(
                `/training/topics/${topicId}`,
              );
              setTopic(topicRes.data.data);
            } catch {
              // Continue even if refresh fails
            }
          }
          // Refresh session status
          try {
            const sessionRes = await api.get<ApiResponse<TrainingSessionInfo>>(
              `/training/session/${session.id}`,
            );
            setSession(sessionRes.data.data);
          } catch {
            // Continue even if refresh fails
          }
        }
      } catch {
        // Continue polling on error
      }
    };

    trackingPollRef.current = setInterval(pollTracking, 5000);
    return () => {
      if (trackingPollRef.current) clearInterval(trackingPollRef.current);
    };
  }, [session, phase, topicId]);

  // Auto-select first unsolved problem when entering session phase
  useEffect(() => {
    if (phase === "session" && topic && !hasAutoSelected.current) {
      hasAutoSelected.current = true;
      const firstUnsolved = topic.problems?.find(
        (p) => !p.solved && p.contest_id && p.index,
      );
      if (firstUnsolved) {
        const timer = setTimeout(() => setSelectedProblemId(firstUnsolved.problem_id), 0);
        return () => clearTimeout(timer);
      }
    }
  }, [phase, topic]);

  const startSession = async () => {
    if (!topicId) return;
    setError("");
    setLoading(true);
    try {
      const res = await api.post<ApiResponse<TrainingSessionInfo>>("/training/start", {
        topic_id: topicId,
      });
      setSession(res.data.data);
      setPhase("session");
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((p) => p + 1), 1000);
    } catch (err) {
      setError(extractApiError(err, t("training:failedStartSession")));
    } finally {
      setLoading(false);
    }
  };

  const abandonSession = async () => {
    if (!session) return;
    setError("");
    setLoading(true);
    try {
      await api.post(`/training/session/${session.id}/abandon`);
      if (timerRef.current) clearInterval(timerRef.current);
      setPhase("result");
    } catch (err) {
      setError(extractApiError(err, t("training:failedAbandon")));
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setSession(null);
    setPhase("topic");
    setElapsed(0);
    setError("");
    setAchievements([]);
    setShowAchievements(false);
    setSelectedProblemId(null);
  };

  // -- LOADING --
  if (phase === "loading") {
    return <LoadingSpinner text={t("training:loadingTopic")} className="py-20" />;
  }

  // -- TOPIC VIEW --
  if (phase === "topic" && topic) {
    return (
      <div className="mx-auto max-w-4xl space-y-5">
        <button
          onClick={() => navigate("/training")}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {t("training:backToTopics")}
        </button>

        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-foreground">{topic.name}</h1>
            {topic.description && (
              <p className="mt-1 text-sm text-muted-foreground">{topic.description}</p>
            )}
            {topic.cf_tags.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {topic.cf_tags.map((tag) => (
                  <span key={tag} className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
          <Button onClick={startSession} disabled={loading}>
            {loading ? (
              <Loader2 className="mr-2 size-4 animate-spin" />
            ) : (
              <Play className="mr-2 size-4" />
            )}
            {t("training:startTraining")}
          </Button>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Problem list */}
        <div className="rounded-xl border border-border bg-card">
          <div className="border-b border-border px-5 py-3">
            <h2 className="text-sm font-semibold text-foreground">
              {t("training:problems", { count: topic.problems?.length ?? 0 })}
            </h2>
          </div>
          {(!topic.problems || topic.problems.length === 0) ? (
            <div className="px-5 py-8 text-center text-sm text-muted-foreground">
              {t("training:noProblems")}
            </div>
          ) : (
            <div className="divide-y divide-border">
              {topic.problems.map((problem) => (
                <div
                  key={problem.problem_id}
                  className="flex items-center gap-4 px-5 py-3"
                >
                  {problem.solved ? (
                    <CheckCircle2 className="size-4 shrink-0 text-green-400" />
                  ) : (
                    <Circle className="size-4 shrink-0 text-muted-foreground" />
                  )}
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">
                      {problem.contest_id}
                      {problem.index} - {problem.name}
                    </p>
                    {problem.solved && problem.time_spent != null && (
                      <p className="text-xs text-muted-foreground">
                        {t("training:solvedIn", { time: formatTime(problem.time_spent), attempts: problem.attempts })}
                      </p>
                    )}
                  </div>
                  {problem.rating && (
                    <span
                      className="shrink-0 text-sm font-bold"
                      style={{ color: getRatingColor(problem.rating) }}
                    >
                      {problem.rating}
                    </span>
                  )}
                  <a
                    href={problem.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 text-muted-foreground hover:text-foreground"
                  >
                    <ExternalLink className="size-4" />
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // -- SESSION IN PROGRESS --
  if (phase === "session" && session && topic) {
    return (
      <div className="mx-auto max-w-4xl space-y-5">
        {/* Achievement popup overlay */}
        {achievements.length > 0 && showAchievements && (
          <AchievementPopup
            achievements={achievements}
            onComplete={() => setShowAchievements(false)}
          />
        )}

        <div className="flex items-center justify-between">
          <button
            onClick={() => navigate("/training")}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            {t("training:topics")}
          </button>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Clock className="size-4" />
              <span className="font-mono">{formatTime(elapsed)}</span>
            </div>
            <Button variant="destructive" size="sm" onClick={abandonSession} disabled={loading}>
              <StopCircle className="mr-1.5 size-3.5" />
              {t("training:endSession")}
            </Button>
          </div>
        </div>

        {/* Session info */}
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">{t("training:solvedLabel")}</p>
            <p className="mt-1 text-xl font-bold text-green-400">{session.problems_solved}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">{t("common:total")}</p>
            <p className="mt-1 text-xl font-bold text-foreground">{session.total_problems}</p>
          </div>
          <div className="relative rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">{t("training:streak")}</p>
            <div className="mt-1 flex items-center justify-center">
              <StreakEffect streak={session.streak_count} />
            </div>
            {/* Coin animation overlay */}
            <div className="absolute -top-2 right-2">
              <CoinAnimation
                amount={lastTokensEarned}
                triggerKey={tokenTriggerKey}
              />
            </div>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Problem list with inline report panel */}
        <div className="rounded-xl border border-border bg-card">
          <div className="border-b border-border px-5 py-3">
            <h2 className="text-sm font-semibold text-foreground">{t("training:problems", { count: topic.problems?.length ?? 0 })}</h2>
          </div>
          <div className="divide-y divide-border">
            {topic.problems?.map((problem) => {
              const isSelected = selectedProblemId === problem.problem_id;
              return (
                <div
                  key={problem.problem_id}
                  className={`cursor-pointer transition-colors ${
                    isSelected ? "bg-primary/5" : "hover:bg-muted/30"
                  }`}
                  onClick={() => {
                    if (problem.contest_id && problem.index) {
                      setSelectedProblemId(problem.problem_id);
                    }
                  }}
                >
                  <div className="flex items-center gap-4 px-5 py-3">
                    {problem.solved ? (
                      <CheckCircle2 className="size-4 shrink-0 text-green-400" />
                    ) : (
                      <Circle className="size-4 shrink-0 text-muted-foreground" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground">
                        {problem.contest_id}
                        {problem.index} - {problem.name}
                      </p>
                      {problem.solved && problem.time_spent != null && (
                        <p className="text-xs text-muted-foreground">
                          {t("training:solvedIn", { time: formatTime(problem.time_spent), attempts: problem.attempts })}
                        </p>
                      )}
                    </div>
                    {problem.rating && (
                      <span
                        className="shrink-0 text-sm font-bold"
                        style={{ color: getRatingColor(problem.rating) }}
                      >
                        {problem.rating}
                      </span>
                    )}
                    <div className="flex items-center gap-2">
                      <a
                        href={problem.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-muted-foreground hover:text-foreground"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <ExternalLink className="size-4" />
                      </a>
                      {!problem.solved && (
                        <Loader2 className="size-4 animate-spin text-primary" />
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* ProblemViewer for selected problem */}
        {(() => {
          const selectedProblem = topic.problems?.find(
            (p) => p.problem_id === selectedProblemId,
          );
          if (!selectedProblem || !selectedProblem.contest_id || !selectedProblem.index) {
            return null;
          }
          return (
            <ProblemViewer
              contestId={selectedProblem.contest_id}
              index={selectedProblem.index}
              blindBox={false}
            />
          );
        })()}
      </div>
    );
  }

  // -- RESULT --
  if (phase === "result") {
    return (
      <div className="mx-auto max-w-2xl space-y-5 text-center">
        <div className="mx-auto flex size-16 items-center justify-center rounded-2xl bg-green-500/10">
          <Trophy className="size-8 text-green-400" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">{t("training:trainingComplete")}</h1>
        {session && (
          <p className="text-sm text-muted-foreground">
            {t("training:solvedOutOf", { solved: session.problems_solved, total: session.total_problems })}
          </p>
        )}
        <div className="flex justify-center gap-3">
          <Button onClick={handleReset}>{t("training:trainAgain")}</Button>
          <Button variant="outline" onClick={() => navigate("/training")}>
            {t("training:backToTopics")}
          </Button>
        </div>
      </div>
    );
  }

  // Fallback
  return <LoadingSpinner className="py-20" />;
}
