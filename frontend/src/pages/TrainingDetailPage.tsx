import { useEffect, useRef, useState, useCallback } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  ExternalLink,
  Loader2,
  RefreshCw,
  StopCircle,
  Clock,
  Trophy,
  List,
  Sparkles,
  Filter,
  Shield,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/alert-dialog";
import { Slider } from "@/components/ui/slider";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { EloProgressBar } from "@/components/EloProgressBar";
import { StreakEffect } from "@/components/animations/StreakEffect";
import { CoinAnimation } from "@/components/animations/CoinAnimation";
import { AchievementPopup } from "@/components/animations";
import { ProblemViewer } from "@/components/ProblemViewer";
import { SolvingTimeline } from "@/components/SolvingTimeline";
import { extractApiError, formatTime, getRatingColor, stripIndexPrefix } from "@/utils";
import api from "@/services/api";
import {
  getActiveTrainingSession,
  getRecommendedProblem,
  getCuratedProblems,
  skipProblem,
} from "@/services/trainingApi";
import type {
  ApiResponse,
  AchievementEvent,
  CuratedProblemInfo,
  RecommendedProblem,
  TopicDetail,
  TrainingSessionInfo,
} from "@/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Protection period duration in seconds (5 minutes). */
const PROTECTION_DURATION = 300;

