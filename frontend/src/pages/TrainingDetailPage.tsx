import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  ExternalLink,
  Loader2,
  Play,
  RefreshCw,
  StopCircle,
  Clock,
  Trophy,
  List,
  Sparkles,
  Filter,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { StreakEffect } from "@/components/animations/StreakEffect";
import { CoinAnimation } from "@/components/animations/CoinAnimation";
import { AchievementPopup } from "@/components/animations";
import { ProblemViewer } from "@/components/ProblemViewer";
import { SolvingTimeline } from "@/components/SolvingTimeline";
import { extractApiError, formatTime, getRatingColor } from "@/utils";
import api from "@/services/api";
import {
  getActiveTrainingSession,
  getRecommendedProblem,
  getCuratedProblems,
} from "@/services/trainingApi";
import type {
  ApiResponse,
  AchievementEvent,
  CuratedProblemInfo,
  RecommendedProblem,
  TopicDetail,
  TrainingSessionInfo,
} from "@/types";

type Phase = "loading" | "topic" | "session" | "result";
type DetailMode = "recommend" | "list";

export default function TrainingDetailPage() {
  const { id: topicId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation(["training", "common"]);
  const isZh = i18n.language?.startsWith("zh");

  // Core state
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

  // Dual mode state
  const [detailMode, setDetailMode] = useState<DetailMode>("recommend");
  const [recommendedProblem, setRecommendedProblem] = useState<RecommendedProblem | null>(null);
  const [recommendLoading, setRecommendLoading] = useState(false);

  // Problem list mode state
  const [curatedProblems, setCuratedProblems] = useState<CuratedProblemInfo[]>([]);
  const [curatedTotal, setCuratedTotal] = useState(0);
  const [curatedOffset, setCuratedOffset] = useState(0);
  const [curatedLoading, setCuratedLoading] = useState(false);
  const [curatedHasMore, setCuratedHasMore] = useState(false);
  const [filterMinRating, setFilterMinRating] = useState<string>("");
  const [filterMaxRating, setFilterMaxRating] = useState<string>("");

  // -- Data loading --
  useEffect(() => {
    if (!topicId) return;

    api
      .get<ApiResponse<TopicDetail>>(`/training/topics/${topicId}`)
      .then(async (res) => {
        setTopic(res.data.data);

        try {
          const activeSession = await getActiveTrainingSession(topicId);
          if (activeSession) {
            setSession(activeSession);
            setPhase("session");
            const initialElapsed = activeSession.started_at
              ? Math.max(0, Math.floor((Date.now() - new Date(activeSession.started_at).getTime()) / 1000))
              : 0;
            setElapsed(initialElapsed);
            timerRef.current = setInterval(() => setElapsed((p) => p + 1), 1000);
          } else {
            setPhase("topic");
          }
        } catch {
          setPhase("topic");
        }
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
          if (topicId) {
            try {
              const topicRes = await api.get<ApiResponse<TopicDetail>>(
                `/training/topics/${topicId}`,
              );
              setTopic(topicRes.data.data);
            } catch { /* Continue even if refresh fails */ }
          }
          try {
            const sessionRes = await api.get<ApiResponse<TrainingSessionInfo>>(
              `/training/session/${session.id}`,
            );
            setSession(sessionRes.data.data);
          } catch { /* Continue even if refresh fails */ }
        }
      } catch { /* Continue polling on error */ }
    };

    trackingPollRef.current = setInterval(pollTracking, 5000);
    return () => {
      if (trackingPollRef.current) clearInterval(trackingPollRef.current);
    };
  }, [session, phase, topicId, t]);

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

  // -- Fetch recommended problem --
  const fetchRecommendedProblem = useCallback(async () => {
    if (!topicId) return;
    setRecommendLoading(true);
    try {
      const result = await getRecommendedProblem(topicId);
      setRecommendedProblem(result);
    } catch {
      setRecommendedProblem(null);
    } finally {
      setRecommendLoading(false);
    }
  }, [topicId]);

  // Fetch recommended problem when topic phase starts and mode is recommend
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (phase === "topic" && detailMode === "recommend" && topicId) {
      fetchRecommendedProblem();
    }
  }, [phase, detailMode, topicId, fetchRecommendedProblem]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // -- Fetch curated problems --
  const fetchCuratedProblems = useCallback(async (append = false) => {
    if (!topicId) return;
    setCuratedLoading(true);
    try {
      const params: { limit?: number; offset?: number; min_rating?: number; max_rating?: number } = {};
      if (append) {
        params.offset = curatedOffset;
        params.limit = 20;
      } else {
        params.offset = 0;
        params.limit = 20;
      }
      if (filterMinRating) params.min_rating = parseInt(filterMinRating, 10);
      if (filterMaxRating) params.max_rating = parseInt(filterMaxRating, 10);

      const result = await getCuratedProblems(topicId, params);
      if (append) {
        setCuratedProblems((prev) => [...prev, ...result.problems]);
      } else {
        setCuratedProblems(result.problems);
      }
      setCuratedTotal(result.total);
      setCuratedOffset(result.offset + result.problems.length);
      setCuratedHasMore(result.offset + result.problems.length < result.total);
    } catch {
      // Silently fail
    } finally {
      setCuratedLoading(false);
    }
  }, [topicId, curatedOffset, filterMinRating, filterMaxRating]);

  // Fetch curated problems when switching to list mode
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (phase === "topic" && detailMode === "list" && topicId && curatedProblems.length === 0) {
      fetchCuratedProblems(false);
    }
  }, [phase, detailMode, topicId, curatedProblems.length, fetchCuratedProblems]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // -- Session management --
  const startSession = async () => {
    if (!topicId) return;
    setError("");
    setLoading(true);
    try {
      const res = await api.post<ApiResponse<TrainingSessionInfo>>("/training/start", {
        topic_id: topicId,
      });
      const sessionData = res.data.data;
      setSession(sessionData);
      setPhase("session");
      const initialElapsed = sessionData.started_at
        ? Math.max(0, Math.floor((Date.now() - new Date(sessionData.started_at).getTime()) / 1000))
        : 0;
      setElapsed(initialElapsed);
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
    hasAutoSelected.current = false;
  };

  // -- LOADING --
  if (phase === "loading") {
    return <LoadingSpinner text={t("training:loadingTopic")} className="py-20" />;
  }

  // -- TOPIC VIEW (dual mode) --
  if (phase === "topic" && topic) {
    const topicDisplayName = isZh && topic.name_zh ? topic.name_zh : topic.name;

    return (
      <div className="mx-auto max-w-6xl space-y-5">
        <button
          onClick={() => navigate("/training")}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {t("training:backToTopics")}
        </button>

        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-foreground">
              {t("training:topic." + topic.slug, topicDisplayName)}
            </h1>
            {topic.description && (
              <p className="mt-1 text-sm text-muted-foreground">{topic.description}</p>
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

        {/* Dual mode tabs */}
        <div className="flex gap-1 rounded-lg border border-border bg-muted/50 p-1">
          <button
            onClick={() => setDetailMode("recommend")}
            className={`flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              detailMode === "recommend"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Sparkles className="size-3.5" />
            {t("training:recommendMode")}
          </button>
          <button
            onClick={() => setDetailMode("list")}
            className={`flex items-center gap-1.5 rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              detailMode === "list"
                ? "bg-card text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <List className="size-3.5" />
            {t("training:problemListMode")}
          </button>
        </div>

        {/* Recommend mode */}
        {detailMode === "recommend" && (
          <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
            {/* Left: Problem statement */}
            <div>
              {recommendLoading && (
                <div className="flex items-center justify-center py-20">
                  <Loader2 className="size-6 animate-spin text-muted-foreground" />
                  <span className="ml-2 text-sm text-muted-foreground">
                    {t("training:loadingProblem")}
                  </span>
                </div>
              )}
              {!recommendLoading && recommendedProblem && (
                <ProblemViewer
                  contestId={recommendedProblem.contest_id}
                  index={recommendedProblem.index}
                  blindBox={false}
                />
              )}
              {!recommendLoading && !recommendedProblem && (
                <div className="rounded-xl border border-border bg-card px-4 py-12 text-center">
                  <p className="text-sm text-muted-foreground">
                    {t("training:noRecommendedProblem")}
                  </p>
                </div>
              )}
            </div>

            {/* Right: Info panel */}
            <div className="space-y-4">
              {/* Problem info card */}
              {recommendedProblem && (
                <div className="rounded-xl border border-border bg-card p-4 space-y-3">
                  <h3 className="text-sm font-semibold text-foreground">
                    {t("training:infoPanel.problemInfo")}
                  </h3>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">{t("training:infoPanel.rating")}</span>
                      <span
                        className="font-semibold"
                        style={{ color: getRatingColor(recommendedProblem.rating) }}
                      >
                        {recommendedProblem.rating ?? "-"}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">{t("training:infoPanel.yourMelo")}</span>
                      <span className="font-semibold text-foreground">
                        {Math.round(recommendedProblem.melo)}
                      </span>
                    </div>
                    {recommendedProblem.search_range && (
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">{t("training:infoPanel.searchRange")}</span>
                        <span className="text-xs text-muted-foreground">
                          {recommendedProblem.search_range[0]} - {recommendedProblem.search_range[1]}
                        </span>
                      </div>
                    )}
                  </div>

                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={fetchRecommendedProblem}
                    disabled={recommendLoading}
                  >
                    <RefreshCw className="mr-1.5 size-3.5" />
                    {t("training:changeProblem")}
                  </Button>

                  <a
                    href={recommendedProblem.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-1.5 text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
                  >
                    {t("training:infoPanel.problemInfo")}
                    <ExternalLink className="size-3.5" />
                  </a>
                </div>
              )}

              {/* Solving timeline */}
              {recommendedProblem && recommendedProblem.rating && (
                <SolvingTimeline
                  problemId={recommendedProblem.problem_id}
                  problemRating={recommendedProblem.rating}
                  userElo={recommendedProblem.melo}
                  startTime={new Date()}
                />
              )}
            </div>
          </div>
        )}

        {/* Problem list mode */}
        {detailMode === "list" && (
          <div className="space-y-4">
            {/* Difficulty filter */}
            <div className="flex items-center gap-3 rounded-lg border border-border bg-card p-3">
              <Filter className="size-4 text-muted-foreground" />
              <span className="text-xs font-medium text-muted-foreground">
                {t("training:difficultyFilter")}:
              </span>
              <input
                type="number"
                placeholder={t("training:minRating")}
                value={filterMinRating}
                onChange={(e) => setFilterMinRating(e.target.value)}
                className="w-24 rounded-md border border-border bg-transparent px-2 py-1 text-xs text-foreground"
              />
              <span className="text-xs text-muted-foreground">-</span>
              <input
                type="number"
                placeholder={t("training:maxRating")}
                value={filterMaxRating}
                onChange={(e) => setFilterMaxRating(e.target.value)}
                className="w-24 rounded-md border border-border bg-transparent px-2 py-1 text-xs text-foreground"
              />
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setCuratedOffset(0);
                  setCuratedProblems([]);
                  // Will trigger re-fetch via useEffect
                  setTimeout(() => fetchCuratedProblems(false), 0);
                }}
              >
                {t("training:apply")}
              </Button>
            </div>

            {/* Problem list */}
            <div className="rounded-xl border border-border bg-card">
              <div className="border-b border-border px-5 py-3">
                <h2 className="text-sm font-semibold text-foreground">
                  {t("training:problems", { count: curatedTotal })}
                </h2>
              </div>
              {curatedLoading && curatedProblems.length === 0 ? (
                <div className="px-5 py-8 text-center">
                  <Loader2 className="mx-auto size-5 animate-spin text-muted-foreground" />
                </div>
              ) : curatedProblems.length === 0 ? (
                <div className="px-5 py-8 text-center text-sm text-muted-foreground">
                  {t("training:noProblems")}
                </div>
              ) : (
                <div className="divide-y divide-border">
                  {curatedProblems.map((problem) => (
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

            {/* Load more */}
            {curatedHasMore && (
              <div className="flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fetchCuratedProblems(true)}
                  disabled={curatedLoading}
                >
                  {curatedLoading ? (
                    <>
                      <Loader2 className="mr-1.5 size-3.5 animate-spin" />
                      {t("training:loadingMore")}
                    </>
                  ) : (
                    t("training:loadMore")
                  )}
                </Button>
              </div>
            )}
            {!curatedHasMore && curatedProblems.length > 0 && (
              <p className="text-center text-xs text-muted-foreground">
                {t("training:noMoreProblems")}
              </p>
            )}
          </div>
        )}
      </div>
    );
  }

  // -- SESSION IN PROGRESS --
  if (phase === "session" && session && topic) {
    return (
      <div className="mx-auto max-w-4xl space-y-5">
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
            <div className="absolute -top-2 right-2">
              <CoinAnimation amount={lastTokensEarned} triggerKey={tokenTriggerKey} />
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
            <h2 className="text-sm font-semibold text-foreground">
              {t("training:problems", { count: topic.problems?.length ?? 0 })}
            </h2>
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
                          {t("training:solvedIn", {
                            time: formatTime(problem.time_spent),
                            attempts: problem.attempts,
                          })}
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
            {t("training:solvedOutOf", {
              solved: session.problems_solved,
              total: session.total_problems,
            })}
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
