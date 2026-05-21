/** Free Play Session page.
 *
 * Displayed during an active free play session.
 * Layout: main area (ProblemViewer external link) + side panel (info + timer + auto-tracking + quit).
 *
 * Auto-tracking: polls /submission-tracking/status every 5 seconds to detect
 * when the user submits on Codeforces. When a result is detected, it
 * transitions to the result view.
 *
 * After settlement (auto or quit) the result stats are displayed inline.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Loader2,
  Clock,
  X,
  Trophy,
  XCircle,
  Zap,
  RotateCcw,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { ProblemViewer } from "@/components/ProblemViewer";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { EloChange, CoinAnimation, AcceptedCelebration, AchievementPopup } from "@/components/animations";
import { SolvingTimeline } from "@/components/SolvingTimeline";
import { useAuthStore } from "@/stores/auth";
import { formatTime, getRatingColor } from "@/utils";
import * as freePlayApi from "@/services/freePlayApi";
import api from "@/services/api";
import type {
  FreePlayProblemInfo,
  FreePlaySubmitResponse,
  FreePlayQuitResponse,
} from "@/types";

// ---------------------------------------------------------------------------
// Hook: elapsed seconds counter
// ---------------------------------------------------------------------------

function useElapsedTime(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  const ref = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (running) {
      setElapsed(0);
      ref.current = setInterval(() => setElapsed((p) => p + 1), 1000);
    }
    return () => {
      if (ref.current) clearInterval(ref.current);
    };
  }, [running]);

  return elapsed;
}

// ---------------------------------------------------------------------------
// Session phase
// ---------------------------------------------------------------------------

type SessionPhase = "loading" | "active" | "result";

// ---------------------------------------------------------------------------
// Result view
// ---------------------------------------------------------------------------

function ResultView({
  submitResult,
  quitResult,
  problem,
  onNewSession,
}: {
  submitResult: FreePlaySubmitResponse | null;
  quitResult: FreePlayQuitResponse | null;
  problem: FreePlayProblemInfo;
  onNewSession: () => void;
}) {
  const navigate = useNavigate();
  const { t } = useTranslation(["free_play", "common"]);
  const [eloTriggerKey] = useState(() => Date.now());
  const [showCelebration, setShowCelebration] = useState(false);
  const [showAchievements, setShowAchievements] = useState(false);

  const isQuit = quitResult != null;
  const isSolved = submitResult?.solved === true;

  const eloChange = submitResult?.elo_change ?? quitResult?.elo_change;
  const ppChange = submitResult?.pp_change;
  const tokensEarned = submitResult?.tokens_earned ?? 0;
  const overkillMultiplier = submitResult?.overkill_multiplier ?? 1.0;
  const isOverkill = overkillMultiplier > 1.0;
  const achievements = submitResult?.achievements ?? [];

  useEffect(() => {
    if (eloChange != null && eloChange > 0) {
      setShowCelebration(true);
    }
  }, [eloChange]);

  useEffect(() => {
    if (achievements.length > 0) {
      const timer = setTimeout(() => setShowAchievements(true), 1500);
      return () => clearTimeout(timer);
    }
  }, [achievements]);

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <AcceptedCelebration
        active={showCelebration}
        onComplete={() => setShowCelebration(false)}
      />

      {achievements.length > 0 && showAchievements && (
        <AchievementPopup
          achievements={achievements}
          onComplete={() => setShowAchievements(false)}
        />
      )}

      {/* Header */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="text-center">
        <div
          className={`mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl ${
            isQuit ? "bg-red-500/10" : isSolved ? "bg-green-500/10" : "bg-red-500/10"
          }`}
        >
          {isSolved ? (
            <Trophy className="size-8 text-green-400" />
          ) : isQuit ? (
            <X className="size-8 text-red-400" />
          ) : (
            <XCircle className="size-8 text-red-400" />
          )}
        </div>
        <h1 className="text-2xl font-bold text-foreground">
          {isQuit
            ? t("free_play:session.abandoned")
            : isSolved
              ? t("free_play:session.completed")
              : t("free_play:session.notSolved")}
        </h1>

        {eloChange != null && (
          <div className="mt-2">
            <EloChange value={eloChange} triggerKey={eloTriggerKey} />
          </div>
        )}
      </motion.div>

      {/* Problem card */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.2 }}
        className="rounded-xl border-2 border-border bg-card p-5"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-foreground">{problem.name}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {problem.contest_id}
              {problem.index}
            </p>
          </div>
          {problem.rating != null && (
            <span
              className="shrink-0 rounded-lg px-3 py-1 text-sm font-bold"
              style={{
                color: getRatingColor(problem.rating),
                backgroundColor: `${getRatingColor(problem.rating)}20`,
              }}
            >
              {problem.rating}
            </span>
          )}
        </div>
        {problem.tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {problem.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        )}
      </motion.div>

      {/* Stats grid */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="grid grid-cols-3 gap-3"
      >
        <div className="rounded-xl border border-border bg-card p-4 text-center">
          <p className="text-xs text-muted-foreground">{t("free_play:result.eloChange")}</p>
          <p
            className={`mt-1 text-lg font-bold ${
              eloChange == null
                ? "text-muted-foreground"
                : eloChange > 0
                  ? "text-green-400"
                  : eloChange < 0
                    ? "text-red-400"
                    : "text-muted-foreground"
            }`}
          >
            {eloChange != null ? (eloChange > 0 ? "+" : "") + eloChange : "-"}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4 text-center">
          <p className="text-xs text-muted-foreground">{t("free_play:result.ppChange")}</p>
          <p
            className={`mt-1 text-lg font-bold ${
              ppChange == null
                ? "text-muted-foreground"
                : ppChange > 0
                  ? "text-blue-400"
                  : ppChange < 0
                    ? "text-red-400"
                    : "text-muted-foreground"
            }`}
          >
            {ppChange != null ? (ppChange > 0 ? "+" : "") + ppChange.toFixed(1) : "-"}
          </p>
        </div>
        <div className="rounded-xl border border-border bg-card p-4 text-center">
          <p className="text-xs text-muted-foreground">{t("free_play:result.tokensEarned")}</p>
          <div className="mt-1">
            <CoinAnimation amount={tokensEarned} triggerKey={eloTriggerKey} className="justify-center" />
            {tokensEarned === 0 && <span className="text-lg font-bold text-muted-foreground">0</span>}
          </div>
        </div>
      </motion.div>

      {/* Overkill bonus */}
      <AnimatePresence>
        {isOverkill && (
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ delay: 0.6, type: "spring", stiffness: 300, damping: 25 }}
            className="rounded-xl border-2 border-yellow-500/40 bg-gradient-to-r from-yellow-500/10 via-amber-500/10 to-yellow-500/10 p-4"
          >
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-lg bg-yellow-500/20">
                <Zap className="size-5 text-yellow-400" />
              </div>
              <div>
                <h4 className="font-bold text-yellow-300">
                  {t("free_play:result.overkillBonus")}
                </h4>
                <p className="text-sm text-yellow-400/80">
                  {t("free_play:result.overkillDesc", { multiplier: overkillMultiplier.toFixed(2) })}
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Actions */}
      <div className="flex justify-center gap-3">
        <Button onClick={onNewSession}>
          <RotateCcw className="mr-2 size-4" />
          {t("free_play:result.newSession")}
        </Button>
        <Button variant="outline" onClick={() => navigate("/dashboard")}>
          {t("free_play:result.backToDashboard")}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function FreePlaySessionPage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation(["free_play", "common"]);
  const user = useAuthStore((s) => s.user);

  const [phase, setPhase] = useState<SessionPhase>("loading");
  const [problem, setProblem] = useState<FreePlayProblemInfo | null>(null);
  const [error, setError] = useState("");

  // Result data
  const [submitResult, setSubmitResult] = useState<FreePlaySubmitResponse | null>(null);
  const [quitResult, setQuitResult] = useState<FreePlayQuitResponse | null>(null);

  // Quit button loading state
  const [quitting, setQuitting] = useState(false);

  // Timer
  const elapsed = useElapsedTime(phase === "active");

  // Auto-tracking poll
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Solving timeline start time
  const startTimeRef = useRef<Date>(new Date());

  // Load session on mount
  useEffect(() => {
    if (!sessionId) {
      setError("No session ID");
      setPhase("active"); // allow user to navigate away
      return;
    }

    const state = location.state as {
      problem?: FreePlayProblemInfo;
    } | undefined;

    if (state?.problem) {
      setProblem(state.problem);
      setPhase("active");
    } else {
      // No problem info in navigation state (refresh / direct URL).
      // Try to recover from backend.
      freePlayApi.freePlayGetActive().then((active) => {
        if (active?.problem) {
          setProblem(active.problem);
          setPhase("active");
        } else {
          navigate("/free-play", { replace: true });
        }
      }).catch(() => {
        navigate("/free-play", { replace: true });
      });
    }
  }, [sessionId, navigate, location.state]);

  // Auto-tracking polling
  useEffect(() => {
    if (!sessionId || phase !== "active") return;

    const pollTracking = async () => {
      try {
        const res = await api.get(
          `/submission-tracking/status?session_type=free_play&session_id=${sessionId}`,
        );
        const tracking = res.data?.data;
        if (tracking && (tracking.status === "matched" || tracking.status === "settled")) {
          if (pollRef.current) clearInterval(pollRef.current);
          // Auto-submit using the tracking data
          try {
            const result = await freePlayApi.freePlaySubmit(sessionId, {
              solved: tracking.status === "settled" || tracking.verdict === "OK",
              time_spent: elapsed,
              attempts: tracking.attempts ?? 1,
              error_count: tracking.error_count ?? 0,
            });
            setSubmitResult(result);
            setPhase("result");
          } catch {
            // If auto-submit fails, just show the result as-is
            setPhase("result");
          }
        }
      } catch {
        // Continue polling on error
      }
    };

    pollRef.current = setInterval(pollTracking, 5000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [sessionId, phase, elapsed]);

  // ---- Quit ----
  const handleQuit = useCallback(async () => {
    if (!sessionId) return;
    setQuitting(true);
    try {
      const result = await freePlayApi.freePlayQuit(sessionId);
      setQuitResult(result);
      setPhase("result");
    } catch {
      setError(t("free_play:error.quitFailed"));
    } finally {
      setQuitting(false);
    }
  }, [sessionId, t]);

  // ---- New session ----
  const handleNewSession = useCallback(() => {
    navigate("/free-play");
  }, [navigate]);

  // ---- Render ----

  if (phase === "loading") {
    return <LoadingSpinner text={t("common:loading", { defaultValue: "Loading..." })} className="py-20" />;
  }

  if (phase === "result") {
    if (!problem) {
      return (
        <div className="mx-auto max-w-2xl text-center">
          <p className="text-sm text-muted-foreground">{t("common:back", { defaultValue: "Back" })}</p>
          <Button variant="outline" className="mt-4" onClick={handleNewSession}>
            {t("free_play:result.newSession")}
          </Button>
        </div>
      );
    }
    return (
      <ResultView
        submitResult={submitResult}
        quitResult={quitResult}
        problem={problem}
        onNewSession={handleNewSession}
      />
    );
  }

  // phase === "active"
  if (!problem) {
    return (
      <div className="mx-auto max-w-2xl text-center">
        <p className="text-sm text-muted-foreground">No problem data.</p>
        <Button variant="outline" className="mt-4" onClick={handleNewSession}>
          {t("free_play:result.backToDashboard")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:gap-6">
      {/* Main area: ProblemViewer */}
      <div className="flex-1 min-w-0">
        <ProblemViewer
          contestId={problem.contest_id}
          index={problem.index}
          blindBox={false}
        />
      </div>

      {/* Side panel */}
      <div className="w-full shrink-0 space-y-4 lg:w-72">
        {/* Problem info */}
        <div className="rounded-xl border border-border bg-card p-4 space-y-3">
          <h3 className="text-sm font-semibold text-foreground">{t("free_play:problemInfo")}</h3>
          <div>
            <p className="text-sm font-medium text-foreground">{problem.name}</p>
            <p className="text-xs text-muted-foreground">
              {problem.contest_id}
              {problem.index}
            </p>
          </div>
          {problem.rating != null && (
            <span
              className="inline-block rounded-lg px-3 py-1 text-sm font-bold"
              style={{
                color: getRatingColor(problem.rating),
                backgroundColor: `${getRatingColor(problem.rating)}20`,
              }}
            >
              {problem.rating}
            </span>
          )}
          {problem.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {problem.tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Timer */}
        <div className="rounded-xl border border-border bg-card p-4">
          <div className="flex items-center gap-2">
            <Clock className="size-4 text-muted-foreground" />
            <span className="font-mono text-lg font-bold text-foreground">
              {formatTime(elapsed)}
            </span>
          </div>
        </div>

        {/* Auto-tracking status */}
        <div className="rounded-xl border border-primary/30 bg-card p-4 space-y-3">
          <div className="flex items-center gap-3">
            <Loader2 className="size-5 animate-spin text-primary" />
            <div>
              <h4 className="text-sm font-semibold text-foreground">
                {t("free_play:session.autoTracking")}
              </h4>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {t("free_play:session.autoTrackingDesc")}
              </p>
            </div>
          </div>
        </div>

        {/* Solving Timeline */}
        {problem && problem.rating != null && user?.elo != null && (
          <SolvingTimeline
            problemId={`${problem.contest_id}${problem.index}`}
            problemRating={problem.rating}
            userElo={user.elo}
            startTime={startTimeRef.current}
          />
        )}

        {/* Error */}
        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Quit button */}
        <Button variant="destructive" className="w-full" onClick={handleQuit} disabled={quitting}>
          {quitting ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" />
              {t("free_play:session.quitting")}
            </>
          ) : (
            <>
              <X className="mr-2 size-4" />
              {t("free_play:session.quit")}
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
