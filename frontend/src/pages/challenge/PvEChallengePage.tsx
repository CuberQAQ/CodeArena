/** PvE Challenge page.
 *
 * Three phases:
 *   1. idle         - Start button
 *   2. in_progress  - Blind-box problem display (rating/tags hidden), timer, submit/quit
 *   3. result       - Reveal rating/tags, show Elo/PP/token changes, overkill indicator
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  Loader2,
  Clock,
  ExternalLink,
  X,
  CheckCircle2,
  XCircle,
  Trophy,
  Sparkles,
  HelpCircle,
  RotateCcw,
  Zap,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { EloChange, CoinAnimation, AcceptedCelebration, AchievementPopup } from "@/components/animations";
import { usePvEChallengeStore } from "@/stores/pveChallengeStore";
import { formatTime, getRatingColor } from "@/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function useElapsedTime(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  const ref = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (running) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset timer when starting
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
// Idle phase - start button
// ---------------------------------------------------------------------------

function IdlePhase() {
  const startChallenge = usePvEChallengeStore((s) => s.startChallenge);
  const phase = usePvEChallengeStore((s) => s.phase);
  const error = usePvEChallengeStore((s) => s.error);
  const loading = phase === "loading";
  const { t } = useTranslation("challenge");

  return (
    <div className="mx-auto max-w-2xl">
      <div className="text-center">
        <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl bg-purple-500/10">
          <HelpCircle className="size-8 text-purple-400" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">{t("pve.title")}</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          {t("pve.description")}
        </p>
      </div>

      {error && (
        <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="mt-8 flex justify-center">
        <Button size="lg" onClick={startChallenge} disabled={loading}>
          {loading ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" />
              {t("pve.loadingProblem")}
            </>
          ) : (
            <>
              <Sparkles className="mr-2 size-4" />
              {t("pve.startSoloChallenge")}
            </>
          )}
        </Button>
      </div>

      <div className="mt-8 rounded-xl border border-border bg-card p-5">
        <h3 className="text-sm font-semibold text-foreground">{t("pve.howItWorks")}</h3>
        <ol className="mt-3 space-y-2 text-sm text-muted-foreground">
          <li>{t("pve.step1")}</li>
          <li>{t("pve.step2")}</li>
          <li>{t("pve.step3")}</li>
          <li>{t("pve.step4")}</li>
          <li>{t("pve.step5")}</li>
        </ol>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// In-progress phase - blind box + timer + submit
// ---------------------------------------------------------------------------

function InProgressPhase({ onNavigateBack }: { onNavigateBack: () => void }) {
  const startResponse = usePvEChallengeStore((s) => s.startResponse);
  const submitResultAction = usePvEChallengeStore((s) => s.submitResultAction);
  const quitChallengeAction = usePvEChallengeStore((s) => s.quitChallengeAction);
  const error = usePvEChallengeStore((s) => s.error);
  const phase = usePvEChallengeStore((s) => s.phase);
  const { t } = useTranslation(["challenge", "common"]);

  const elapsed = useElapsedTime(phase === "in_progress");
  const [solved, setSolved] = useState(false);
  const [attempts, setAttempts] = useState(1);
  const [errorCount, setErrorCount] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const problem = startResponse?.problem;

  const handleSubmit = async () => {
    setSubmitting(true);
    await submitResultAction(solved, elapsed, attempts, errorCount);
    setSubmitting(false);
  };

  const handleQuit = async () => {
    setSubmitting(true);
    await quitChallengeAction(attempts > 0 ? attempts - 1 : 0);
    setSubmitting(false);
  };

  if (!problem) {
    return (
      <div className="mx-auto max-w-2xl text-center">
        <LoadingSpinner text={t("common:loadingProblem")} className="py-20" />
        <Button variant="outline" className="mt-4" onClick={onNavigateBack}>
          {t("common:back")}
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      {/* Timer bar */}
      <div className="flex items-center justify-between rounded-xl border border-border bg-card px-5 py-3">
        <div className="flex items-center gap-2">
          <Clock className="size-4 text-muted-foreground" />
          <span className="font-mono text-lg font-bold text-foreground">
            {formatTime(elapsed)}
          </span>
        </div>
        <span className="flex items-center gap-1.5 text-sm font-medium text-purple-400">
          <HelpCircle className="size-4" />
          {t("challenge:pve.mysteryChallenge")}
        </span>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Problem card -- blind box */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-xl border-2 border-purple-500/30 bg-card p-5"
      >
        {/* Mystery shimmer overlay */}
        <div className="pointer-events-none absolute inset-0 bg-gradient-to-r from-purple-500/5 via-transparent to-purple-500/5" />

        <div className="relative space-y-3">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold text-foreground">{problem.name}</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {problem.contest_id}
                {problem.index}
              </p>
            </div>
            {/* Hidden rating */}
            <span className="shrink-0 rounded-lg bg-purple-500/20 px-3 py-1 text-sm font-bold text-purple-400">
              ???
            </span>
          </div>

          {/* Hidden tags */}
          <div className="flex flex-wrap gap-1.5">
            {[1, 2, 3].map((i) => (
              <span
                key={i}
                className="rounded-md bg-purple-500/10 px-2.5 py-0.5 text-xs font-medium text-purple-400"
              >
                ???
              </span>
            ))}
          </div>

          <Button
            variant="outline"
            className="mt-1"
            onClick={() => window.open(problem.url, "_blank")}
          >
            <ExternalLink className="mr-2 size-4" />
            {t("challenge:openOnCodeforces")}
          </Button>
        </div>
      </motion.div>

      {/* Submit result panel */}
      <div className="rounded-xl border border-border bg-card p-5 space-y-4">
        <h3 className="text-sm font-semibold text-foreground">{t("challenge:pve.reportYourResult")}</h3>

        <div className="flex items-center gap-3">
          <label className="text-sm text-muted-foreground">{t("challenge:pve.didYouSolve")}</label>
          <Button
            size="sm"
            variant={solved ? "default" : "outline"}
            onClick={() => setSolved(true)}
          >
            <CheckCircle2 className="mr-1.5 size-3.5" />
            {t("common:yes")}
          </Button>
          <Button
            size="sm"
            variant={!solved ? "destructive" : "outline"}
            onClick={() => setSolved(false)}
          >
            <XCircle className="mr-1.5 size-3.5" />
            {t("common:no")}
          </Button>
        </div>

        {solved && (
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <label className="text-sm text-muted-foreground">{t("common:attempts")}:</label>
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
            <div className="flex items-center gap-3">
              <label className="text-sm text-muted-foreground">{t("challenge:pve.errorsLabel")}</label>
              <input
                type="number"
                min={0}
                value={errorCount || ""}
                onChange={(e) => {
                  const v = parseInt(e.target.value);
                  setErrorCount(isNaN(v) ? 0 : v);
                }}
                onBlur={() => {
                  if (isNaN(errorCount) || errorCount < 0) setErrorCount(0);
                }}
                className="w-20 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary focus:outline-none"
              />
            </div>
          </div>
        )}

        <div className="flex gap-3">
          <Button onClick={handleSubmit} disabled={submitting}>
            {submitting ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
            {t("challenge:pve.submitResult")}
          </Button>
          <Button variant="destructive" onClick={handleQuit} disabled={submitting}>
            {submitting ? <Loader2 className="mr-2 size-4 animate-spin" /> : <X className="mr-2 size-4" />}
            {t("challenge:pve.quit")}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result phase - reveal + stats
// ---------------------------------------------------------------------------

function ResultPhase({ onReset }: { onReset: () => void }) {
  const navigate = useNavigate();
  const challenge = usePvEChallengeStore((s) => s.challenge);
  const startResponse = usePvEChallengeStore((s) => s.startResponse);
  const submitResult = usePvEChallengeStore((s) => s.submitResult);
  const quitResult = usePvEChallengeStore((s) => s.quitResult);
  const { t } = useTranslation(["challenge", "common"]);
  const [eloTriggerKey] = useState(() => Date.now());
  const [showCelebration, setShowCelebration] = useState(false);
  const [showAchievements, setShowAchievements] = useState(false);

  // Show celebration for positive Elo
  useEffect(() => {
    const eloChange = submitResult?.elo_change ?? quitResult?.elo_change;
    if (eloChange != null && eloChange > 0) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- trigger celebration on positive elo
      setShowCelebration(true);
    }
  }, [submitResult?.elo_change, quitResult?.elo_change]);

  // Show achievement popup when achievements are present
  useEffect(() => {
    if (submitResult?.achievements && submitResult.achievements.length > 0) {
      // Delay slightly so the celebration plays first
      const timer = setTimeout(() => setShowAchievements(true), 1500);
      return () => clearTimeout(timer);
    }
  }, [submitResult?.achievements]);

  const isQuit = challenge?.status === "quit" || quitResult != null;
  const isSolved = submitResult?.solved === true;
  const problem = startResponse?.problem;
  const problemRating = challenge?.problem_rating ?? problem?.rating;
  const problemTags = challenge?.problem_tags ?? problem?.tags ?? [];
  const eloChange = submitResult?.elo_change ?? quitResult?.elo_change;
  const ppChange = submitResult?.pp_change ?? challenge?.pp_change;
  const tokensEarned = submitResult?.tokens_earned ?? 0;
  const overkillMultiplier = submitResult?.overkill_multiplier ?? 1.0;
  const isOverkill = overkillMultiplier > 1.0;
  const achievements = submitResult?.achievements ?? [];

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

      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-center"
      >
        <div
          className={`mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl ${
            isQuit
              ? "bg-red-500/10"
              : isSolved
                ? "bg-green-500/10"
                : "bg-red-500/10"
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
          {isQuit ? t("challenge:pve.challengeAbandoned") : isSolved ? t("challenge:pve.challengeComplete") : t("challenge:pve.notSolved")}
        </h1>

        {eloChange != null && (
          <div className="mt-2">
            <EloChange value={eloChange} triggerKey={eloTriggerKey} />
          </div>
        )}
      </motion.div>

      {/* Problem reveal card */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ delay: 0.2 }}
        className="rounded-xl border-2 border-border bg-card p-5"
      >
        <h3 className="text-sm font-semibold text-foreground">{t("challenge:pve.problemRevealed")}</h3>
        {problem && (
          <div className="mt-3 space-y-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-foreground">{problem.name}</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {problem.contest_id}
                  {problem.index}
                </p>
              </div>
              {/* Revealed rating */}
              {problemRating != null && (
                <motion.span
                  initial={{ opacity: 0, scale: 0.5 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ delay: 0.4, type: "spring", stiffness: 300, damping: 25 }}
                  className="shrink-0 rounded-lg px-3 py-1 text-sm font-bold"
                  style={{
                    color: getRatingColor(problemRating),
                    backgroundColor: `${getRatingColor(problemRating)}20`,
                  }}
                >
                  {problemRating}
                </motion.span>
              )}
            </div>

            {/* Revealed tags */}
            <AnimatePresence>
              {problemTags.length > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 0.5 }}
                  className="flex flex-wrap gap-1.5"
                >
                  {problemTags.map((tag, i) => (
                    <motion.span
                      key={tag}
                      initial={{ opacity: 0, y: 5 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.5 + i * 0.08 }}
                      className="rounded-md bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                    >
                      {tag}
                    </motion.span>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>

            <a
              href={problem.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              <ExternalLink className="size-3" />
              {t("challenge:viewOnCodeforces")}
            </a>
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
        {/* Elo change */}
        <div className="rounded-xl border border-border bg-card p-4 text-center">
          <p className="text-xs text-muted-foreground">{t("common:elo")}</p>
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

        {/* PP change */}
        <div className="rounded-xl border border-border bg-card p-4 text-center">
          <p className="text-xs text-muted-foreground">{t("common:pp")}</p>
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

        {/* Tokens earned */}
        <div className="rounded-xl border border-border bg-card p-4 text-center">
          <p className="text-xs text-muted-foreground">{t("common:tokens")}</p>
          <div className="mt-1">
            <CoinAnimation amount={tokensEarned} triggerKey={eloTriggerKey} className="justify-center" />
            {tokensEarned === 0 && (
              <span className="text-lg font-bold text-muted-foreground">0</span>
            )}
          </div>
        </div>
      </motion.div>

      {/* Overkill bonus indicator */}
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
                  {t("challenge:pve.overkillBonus")}
                </h4>
                <p className="text-sm text-yellow-400/80">
                  {t("challenge:pve.overkillDesc", { multiplier: overkillMultiplier.toFixed(2) })}
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Actions */}
      <div className="flex justify-center gap-3">
        <Button onClick={onReset}>
          <RotateCcw className="mr-2 size-4" />
          {t("challenge:pve.newChallenge")}
        </Button>
        <Button variant="outline" onClick={() => navigate("/dashboard")}>
          {t("challenge:pve.backToDashboard")}
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function PvEChallengePage() {
  const navigate = useNavigate();
  const phase = usePvEChallengeStore((s) => s.phase);
  const reset = usePvEChallengeStore((s) => s.reset);

  const handleReset = useCallback(() => {
    reset();
  }, [reset]);

  const handleNavigateBack = useCallback(() => {
    reset();
    navigate("/challenge");
  }, [reset, navigate]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      // Do not reset here -- allow back navigation to preserve state
    };
  }, []);

  if (phase === "idle" || phase === "loading") {
    return <IdlePhase />;
  }

  if (phase === "in_progress") {
    return <InProgressPhase onNavigateBack={handleNavigateBack} />;
  }

  if (phase === "result") {
    return <ResultPhase onReset={handleReset} />;
  }

  return <IdlePhase />;
}
