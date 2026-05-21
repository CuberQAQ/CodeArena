import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Swords, Loader2, Clock, Trophy, ExternalLink, X, CheckCircle2, XCircle, Sparkles, Coins } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { MatchWaiting } from "@/components/animations/MatchWaiting";
import { EloChange } from "@/components/animations/EloChange";
import { AcceptedCelebration } from "@/components/animations/AcceptedCelebration";
import { AchievementPopup } from "@/components/animations";
import { SolvingTimeline } from "@/components/SolvingTimeline";
import { ProblemViewer } from "@/components/ProblemViewer";
import { useAuthStore } from "@/stores/auth";
import { extractApiError, formatTime, getRatingColor } from "@/utils";
import api from "@/services/api";
import type {
  ApiResponse,
  AchievementEvent,
  ActiveChallengeInfo,
  QueueStatus,
  StartChallengeResponse,
  ChallengeDetail,
  SubmitResultResponse,
  QuitChallengeResponse,
} from "@/types";

type Phase = "idle" | "queuing" | "matched" | "waiting" | "in_progress" | "result";

export default function ChallengePage() {
  const navigate = useNavigate();
  const { sessionId: urlSessionId } = useParams<{ sessionId?: string }>();
  const { t } = useTranslation("challenge");
  const user = useAuthStore((s) => s.user);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string>("");
  const [challenge, setChallenge] = useState<ChallengeDetail | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const trackingPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasResumedRef = useRef(false);
  const [solved, setSolved] = useState(false);
  const [attempts, setAttempts] = useState(0);
  const [quitSubmissions, setQuitSubmissions] = useState(0);
  const [showCelebration, setShowCelebration] = useState(false);
  const [eloTriggerKey, setEloTriggerKey] = useState(0);
  const [achievements, setAchievements] = useState<AchievementEvent[]>([]);
  const [showAchievements, setShowAchievements] = useState(false);
  const [hasSubmitted, setHasSubmitted] = useState(false);
  const submitPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Track when the in-progress phase started for the solving timeline
  const challengeStartRef = useRef<Date>(new Date());

  // Resume logic on mount
  useEffect(() => {
    if (hasResumedRef.current) return;
    hasResumedRef.current = true;

    const resumeChallenge = async (sid: string) => {
      try {
        const res = await api.get<ApiResponse<ChallengeDetail>>(`/challenge/${sid}`);
        const data = res.data.data;

        if (data.status === "completed" || data.result) {
          // Already completed -- show result
          setSessionId(sid);
          setChallenge(data);
          setEloTriggerKey((k) => k + 1);
          setPhase("result");
          return;
        }

        if (data.status === "active") {
          // Active session -- resume
          setSessionId(sid);
          setChallenge(data);

          // Recover elapsed time from created_at
          if (data.created_at) {
            const elapsedSec = Math.floor((Date.now() - new Date(data.created_at).getTime()) / 1000);
            setElapsed(Math.max(0, elapsedSec));
            challengeStartRef.current = new Date(data.created_at);
          }

          setPhase("in_progress");

          // Update URL to include sessionId for bookmarkability
          if (!urlSessionId) {
            navigate(`/challenge/${sid}`, { replace: true });
          }

          // Start timer from recovered elapsed
          if (timerRef.current) clearInterval(timerRef.current);
          timerRef.current = setInterval(() => {
            setElapsed((prev) => prev + 1);
          }, 1000);
        }
      } catch {
        // Session not found or error -- stay idle
      }
    };

    if (urlSessionId) {
      // Direct URL with session ID -- load that session
      resumeChallenge(urlSessionId);
    } else {
      // No session ID in URL -- check for active or recently completed challenge
      api
        .get<ApiResponse<ActiveChallengeInfo | null>>("/challenge/active")
        .then((res) => {
          const active = res.data.data as ActiveChallengeInfo | null;
          if (active && (active.status === "active" || active.status === "completed")) {
            resumeChallenge(active.id);
          }
        })
        .catch(() => {});
    }
  }, [urlSessionId]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
      if (trackingPollRef.current) clearInterval(trackingPollRef.current);
      if (submitPollRef.current) clearInterval(submitPollRef.current);
    };
  }, []);

  // Start polling queue status
  const startPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const res = await api.get<ApiResponse<QueueStatus>>("/challenge/status");
        const status = res.data.data;
        if (status.matched && status.session_id) {
          if (pollRef.current) clearInterval(pollRef.current);
          setSessionId(status.session_id);
          navigate(`/challenge/${status.session_id}`, { replace: true });
          setPhase("matched");
        }
      } catch {
        // Continue polling on transient errors
      }
    }, 2000);
  }, [navigate]);

  // Poll submission tracking status during active challenge
  useEffect(() => {
    if (!sessionId || phase !== "in_progress") return;

    const pollTracking = async () => {
      try {
        const res = await api.get(
          `/submission-tracking/status?session_type=pvp&session_id=${sessionId}`,
        );
        const tracking = res.data?.data;
        if (tracking && tracking.status === "timeout") {
          if (trackingPollRef.current) clearInterval(trackingPollRef.current);
          setError(t("challenge:trackingTimedOut"));
          return;
        }
        if (tracking && (tracking.status === "matched" || tracking.status === "settled")) {
          if (trackingPollRef.current) clearInterval(trackingPollRef.current);
          // Fetch updated challenge details and transition to result
          const detailRes = await api.get<ApiResponse<ChallengeDetail>>(
            `/challenge/${sessionId}`,
          );
          const detail = detailRes.data.data;
          if (detail.status === "completed" || detail.result) {
            setChallenge(detail);
            setEloTriggerKey((k) => k + 1);
            if (timerRef.current) clearInterval(timerRef.current);
            if (submitPollRef.current) clearInterval(submitPollRef.current);
            setPhase("result");
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
  }, [sessionId, phase]);

  // Timer for in-progress phase
  const startTimer = useCallback(() => {
    setElapsed(0);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
  }, []);

  // Poll for opponent confirmation when waiting
  useEffect(() => {
    if (phase !== "waiting" || !sessionId) return;

    const pollWaiting = async () => {
      try {
        const res = await api.get<ApiResponse<ChallengeDetail>>(`/challenge/${sessionId}`);
        const data = res.data.data;
        if (data.status === "active" && data.problem) {
          setChallenge(data);
          setPhase("in_progress");
          challengeStartRef.current = new Date();
          startTimer();
          return true; // done
        }
        if (data.status === "completed" || data.result) {
          setChallenge(data);
          setEloTriggerKey((k) => k + 1);
          setPhase("result");
          return true; // done
        }
        return false; // continue polling
      } catch {
        return false; // continue polling on transient errors
      }
    };

    const interval = setInterval(async () => {
      const done = await pollWaiting();
      if (done) clearInterval(interval);
    }, 3000);

    // Also poll immediately so we don't wait 3s for the first check
    pollWaiting();

    return () => clearInterval(interval);
  }, [phase, sessionId, startTimer]);

  // Poll for opponent quit or session completion during in_progress phase
  useEffect(() => {
    if (phase !== "in_progress" || !sessionId) return;

    const interval = setInterval(async () => {
      try {
        const res = await api.get<ApiResponse<ChallengeDetail>>(`/challenge/${sessionId}`);
        const data = res.data.data;
        if (data.status === "completed" || data.result) {
          setChallenge(data);
          setEloTriggerKey((k) => k + 1);
          if (timerRef.current) clearInterval(timerRef.current);
          if (trackingPollRef.current) clearInterval(trackingPollRef.current);
          if (submitPollRef.current) clearInterval(submitPollRef.current);
          setPhase("result");
          clearInterval(interval);
        }
      } catch {
        // Continue polling on transient errors
      }
    }, 3000);

    return () => clearInterval(interval);
  }, [phase, sessionId]);

  // Join queue
  const handleJoinQueue = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await api.post<ApiResponse<QueueStatus>>("/challenge/queue");
      const status = res.data.data;
      if (status.matched && status.session_id) {
        setSessionId(status.session_id);
        navigate(`/challenge/${status.session_id}`, { replace: true });
        setPhase("matched");
      } else {
        setPhase("queuing");
        startPolling();
      }
    } catch (err) {
      setError(extractApiError(err, t("failedJoinQueue")));
    } finally {
      setLoading(false);
    }
  };

  // Leave queue
  const handleLeaveQueue = async () => {
    try {
      await api.delete("/challenge/queue");
    } catch {
      // Ignore errors when leaving queue
    }
    if (pollRef.current) clearInterval(pollRef.current);
    setPhase("idle");
  };

  // Start challenge (confirm ready)
  const handleStartChallenge = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await api.post<ApiResponse<StartChallengeResponse>>(
        `/challenge/start`,
        { session_id: sessionId },
      );
      const data = res.data.data;
      if (!data.session_id || data.status === "no_match") {
        setError("Match no longer available. Please try again.");
        setPhase("idle");
        return;
      }
      if (data.status === "waiting_opponent") {
        setSessionId(data.session_id);
        setPhase("waiting");
        return;
      }
      setSessionId(data.session_id);
      setPhase("in_progress");
      challengeStartRef.current = new Date();
      startTimer();
      // Fetch full details
      const detailRes = await api.get<ApiResponse<ChallengeDetail>>(
        `/challenge/${data.session_id}`,
      );
      setChallenge(detailRes.data.data);
    } catch (err) {
      setError(extractApiError(err, t("failedStartChallenge")));
    } finally {
      setLoading(false);
    }
  };

  // Submit result
  const handleSubmit = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await api.post<ApiResponse<SubmitResultResponse>>(
        `/challenge/${sessionId}/submit`,
        { solved, time_spent: elapsed, attempts },
      );
      const data = res.data.data;
      if (data.settled) {
        if (timerRef.current) clearInterval(timerRef.current);
        if (trackingPollRef.current) clearInterval(trackingPollRef.current);
        // Fetch details -- settlement may still be processing in background
        const detailRes = await api.get<ApiResponse<ChallengeDetail>>(
          `/challenge/${sessionId}`,
        );
        const detail = detailRes.data.data;
        setChallenge(detail);
        setEloTriggerKey((k) => k + 1);
        if (data.elo_change != null && data.elo_change > 0 && data.result === "win") {
          setShowCelebration(true);
        }
        if (data.achievements && data.achievements.length > 0) {
          setAchievements(data.achievements);
          setTimeout(() => setShowAchievements(true), 1500);
        }
        setPhase("result");
        // If background settlement not yet complete, poll until it is
        if (detail.status !== "completed") {
          if (submitPollRef.current) clearInterval(submitPollRef.current);
          submitPollRef.current = setInterval(async () => {
            try {
              const pollRes = await api.get<ApiResponse<ChallengeDetail>>(
                `/challenge/${sessionId}`,
              );
              const pollDetail = pollRes.data.data;
              if (pollDetail.status === "completed") {
                if (submitPollRef.current) clearInterval(submitPollRef.current);
                setChallenge(pollDetail);
                setEloTriggerKey((k) => k + 1);
                if (pollDetail.elo_change != null && pollDetail.elo_change > 0) {
                  setShowCelebration(true);
                }
              }
            } catch {
              // Continue polling
            }
          }, 1500);
        }
      } else {
        // Waiting for opponent -- stay in in_progress, show waiting state
        setHasSubmitted(true);
        if (timerRef.current) clearInterval(timerRef.current);
        if (trackingPollRef.current) clearInterval(trackingPollRef.current);
        // Poll for final result
        if (submitPollRef.current) clearInterval(submitPollRef.current);
        submitPollRef.current = setInterval(async () => {
          try {
            const detailRes = await api.get<ApiResponse<ChallengeDetail>>(
              `/challenge/${sessionId}`,
            );
            const detail = detailRes.data.data;
            if (detail.status === "completed" || detail.result) {
              if (submitPollRef.current) clearInterval(submitPollRef.current);
              setChallenge(detail);
              setEloTriggerKey((k) => k + 1);
              if (detail.elo_change != null && detail.elo_change > 0) {
                setShowCelebration(true);
              }
              setPhase("result");
            }
          } catch {
            // Continue polling
          }
        }, 3000);
      }
    } catch (err) {
      setError(extractApiError(err, t("failedSubmit")));
    } finally {
      setLoading(false);
    }
  };

  // Quit challenge
  const handleQuit = async () => {
    setError("");
    setLoading(true);
    try {
      await api.post<ApiResponse<QuitChallengeResponse>>(
        `/challenge/${sessionId}/quit`,
        { submissions: quitSubmissions },
      );
      if (timerRef.current) clearInterval(timerRef.current);
      if (trackingPollRef.current) clearInterval(trackingPollRef.current);
      if (submitPollRef.current) clearInterval(submitPollRef.current);
      const detailRes = await api.get<ApiResponse<ChallengeDetail>>(
        `/challenge/${sessionId}`,
      );
      setChallenge(detailRes.data.data);
      setEloTriggerKey((k) => k + 1);
      setPhase("result");
    } catch (err) {
      setError(extractApiError(err, t("failedQuit")));
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setPhase("idle");
    setSessionId("");
    setChallenge(null);
    setElapsed(0);
    setError("");
    setSolved(false);
    setAttempts(0);
    setQuitSubmissions(0);
    setShowCelebration(false);
    setAchievements([]);
    setShowAchievements(false);
    setHasSubmitted(false);
    if (trackingPollRef.current) {
      clearInterval(trackingPollRef.current);
      trackingPollRef.current = null;
    }
    if (submitPollRef.current) {
      clearInterval(submitPollRef.current);
      submitPollRef.current = null;
    }
    // Navigate to /challenge (no session ID) so URL is clean
    if (urlSessionId) {
      navigate("/challenge", { replace: true });
    }
  };

  // -- IDLE --
  if (phase === "idle") {
    return (
      <div className="mx-auto max-w-2xl">
        <div className="text-center">
          <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl bg-primary/10">
            <Swords className="size-8 text-primary" />
          </div>
          <h1 className="text-2xl font-bold text-foreground">{t("randomChallenge")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {t("randomChallengeDesc")}
          </p>
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="mt-8 flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
          <Button size="lg" onClick={handleJoinQueue} disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                {t("joining")}
              </>
            ) : (
              <>
                <Swords className="mr-2 size-4" />
                {t("findOpponent")}
              </>
            )}
          </Button>
          <Button
            size="lg"
            variant="outline"
            onClick={() => navigate("/pve-challenge")}
            disabled={loading}
          >
            <Sparkles className="mr-2 size-4 text-purple-400" />
            {t("soloChallenge")}
          </Button>
        </div>

        <div className="mt-8 rounded-xl border border-border bg-card p-5">
          <h3 className="text-sm font-semibold text-foreground">{t("howItWorks")}</h3>
          <ol className="mt-3 space-y-2 text-sm text-muted-foreground">
            <li>{t("step1")}</li>
            <li>{t("step2")}</li>
            <li>{t("step3")}</li>
            <li>{t("step4")}</li>
            <li>{t("step5")}</li>
          </ol>
        </div>
      </div>
    );
  }

  // -- QUEUING --
  if (phase === "queuing") {
    return (
      <div className="mx-auto max-w-2xl text-center">
        <MatchWaiting className="mb-6" />
        <h1 className="text-2xl font-bold text-foreground">{t("findingOpponent")}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {t("findingOpponentDesc")}
        </p>
        <Button variant="outline" className="mt-8" onClick={handleLeaveQueue}>
          <X className="mr-2 size-4" />
          {t("common:cancel", { ns: "common" })}
        </Button>
      </div>
    );
  }

  // -- MATCHED --
  if (phase === "matched") {
    return (
      <div className="mx-auto max-w-2xl text-center">
        <div className="mx-auto mb-6 flex size-20 items-center justify-center rounded-full bg-green-500/10">
          <Trophy className="size-10 text-green-400" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">{t("opponentFound")}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {t("opponentFoundDesc")}
        </p>

        {error && (
          <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="mt-6 flex justify-center">
          <Button size="lg" onClick={handleStartChallenge} disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                {t("starting")}
              </>
            ) : (
              t("startChallenge")
            )}
          </Button>
        </div>
      </div>
    );
  }

  // -- WAITING (for opponent confirmation) --
  if (phase === "waiting") {
    return (
      <div className="mx-auto max-w-2xl text-center">
        <div className="mx-auto mb-6 flex size-20 items-center justify-center rounded-full bg-primary/10">
          <Loader2 className="size-10 animate-spin text-primary" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">{t("waitingForOpponent")}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {t("waitingForOpponentDesc")}
        </p>
        <Button variant="outline" className="mt-8" onClick={handleReset}>
          <X className="mr-2 size-4" />
          {t("common:cancel", { ns: "common" })}
        </Button>
      </div>
    );
  }

  // -- IN PROGRESS --
  if (phase === "in_progress") {
    const problem = challenge?.problem;
    return (
      <div className="flex flex-col gap-4 lg:flex-row lg:gap-6">
        {/* Main area */}
        <div className="flex-1 min-w-0 space-y-5">
          {/* Timer bar */}
          <div className="flex items-center justify-between rounded-xl border border-border bg-card px-5 py-3">
            <div className="flex items-center gap-2">
              <Clock className="size-4 text-muted-foreground" />
              <span className="font-mono text-lg font-bold text-foreground">
                {formatTime(elapsed)}
              </span>
            </div>
            <span className="text-sm font-medium text-muted-foreground">{t("challengeInProgress")}</span>
          </div>

          {error && (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {/* Problem statement (in-app viewer) */}
          {problem && (
            <ProblemViewer
              contestId={problem.contest_id}
              index={problem.index}
              blindBox={false}
            />
          )}

          {/* Submit result area: auto-tracking + manual submit */}
          {hasSubmitted ? (
            // Player has manually submitted, waiting for opponent
            <div className="rounded-xl border border-border bg-card p-5 text-center space-y-3">
              <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/10">
                <Loader2 className="size-6 animate-spin text-primary" />
              </div>
              <p className="text-sm font-medium text-foreground">{t("waitingForOpponentResult")}</p>
              {problem && (
                <Button
                  variant="outline"
                  onClick={() => window.open(problem.url, "_blank")}
                >
                  <ExternalLink className="mr-2 size-4" />
                  {t("openOnCodeforces")}
                </Button>
              )}
            </div>
          ) : (
            <>
              {/* Auto-tracking panel */}
              <div className="rounded-xl border border-primary/30 bg-card p-5 space-y-4">
                <div className="flex items-center gap-3">
                  <Loader2 className="size-5 animate-spin text-primary" />
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">{t("waitingForCFResult")}</h3>
                    <p className="text-xs text-muted-foreground mt-1">
                      {t("waitingForCFResultDesc")}
                    </p>
                  </div>
                </div>
              </div>

              {/* Manual submit panel */}
              <div className="rounded-xl border border-border bg-card p-5 space-y-4">
                <h3 className="text-sm font-semibold text-foreground">{t("reportYourResult")}</h3>

                <div className="flex items-center gap-3">
                  <label className="text-sm text-muted-foreground">{t("didYouSolve")}</label>
                  <Button
                    size="sm"
                    variant={solved ? "default" : "outline"}
                    onClick={() => setSolved(true)}
                  >
                    <CheckCircle2 className="mr-1.5 size-3.5" />
                    {t("common:yes", { ns: "common" })}
                  </Button>
                  <Button
                    size="sm"
                    variant={!solved ? "destructive" : "outline"}
                    onClick={() => setSolved(false)}
                  >
                    <XCircle className="mr-1.5 size-3.5" />
                    {t("common:no", { ns: "common" })}
                  </Button>
                </div>

                {solved && (
                  <div className="flex items-center gap-3">
                    <label className="text-sm text-muted-foreground">{t("common:attempts", { ns: "common" })}:</label>
                    <input
                      type="number"
                      min={1}
                      value={attempts || ""}
                      onChange={(e) => {
                        const v = parseInt(e.target.value);
                        setAttempts(isNaN(v) ? 0 : v);
                      }}
                      onBlur={() => {
                        if (!attempts || attempts < 1) setAttempts(1);
                      }}
                      className="w-20 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary focus:outline-none"
                    />
                  </div>
                )}

                <div className="flex gap-3">
                  <Button onClick={handleSubmit} disabled={loading}>
                    {loading ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
                    {t("submitResult")}
                  </Button>
                  <Button variant="destructive" onClick={handleQuit} disabled={loading}>
                    {loading ? <Loader2 className="mr-2 size-4 animate-spin" /> : <X className="mr-2 size-4" />}
                    {t("quit")}
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>

        {/* Side panel - Solving Timeline */}
        {problem && problem.rating != null && user?.elo != null && (
          <div className="w-full shrink-0 lg:w-72">
            <SolvingTimeline
              problemId={`${problem.contest_id}${problem.index}`}
              problemRating={problem.rating}
              userElo={user.elo}
              startTime={challengeStartRef.current}
            />
          </div>
        )}
      </div>
    );
  }

  // -- RESULT --
  if (phase === "result" && challenge) {
    // Settlement still processing in background
    if (!challenge.result) {
      return (
        <div className="mx-auto max-w-2xl text-center">
          <div className="mx-auto mb-6 flex size-20 items-center justify-center rounded-full bg-primary/10">
            <Loader2 className="size-10 animate-spin text-primary" />
          </div>
          <h1 className="text-2xl font-bold text-foreground">{t("settling")}</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {t("settlingDesc")}
          </p>
        </div>
      );
    }

    const isWin = challenge.result === "win";
    const isDraw = challenge.result === "draw";
    const isQuit = challenge.result === "quit" || challenge.status === "quit";

    return (
      <div className="mx-auto max-w-2xl space-y-5">
        <AcceptedCelebration
          active={showCelebration}
          onComplete={() => setShowCelebration(false)}
        />

        {/* Achievement popup overlay */}
        {achievements.length > 0 && showAchievements && (
          <AchievementPopup
            achievements={achievements}
            onComplete={() => setShowAchievements(false)}
          />
        )}

        <div className="text-center">
          <div
            className={`mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl ${
              isWin
                ? "bg-green-500/10"
                : isDraw
                  ? "bg-yellow-500/10"
                  : "bg-red-500/10"
            }`}
          >
            {isWin ? (
              <Trophy className="size-8 text-green-400" />
            ) : isQuit ? (
              <X className="size-8 text-red-400" />
            ) : (
              <Swords className="size-8 text-red-400" />
            )}
          </div>
          <h1 className="text-2xl font-bold text-foreground">
            {isWin ? t("victory") : isDraw ? t("draw") : isQuit ? t("challengeAbandoned") : t("defeat")}
          </h1>
          {challenge.elo_change != null && (
            <div className="mt-2">
              <EloChange value={challenge.elo_change} triggerKey={eloTriggerKey} />
            </div>
          )}
        </div>

        {/* Problem summary */}
        {challenge.problem && (
          <div className="rounded-xl border border-border bg-card p-5">
            <h3 className="text-sm font-semibold text-foreground">{t("problem")}</h3>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-sm text-foreground">{challenge.problem.name}</span>
              {challenge.problem.rating && (
                <span
                  className="text-sm font-bold"
                  style={{ color: getRatingColor(challenge.problem.rating) }}
                >
                  {challenge.problem.rating}
                </span>
              )}
            </div>
            <a
              href={challenge.problem.url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <ExternalLink className="size-3" />
              {t("viewOnCodeforces")}
            </a>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">{t("yourTime")}</p>
            <p className="mt-1 text-lg font-bold text-foreground">
              {(challenge.is_challenger ? challenge.challenger_time : challenge.opponent_time) != null
                ? formatTime(challenge.is_challenger ? challenge.challenger_time! : challenge.opponent_time!)
                : "-"}
            </p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">{t("submissions")}</p>
            <p className="mt-1 text-lg font-bold text-foreground">
              {challenge.is_challenger ? challenge.challenger_submissions : challenge.opponent_submissions}
            </p>
          </div>
        </div>

        {/* Tokens earned */}
        {challenge.tokens_earned != null && challenge.tokens_earned > 0 && (
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <div className="flex items-center justify-center gap-2">
              <Coins className="size-4 text-yellow-500" />
              <p className="text-xs text-muted-foreground">{t("tokensEarned")}</p>
            </div>
            <p className="mt-1 text-lg font-bold text-yellow-500">
              +{challenge.tokens_earned}
            </p>
          </div>
        )}

        <div className="flex justify-center gap-3">
          <Button onClick={handleReset}>{t("newChallenge")}</Button>
          <Button variant="outline" onClick={() => navigate("/dashboard")}>
            {t("backToDashboard")}
          </Button>
        </div>
      </div>
    );
  }

  // Fallback for result without challenge data
  return (
    <div className="mx-auto max-w-2xl text-center">
      <LoadingSpinner text={t("common:loadingResult", { ns: "common" })} className="py-20" />
      <Button variant="outline" className="mt-4" onClick={handleReset}>
        {t("common:back", { ns: "common" })}
      </Button>
    </div>
  );
}