type Phase = "loading" | "active" | "result";
type DetailMode = "recommend" | "list";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format remaining protection seconds as M:SS. */
function formatProtectionTime(seconds: number): string {
  const m = Math.floor(Math.max(0, seconds) / 60);
  const s = Math.floor(Math.max(0, seconds) % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

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

  // Skip confirmation dialog
  const [skipDialogOpen, setSkipDialogOpen] = useState(false);
  const [pendingSwitchProblemId, setPendingSwitchProblemId] = useState<string | null>(null);
  const skipLoadingRef = useRef(false);

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
  // Slider state (derived from topic M-Elo, step 50)
  const [sliderRange, setSliderRange] = useState<[number, number]>([800, 2400]);

  // Protection period remaining seconds
  const [protectionRemaining, setProtectionRemaining] = useState<number | null>(null);

  // -- Navigation guard --
  useEffect(() => {
    if (phase !== "active" || !session) return;

    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [phase, session]);

  // -- Auto-start session on mount --
  useEffect(() => {
    if (!topicId) return;

    let cancelled = false;

    const init = async () => {
      try {
        // 1. Load topic details + recover active session in parallel
        const [topicRes, activeSession] = await Promise.all([
          api.get<ApiResponse<TopicDetail>>(`/training/topics/${topicId}`).catch((e) => {
            throw e;
          }),
          getActiveTrainingSession(topicId).catch(() => null),
        ]);
        if (cancelled) return;

        const topicData = topicRes.data.data;
        setTopic(topicData);

        // 2. If active session found, resume it
        if (activeSession) {
          setSession(activeSession);
          const startedAt = activeSession.started_at ? new Date(activeSession.started_at) : new Date();
          const initialElapsed = activeSession.started_at
            ? Math.max(0, Math.floor((Date.now() - startedAt.getTime()) / 1000))
            : 0;
          setElapsed(initialElapsed);
          setPhase("active");
          return;
        }

        // 3. No active session -- auto-start new one
        try {
          const startRes = await api.post<ApiResponse<TrainingSessionInfo>>("/training/start", {
            topic_id: topicId,
          });
          if (cancelled) return;
          const sessionData = startRes.data.data;
          setSession(sessionData);
          const startedAt = sessionData.started_at ? new Date(sessionData.started_at) : new Date();
          const initialElapsed = sessionData.started_at
            ? Math.max(0, Math.floor((Date.now() - startedAt.getTime()) / 1000))
            : 0;
          setElapsed(initialElapsed);
          setPhase("active");
        } catch (err) {
          if (cancelled) return;
          setError(extractApiError(err, t("training:autoStartFailed")));
          setPhase("active");
        }
      } catch {
        if (cancelled) return;
        setError(t("training:failedLoadTopic"));
        setPhase("active");
      }
    };

    init();
    return () => {
      cancelled = true;
    };
  }, [topicId, t]);

  // -- Sync slider range when topic loads --
  /* eslint-disable react-hooks/set-state-in-effect -- one-time sync from loaded topic data */
  useEffect(() => {
    if (!topic) return;
    const melo = topic.melo ?? 1200;
    const sliderMin = Math.max(800, melo - 200);
    const sliderMax = melo + 400;
    // Snap to step of 50
    const snappedMin = Math.round(sliderMin / 50) * 50;
    const snappedMax = Math.round(sliderMax / 50) * 50;
    setSliderRange([snappedMin, snappedMax]);
    // Also initialize filter values to match full range
    setFilterMinRating(String(snappedMin));
    setFilterMaxRating(String(snappedMax));
  }, [topic]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // -- Start timer when entering active phase --
  useEffect(() => {
    if (phase !== "active") return;
    // Clear any existing timer first
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => setElapsed((p) => p + 1), 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [phase]);

  // -- Protection period countdown --
  /* eslint-disable react-hooks/set-state-in-effect -- interval callback updates remaining time */
  useEffect(() => {
    if (phase !== "active" || !session?.started_at) {
      setProtectionRemaining(null);
      return;
    }

    const startedAt = new Date(session.started_at).getTime();

    const update = () => {
      const secs = Math.max(0, PROTECTION_DURATION - Math.floor((Date.now() - startedAt) / 1000));
      setProtectionRemaining(secs > 0 ? secs : null);
    };

    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [phase, session?.started_at]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (trackingPollRef.current) clearInterval(trackingPollRef.current);
    };
  }, []);

  // Poll submission tracking status during active training session
  useEffect(() => {
    if (!session || phase !== "active") return;

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

  // Auto-select first unsolved problem when entering active phase
  /* eslint-disable react-hooks/set-state-in-effect -- one-time auto-select via ref guard */
  useEffect(() => {
    if (phase === "active" && topic && !hasAutoSelected.current) {
      hasAutoSelected.current = true;
      const firstUnsolved = topic.problems?.find(
        (p) => !p.solved && p.contest_id && p.index,
      );
      if (firstUnsolved) {
        setSelectedProblemId(firstUnsolved.problem_id);
      } else if (topic.problems && topic.problems.length > 0) {
        // All problems solved -- pick the first one
        setSelectedProblemId(topic.problems[0].problem_id);
      }
    }
  }, [phase, topic]);
  /* eslint-enable react-hooks/set-state-in-effect */

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

  // Fetch recommended problem when in recommend mode
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (phase === "active" && detailMode === "recommend" && topicId) {
      fetchRecommendedProblem();
    }
  }, [phase, detailMode, topicId, fetchRecommendedProblem]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // -- Fetch curated problems --
  const fetchCuratedProblems = useCallback(async (append = false, overrideFilters?: { min?: number; max?: number }) => {
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
      const minRating = overrideFilters?.min ?? (filterMinRating ? parseInt(filterMinRating, 10) : undefined);
      const maxRating = overrideFilters?.max ?? (filterMaxRating ? parseInt(filterMaxRating, 10) : undefined);
      if (minRating !== undefined) params.min_rating = minRating;
      if (maxRating !== undefined) params.max_rating = maxRating;

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
    if (phase === "active" && detailMode === "list" && topicId && curatedProblems.length === 0) {
      fetchCuratedProblems(false);
    }
  }, [phase, detailMode, topicId, curatedProblems.length, fetchCuratedProblems]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // -- Derived data --
  const selectedProblem = topic?.problems?.find(
    (p) => p.problem_id === selectedProblemId,
  );

  const isProtectionActive = protectionRemaining !== null && protectionRemaining > 0;

  // -- Problem switching logic --
  const handleProblemSwitch = useCallback(
    (newProblemId: string) => {
      if (newProblemId === selectedProblemId) return;

      // During protection period -- free switch
      if (isProtectionActive) {
        setSelectedProblemId(newProblemId);
        return;
      }

      // After protection -- show confirmation dialog
      setPendingSwitchProblemId(newProblemId);
      setSkipDialogOpen(true);
    },
    [selectedProblemId, isProtectionActive],
  );

  const handleSkipConfirm = useCallback(async () => {
    if (!session || !pendingSwitchProblemId || skipLoadingRef.current) return;
    skipLoadingRef.current = true;
    try {
      if (selectedProblemId) {
        await skipProblem(session.id, selectedProblemId);
      }
      setSelectedProblemId(pendingSwitchProblemId);
    } catch (err) {
      setError(extractApiError(err, t("training:skipProblemFailed")));
    } finally {
      skipLoadingRef.current = false;
      setSkipDialogOpen(false);
      setPendingSwitchProblemId(null);
    }
  }, [session, pendingSwitchProblemId, selectedProblemId, t]);

  const handleSkipCancel = useCallback(() => {
    setSkipDialogOpen(false);
    setPendingSwitchProblemId(null);
  }, []);

  // -- Recommend mode "change problem" handler --
  const handleChangeProblem = useCallback(async () => {
    if (isProtectionActive || !session) {
      // During protection -- just fetch a new one, no skip penalty
      fetchRecommendedProblem();
      return;
    }

    // After protection -- need confirmation dialog
    // We treat "change problem" as switching to a new problem
    setPendingSwitchProblemId("__recommend_change__");
    setSkipDialogOpen(true);
  }, [isProtectionActive, session, fetchRecommendedProblem]);

  const handleRecommendSkipConfirm = useCallback(async () => {
    if (!session || !selectedProblemId || skipLoadingRef.current) return;
    skipLoadingRef.current = true;
    try {
      await skipProblem(session.id, selectedProblemId);
      fetchRecommendedProblem();
    } catch (err) {
      setError(extractApiError(err, t("training:skipProblemFailed")));
    } finally {
      skipLoadingRef.current = false;
      setSkipDialogOpen(false);
      setPendingSwitchProblemId(null);
    }
  }, [session, selectedProblemId, fetchRecommendedProblem, t]);

  // Unified skip confirm handler
  const handleUnifiedSkipConfirm = useCallback(() => {
    if (pendingSwitchProblemId === "__recommend_change__") {
      handleRecommendSkipConfirm();
    } else {
      handleSkipConfirm();
    }
  }, [pendingSwitchProblemId, handleRecommendSkipConfirm, handleSkipConfirm]);

  // -- Session management --
  const abandonSession = useCallback(async () => {
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
  }, [session, t]);

  const handleBack = useCallback(() => {
    // During protection -- abandon without penalty (backend handles this)
    abandonSession();
  }, [abandonSession]);

  const handleReset = useCallback(() => {
    setSession(null);
    setPhase("loading");
    setElapsed(0);
    setError("");
    setAchievements([]);
    setShowAchievements(false);
    setSelectedProblemId(null);
    hasAutoSelected.current = false;
    setProtectionRemaining(null);
    setDetailMode("recommend");
    setRecommendedProblem(null);
    setCuratedProblems([]);
    setCuratedTotal(0);
    setCuratedOffset(0);
  }, []);

  // ---------------------------------------------------------------------------
  // RENDER: Loading
  // ---------------------------------------------------------------------------
  if (phase === "loading") {
    return <LoadingSpinner text={t("training:loadingTopic")} className="py-20" />;
  }

  // ---------------------------------------------------------------------------
  // RENDER: Result
  // ---------------------------------------------------------------------------
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

  // ---------------------------------------------------------------------------
  // RENDER: Active (unified dual-column layout)
  // ---------------------------------------------------------------------------

  const topicDisplayName = topic ? (isZh && topic.name_zh ? topic.name_zh : topic.name) : "";
  const sessionStartTime = session?.started_at ? new Date(session.started_at) : new Date();

  // Derive the display problem for ProblemViewer based on mode
  const problemViewerProblem = (() => {
    if (detailMode === "recommend") {
      if (!recommendedProblem) return null;
      return {
        contestId: String(recommendedProblem.contest_id),
        index: recommendedProblem.index,
        rating: recommendedProblem.rating,
        problemId: recommendedProblem.problem_id,
        url: recommendedProblem.url,
        melo: recommendedProblem.melo,
      };
    }
    // List mode -- use selectedProblem
    if (!selectedProblem || !selectedProblem.contest_id || !selectedProblem.index) return null;
    return {
      contestId: String(selectedProblem.contest_id),
      index: selectedProblem.index,
      rating: selectedProblem.rating,
      problemId: selectedProblem.problem_id,
      url: selectedProblem.url,
    };
  })();

  return (
    <div className="space-y-3">
      {/* Achievement popup */}
      {achievements.length > 0 && showAchievements && (
        <AchievementPopup
          achievements={achievements}
          onComplete={() => setShowAchievements(false)}
        />
      )}

      {/* Protection period banner */}
      {protectionRemaining !== null && protectionRemaining > 0 && (
        <div className="flex items-center justify-center gap-2 rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-2 text-sm font-medium text-green-400">
          <Shield className="size-4" />
          {t("training:protection.banner", { time: formatProtectionTime(protectionRemaining) })}
        </div>
      )}

      {/* Skip confirmation dialog */}
      <ConfirmDialog
        open={skipDialogOpen}
        onClose={handleSkipCancel}
        onConfirm={handleUnifiedSkipConfirm}
        title={t("training:skipDialog.title")}
        message={t("training:skipDialog.message")}
        cancelText={t("training:skipDialog.cancel")}
        confirmText={t("training:skipDialog.confirm")}
        confirmClassName="bg-destructive/10 text-destructive hover:bg-destructive/20"
      />

      {/* Top navigation bar */}
      <div className="flex items-center justify-between">
        <button
          onClick={handleBack}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          {t("training:topics")}
        </button>
        <div className="flex items-center gap-3">
          {/* Topic name */}
          {topic && (
            <span className="text-sm font-medium text-foreground">
              {t("training:topic." + topic.slug, topicDisplayName)}
            </span>
          )}
          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Clock className="size-4" />
            <span className="font-mono">{formatTime(elapsed)}</span>
          </div>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Main dual-column layout */}
      <div className="flex flex-col gap-4 lg:flex-row lg:gap-6">
        {/* ---- LEFT: ProblemViewer ---- */}
        <div className="flex-1 min-w-0">
          {problemViewerProblem ? (
            <ProblemViewer
              contestId={problemViewerProblem.contestId}
              index={problemViewerProblem.index}
              blindBox={false}
            />
          ) : (
            <div className="rounded-xl border border-border bg-card px-4 py-12 text-center">
              <List className="mx-auto size-8 text-muted-foreground/50" />
              <p className="mt-3 text-sm text-muted-foreground">
                {t("training:selectProblemHint")}
              </p>
            </div>
          )}
        </div>

        {/* ---- RIGHT: Info panel ---- */}
        <div className="w-full shrink-0 space-y-4 lg:w-80 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
          {/* Compact stats (only when session exists) */}
          {session && (
            <div className="grid grid-cols-3 gap-2">
              <div className="rounded-xl border border-border bg-card p-3 text-center">
                <p className="text-[10px] text-muted-foreground">{t("training:solvedLabel")}</p>
                <p className="mt-0.5 text-lg font-bold text-green-400">{session.problems_solved}</p>
              </div>
              <div className="rounded-xl border border-border bg-card p-3 text-center">
                <p className="text-[10px] text-muted-foreground">{t("common:total")}</p>
                <p className="mt-0.5 text-lg font-bold text-foreground">{session.total_problems}</p>
              </div>
              <div className="relative rounded-xl border border-border bg-card p-3 text-center">
                <p className="text-[10px] text-muted-foreground">{t("training:streak")}</p>
                <div className="mt-0.5 flex items-center justify-center">
                  <StreakEffect streak={session.streak_count} />
                </div>
                <div className="absolute -top-2 right-2">
                  <CoinAnimation amount={lastTokensEarned} triggerKey={tokenTriggerKey} />
                </div>
              </div>
            </div>
          )}

          {/* Elo progress bar (only when topic has melo) */}
          {topic && topic.melo != null && (
            <EloProgressBar
              melo={topic.melo}
              currentMedalThreshold={topic.current_medal_threshold}
              nextMedalThreshold={topic.next_medal_threshold}
              problemId={
                detailMode === "recommend"
                  ? recommendedProblem?.problem_id
                  : selectedProblem?.problem_id
              }
              problemRating={
                detailMode === "recommend"
                  ? recommendedProblem?.rating ?? null
                  : selectedProblem?.rating ?? null
              }
            />
          )}

          {/* Mode tabs (compact) */}
          <div className="flex gap-1 rounded-lg border border-border bg-muted/50 p-1">
            <button
              onClick={() => setDetailMode("recommend")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                detailMode === "recommend"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Sparkles className="size-3" />
              {t("training:recommendMode")}
            </button>
            <button
              onClick={() => setDetailMode("list")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                detailMode === "list"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <List className="size-3" />
              {t("training:problemListMode")}
            </button>
          </div>

          {/* ---- RECOMMEND MODE content ---- */}
          {detailMode === "recommend" && (
            <>
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

                  {/* Difficulty range slider for recommend mode */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <Filter className="size-3.5 text-muted-foreground" />
                        <span className="text-xs font-medium text-muted-foreground">
                          {t("training:difficultyFilter")}
                        </span>
                      </div>
                      <span className="text-xs font-semibold tabular-nums text-foreground">
                        {t("training:difficultySlider.range", {
                          min: sliderRange[0],
                          max: sliderRange[1],
                        })}
                      </span>
                    </div>
                    <Slider
                      value={sliderRange}
                      onValueChange={(v) => {
                        const range = v as [number, number];
                        setSliderRange(range);
                        setFilterMinRating(String(range[0]));
                        setFilterMaxRating(String(range[1]));
                      }}
                      min={Math.max(800, (topic?.melo ?? 1200) - 200)}
                      max={(topic?.melo ?? 1200) + 400}
                      step={50}
                      aria-label={t("training:difficultyFilter")}
                    />
                  </div>

                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={handleChangeProblem}
                    disabled={recommendLoading}
                  >
                    <RefreshCw className={`mr-1.5 size-3.5 ${recommendLoading ? "animate-spin" : ""}`} />
                    {t("training:changeProblem")}
                  </Button>

                  <a
                    href={recommendedProblem.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-1.5 text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
                  >
                    {t("training:infoPanel.viewOnCodeforces")}
                    <ExternalLink className="size-3.5" />
                  </a>
                </div>
              )}

              {recommendLoading && !recommendedProblem && (
                <div className="rounded-xl border border-border bg-card px-4 py-8 text-center">
                  <Loader2 className="mx-auto size-5 animate-spin text-muted-foreground" />
                  <p className="mt-2 text-xs text-muted-foreground">{t("training:loadingProblem")}</p>
                </div>
              )}

              {!recommendLoading && !recommendedProblem && (
                <div className="rounded-xl border border-border bg-card px-4 py-8 text-center">
                  <p className="text-xs text-muted-foreground">
                    {t("training:noRecommendedProblem")}
                  </p>
                </div>
              )}

              {/* Solving timeline for recommended problem */}
              {recommendedProblem && recommendedProblem.rating && (
                <SolvingTimeline
                  problemId={recommendedProblem.problem_id}
                  problemRating={recommendedProblem.rating}
                  userElo={recommendedProblem.melo}
                  startTime={sessionStartTime}
                />
              )}
            </>
          )}

          {/* ---- LIST MODE content ---- */}
          {detailMode === "list" && (
            <>
              {/* Difficulty range slider */}
              <div className="rounded-lg border border-border bg-card p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <Filter className="size-3.5 text-muted-foreground" />
                    <span className="text-xs font-medium text-muted-foreground">
                      {t("training:difficultyFilter")}
                    </span>
                  </div>
                  <span className="text-xs font-semibold tabular-nums text-foreground">
                    {t("training:difficultySlider.range", {
                      min: sliderRange[0],
                      max: sliderRange[1],
                    })}
                  </span>
                </div>
                <Slider
                  value={sliderRange}
                  onValueChange={(v) => {
                    const range = v as [number, number];
                    setSliderRange(range);
                    setFilterMinRating(String(range[0]));
                    setFilterMaxRating(String(range[1]));
                  }}
                  onValueCommitted={(v) => {
                    const range = v as [number, number];
                    // Trigger refresh on drag end with explicit filter values
                    setCuratedOffset(0);
                    setCuratedProblems([]);
                    setTimeout(() => fetchCuratedProblems(false, { min: range[0], max: range[1] }), 0);
                  }}
                  min={Math.max(800, (topic?.melo ?? 1200) - 200)}
                  max={(topic?.melo ?? 1200) + 400}
                  step={50}
                  aria-label={t("training:difficultyFilter")}
                />
              </div>

              {/* Problem list */}
              <div className="rounded-xl border border-border bg-card">
                <div className="border-b border-border px-4 py-2.5">
                  <h2 className="text-sm font-semibold text-foreground">
                    {t("training:problems", { count: curatedTotal })}
                  </h2>
                </div>
                {curatedLoading && curatedProblems.length === 0 ? (
                  <div className="px-4 py-6 text-center">
                    <Loader2 className="mx-auto size-5 animate-spin text-muted-foreground" />
                  </div>
                ) : curatedProblems.length === 0 ? (
                  <div className="px-4 py-6 text-center text-xs text-muted-foreground">
                    {t("training:noProblems")}
                  </div>
                ) : (
                  <div className="divide-y divide-border max-h-[45vh] overflow-y-auto">
                    {curatedProblems.map((problem) => {
                      const isSelected = selectedProblemId === problem.problem_id;
                      return (
                        <div
                          key={problem.problem_id}
                          className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer transition-colors ${
                            isSelected
                              ? "bg-primary/5"
                              : "hover:bg-muted/30"
                          }`}
                          onClick={() => handleProblemSwitch(problem.problem_id)}
                        >
                          {problem.solved ? (
                            <CheckCircle2 className="size-3.5 shrink-0 text-green-400" />
                          ) : (
                            <Circle className="size-3.5 shrink-0 text-muted-foreground" />
                          )}
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium text-foreground">
                              {problem.contest_id}
                              {problem.index} - {stripIndexPrefix(problem.name)}
                            </p>
                          </div>
                          {problem.rating && (
                            <span
                              className="shrink-0 text-xs font-bold"
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
                            onClick={(e) => e.stopPropagation()}
                          >
                            <ExternalLink className="size-3.5" />
                          </a>
                        </div>
                      );
                    })}
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

              {/* Solving timeline for selected problem in list mode */}
              {selectedProblem && selectedProblem.rating && (
                <SolvingTimeline
                  problemId={selectedProblem.problem_id}
                  problemRating={selectedProblem.rating}
                  userElo={selectedProblem.rating}
                  startTime={sessionStartTime}
                />
              )}
            </>
          )}

          {/* Abandon training button */}
          <Button
            variant="destructive"
            className="w-full"
            onClick={abandonSession}
            disabled={loading || !session}
          >
            <StopCircle className="mr-1.5 size-3.5" />
            {t("training:endSession")}
          </Button>
        </div>
      </div>
    </div>
  );
}
