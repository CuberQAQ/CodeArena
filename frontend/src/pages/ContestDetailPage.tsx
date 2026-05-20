import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  Circle,
  Clock,
  ExternalLink,
  Loader2,
  Trophy,
  Wifi,
  WifiOff,
  XCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { AchievementPopup } from "@/components/animations";
import { extractApiError, formatTime, getRatingColor } from "@/utils";
import api from "@/services/api";
import { useContestLiveStore } from "@/stores/contestStore";
import type {
  ApiResponse,
  AchievementEvent,
  ContestSessionInfo,
  ContestResult,
  LeaderboardEntry,
} from "@/types";

type Phase = "loading" | "active" | "completed";

// ---------------------------------------------------------------------------
// Leaderboard table sub-component
// ---------------------------------------------------------------------------

function LeaderboardTable({
  entries,
}: {
  entries: LeaderboardEntry[];
}) {
  const { t } = useTranslation("contest");

  if (entries.length === 0) {
    return (
      <div className="py-8 text-center text-sm text-muted-foreground">
        {t("waitingLeaderboard")}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="px-3 py-2 font-medium">#</th>
            <th className="px-3 py-2 font-medium">{t("name")}</th>
            <th className="px-3 py-2 font-medium text-right">{t("common:elo", { ns: "common" })}</th>
            <th className="px-3 py-2 font-medium text-right">{t("common:solved", { ns: "common" })}</th>
            <th className="px-3 py-2 font-medium text-center">{t("type")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50">
          {entries.map((entry) => {
            const isHuman = !entry.is_bot;
            return (
              <tr
                key={`${entry.name}-${entry.rank}`}
                className={
                  isHuman
                    ? "bg-primary/10 font-medium"
                    : "hover:bg-muted/30 transition-colors"
                }
              >
                <td className="px-3 py-2 text-muted-foreground">
                  {entry.rank <= 3 ? (
                    <span
                      className={
                        entry.rank === 1
                          ? "text-yellow-400"
                          : entry.rank === 2
                            ? "text-gray-300"
                            : "text-amber-600"
                      }
                    >
                      {entry.rank}
                    </span>
                  ) : (
                    entry.rank
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-2">
                    {isHuman ? null : (
                      <Bot className="size-3.5 shrink-0 text-muted-foreground" />
                    )}
                    <span className={isHuman ? "text-foreground" : "text-muted-foreground"}>
                      {entry.name}
                    </span>
                    {isHuman && (
                      <span className="rounded bg-primary/20 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                        {t("you")}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2 text-right">
                  <span style={{ color: getRatingColor(entry.elo) }}>
                    {entry.elo}
                  </span>
                </td>
                <td className="px-3 py-2 text-right text-foreground">
                  {entry.solved}
                </td>
                <td className="px-3 py-2 text-center">
                  {isHuman ? (
                    <span className="text-xs text-primary">{t("human")}</span>
                  ) : (
                    <span className="text-xs text-muted-foreground">{t("bot")}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function ContestDetailPage() {
  const { id: contestId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation("contest");
  const [phase, setPhase] = useState<Phase>("loading");
  const [contest, setContest] = useState<ContestSessionInfo | null>(null);
  const [result, setResult] = useState<ContestResult | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [remaining, setRemaining] = useState<number>(0);
  const [selectedProblem, setSelectedProblem] = useState<string | null>(null);
  const [submitSolved, setSubmitSolved] = useState(true);
  const [submitAttempts, setSubmitAttempts] = useState(1);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hasFetchedRef = useRef(false);
  const [achievements, setAchievements] = useState<AchievementEvent[]>([]);
  const [showAchievements, setShowAchievements] = useState(false);

  // Live leaderboard state from Zustand store
  const {
    leaderboard,
    wsState,
    timeElapsed,
    timeTotal,
    connect: connectWs,
    disconnect: disconnectWs,
    contestEnded: wsContestEnded,
    reset: resetLive,
  } = useContestLiveStore();

  const handleEndContest = useCallback(async () => {
    if (!contestId) return;
    setLoading(true);
    try {
      await api.post(`/contest/${contestId}/end`);
      // Disconnect WS
      disconnectWs();
      // Refetch contest data
      const res = await api.get<ApiResponse<ContestSessionInfo>>(`/contest/${contestId}`);
      const data = res.data.data;
      setContest(data);
      if (data.status === "completed" || data.status === "ended") {
        setPhase("completed");
        try {
          const resultRes = await api.get<ApiResponse<ContestResult>>(
            `/contest/${contestId}/result`,
          );
          setResult(resultRes.data.data);
        } catch {
          // Use session info as fallback
        }
      }
    } catch (err) {
      setError(extractApiError(err, t("failedEndContest")));
    } finally {
      setLoading(false);
    }
  }, [contestId, disconnectWs, t]);

  // Initial fetch
  useEffect(() => {
    if (!contestId || hasFetchedRef.current) return;
    hasFetchedRef.current = true;

    const doFetch = async () => {
      try {
        const res = await api.get<ApiResponse<ContestSessionInfo>>(`/contest/${contestId}`);
        const data = res.data.data;
        setContest(data);

        if (data.status === "completed" || data.status === "ended") {
          setPhase("completed");
          try {
            const resultRes = await api.get<ApiResponse<ContestResult>>(
              `/contest/${contestId}/result`,
            );
            setResult(resultRes.data.data);
          } catch {
            // fallback
          }
        } else {
          setPhase("active");
          if (data.remaining_seconds != null) {
            setRemaining(Math.max(0, data.remaining_seconds));
          }
          // Connect WebSocket for live leaderboard
          connectWs(contestId);
        }
      } catch (err) {
        setError(extractApiError(err, t("failedLoadContest")));
        setPhase("active");
      }
    };
    doFetch();
  }, [contestId, connectWs, t]);

  // Countdown timer
  useEffect(() => {
    if (phase !== "active") return;
    timerRef.current = setInterval(() => {
      setRemaining((prev) => {
        if (prev <= 1) {
          if (timerRef.current) clearInterval(timerRef.current);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [phase]);

  // Auto-end when timer reaches 0
  const prevRemainingRef = useRef(remaining);
  useEffect(() => {
    if (prevRemainingRef.current > 0 && remaining === 0 && phase === "active") {
      handleEndContest();
    }
    prevRemainingRef.current = remaining;
  }, [remaining, phase, handleEndContest]);

  // Handle WS contest_ended -> transition to completed
  useEffect(() => {
    if (wsContestEnded && phase === "active" && contestId) {
      // Fetch final result
      const fetchResult = async () => {
        try {
          const res = await api.get<ApiResponse<ContestSessionInfo>>(`/contest/${contestId}`);
          const data = res.data.data;
          setContest(data);
          if (data.status === "completed" || data.status === "ended") {
            setPhase("completed");
            try {
              const resultRes = await api.get<ApiResponse<ContestResult>>(
                `/contest/${contestId}/result`,
              );
              setResult(resultRes.data.data);
            } catch {
              // fallback
            }
          }
        } catch {
          // fallback
        }
      };
      fetchResult();
    }
  }, [wsContestEnded, phase, contestId]);

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      disconnectWs();
      resetLive();
    };
  }, [disconnectWs, resetLive]);

  // Show achievement popup when contest result has achievements
  useEffect(() => {
    if (result?.achievements && result.achievements.length > 0) {
      setAchievements(result.achievements);
      const timer = setTimeout(() => setShowAchievements(true), 1500);
      return () => clearTimeout(timer);
    }
  }, [result?.achievements]);

  const submitProblem = async () => {
    if (!contestId || !selectedProblem) return;
    setError("");
    setLoading(true);
    try {
      await api.post(`/contest/${contestId}/submit`, {
        problem_id: selectedProblem,
        solved: submitSolved,
        attempts: submitAttempts,
        time_spent: 0,
      });
      setSelectedProblem(null);
      // Refetch
      const res = await api.get<ApiResponse<ContestSessionInfo>>(`/contest/${contestId}`);
      const data = res.data.data;
      setContest(data);
      if (data.status === "completed" || data.status === "ended") {
        setPhase("completed");
        disconnectWs();
        try {
          const resultRes = await api.get<ApiResponse<ContestResult>>(
            `/contest/${contestId}/result`,
          );
          setResult(resultRes.data.data);
        } catch {
          // fallback
        }
      }
    } catch (err) {
      setError(extractApiError(err, t("failedSubmit")));
    } finally {
      setLoading(false);
    }
  };

  // -- LOADING --
  if (phase === "loading") {
    return <LoadingSpinner text={t("loadingContest")} className="py-20" />;
  }

  // -- ACTIVE CONTEST --
  if (phase === "active" && contest) {
    const progress = contest.total_problems > 0
      ? Math.round((contest.problems_solved / contest.total_problems) * 100)
      : 0;

    // Find the human's rank in the leaderboard
    const humanEntry = leaderboard.find((e) => !e.is_bot);
    const humanRank = humanEntry?.rank ?? null;

    return (
      <div className="mx-auto max-w-5xl space-y-5">
        {/* Header with timer */}
        <div className="flex items-center justify-between">
          <button
            onClick={() => navigate("/contest")}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            {t("backToContests")}
          </button>
          <div className="flex items-center gap-3">
            {/* WS connection indicator */}
            <div className="flex items-center gap-1.5 text-xs">
              {wsState === "connected" ? (
                <>
                  <Wifi className="size-3.5 text-green-400" />
                  <span className="text-green-400">{t("live")}</span>
                </>
              ) : wsState === "connecting" ? (
                <>
                  <Loader2 className="size-3.5 animate-spin text-yellow-400" />
                  <span className="text-yellow-400">{t("connecting")}</span>
                </>
              ) : wsState === "error" ? (
                <>
                  <WifiOff className="size-3.5 text-red-400" />
                  <span className="text-red-400">{t("disconnected")}</span>
                </>
              ) : (
                <>
                  <WifiOff className="size-3.5 text-muted-foreground" />
                  <span className="text-muted-foreground">{t("offline")}</span>
                </>
              )}
            </div>
            <div className="flex items-center gap-1.5">
              <Clock className="size-4 text-muted-foreground" />
              <span
                className={`font-mono text-lg font-bold ${
                  remaining < 300 ? "text-red-400" : "text-foreground"
                }`}
              >
                {formatTime(remaining)}
              </span>
            </div>
            <Button variant="destructive" size="sm" onClick={handleEndContest} disabled={loading}>
              {t("endContest")}
            </Button>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Stats row */}
        <div className="grid grid-cols-4 gap-3">
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">{t("common:solved", { ns: "common" })}</p>
            <p className="mt-1 text-xl font-bold text-green-400">{contest.problems_solved}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">{t("common:total", { ns: "common" })}</p>
            <p className="mt-1 text-xl font-bold text-foreground">{contest.total_problems}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">{t("common:rank", { ns: "common" })}</p>
            <p className="mt-1 text-xl font-bold text-primary">
              {humanRank ?? "-"}
              <span className="text-xs font-normal text-muted-foreground">
                {" "}/{leaderboard.length || "-"}
              </span>
            </p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">{t("elapsed")}</p>
            <p className="mt-1 text-xl font-bold text-foreground">
              {timeElapsed}<span className="text-xs font-normal text-muted-foreground">/{timeTotal} {t("minutes")}</span>
            </p>
          </div>
        </div>

        {/* Progress bar */}
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-green-400 transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* Two-column layout: Problems + Leaderboard */}
        <div className="grid gap-5 lg:grid-cols-2">
          {/* Left: Problems */}
          <div className="space-y-4">
            {/* Submit panel */}
            {selectedProblem && (
              <div className="rounded-xl border border-primary/30 bg-card p-5 space-y-4">
                <h3 className="text-sm font-semibold text-foreground">
                  {t("reportingResult")}
                </h3>
                <div className="flex items-center gap-3">
                  <span className="text-sm text-muted-foreground">{t("solvedQuestion")}</span>
                  <Button
                    size="sm"
                    variant={submitSolved ? "default" : "outline"}
                    onClick={() => setSubmitSolved(true)}
                  >
                    {t("common:yes", { ns: "common" })}
                  </Button>
                  <Button
                    size="sm"
                    variant={!submitSolved ? "destructive" : "outline"}
                    onClick={() => setSubmitSolved(false)}
                  >
                    {t("common:no", { ns: "common" })}
                  </Button>
                </div>
                {submitSolved && (
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-muted-foreground">{t("common:attempts", { ns: "common" })}:</span>
                    <input
                      type="number"
                      min={1}
                      value={submitAttempts}
                      onChange={(e) => setSubmitAttempts(Math.max(1, parseInt(e.target.value) || 1))}
                      className="w-20 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary focus:outline-none"
                    />
                  </div>
                )}
                <div className="flex gap-2">
                  <Button size="sm" onClick={submitProblem} disabled={loading}>
                    {loading && <Loader2 className="mr-1.5 size-3.5 animate-spin" />}
                    {t("common:submit", { ns: "common" })}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setSelectedProblem(null)}>
                    {t("common:cancel", { ns: "common" })}
                  </Button>
                </div>
              </div>
            )}

            {/* Problem list */}
            <div className="rounded-xl border border-border bg-card">
              <div className="border-b border-border px-5 py-3">
                <h2 className="text-sm font-semibold text-foreground">
                  {t("training:problems", { ns: "training", count: contest.problems.length })}
                </h2>
              </div>
              <div className="divide-y divide-border">
                {contest.problems.map((problem) => {
                  const isThis = problem.problem_id === selectedProblem;
                  return (
                    <div
                      key={problem.problem_id}
                      className={`flex items-center gap-4 px-5 py-3 ${isThis ? "bg-primary/5" : ""}`}
                    >
                      {problem.solved ? (
                        <CheckCircle2 className="size-4 shrink-0 text-green-400" />
                      ) : (
                        <Circle className="size-4 shrink-0 text-muted-foreground" />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium text-foreground">
                          {problem.index} - {problem.name}
                        </p>
                      </div>
                      <span
                        className="shrink-0 text-sm font-bold"
                        style={{ color: getRatingColor(problem.rating) }}
                      >
                        {problem.rating}
                      </span>
                      <div className="flex items-center gap-2">
                        <a
                          href={problem.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-muted-foreground hover:text-foreground"
                        >
                          <ExternalLink className="size-4" />
                        </a>
                        {!problem.solved && !selectedProblem && (
                          <Button
                            size="xs"
                            variant="outline"
                            onClick={() => {
                              setSelectedProblem(problem.problem_id);
                              setSubmitSolved(true);
                              setSubmitAttempts(1);
                            }}
                          >
                            {t("common:report", { ns: "common" })}
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Right: Live Leaderboard */}
          <div className="rounded-xl border border-border bg-card">
            <div className="border-b border-border px-5 py-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-foreground">
                {t("liveLeaderboard")}
              </h2>
              <span className="text-xs text-muted-foreground">
                {t("participants", { count: leaderboard.length })}
              </span>
            </div>
            <LeaderboardTable
              entries={leaderboard}
            />
          </div>
        </div>
      </div>
    );
  }

  // -- COMPLETED --
  const data = result ?? contest;
  const pr = result?.performance_rating;

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      {/* Achievement popup overlay */}
      {achievements.length > 0 && showAchievements && (
        <AchievementPopup
          achievements={achievements}
          onComplete={() => setShowAchievements(false)}
        />
      )}

      <button
        onClick={() => navigate("/contest")}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        {t("backToContests")}
      </button>

      <div className="text-center">
        <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl bg-primary/10">
          <Trophy className="size-8 text-primary" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">{t("contestComplete")}</h1>
        <p className="mt-1 text-sm capitalize text-muted-foreground">
          {data?.tier ?? "Contest"}
        </p>
      </div>

      {data && (
        <>
          {/* Main result stats */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground">{t("common:solved", { ns: "common" })}</p>
              <p className="mt-1 text-xl font-bold text-green-400">{data.problems_solved}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground">{t("common:total", { ns: "common" })}</p>
              <p className="mt-1 text-xl font-bold text-foreground">{data.total_problems}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground">{t("submissions")}</p>
              <p className="mt-1 text-xl font-bold text-foreground">{data.submissions}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground">{t("eloChange")}</p>
              <p
                className={`mt-1 text-xl font-bold ${
                  (data.elo_change ?? 0) > 0
                    ? "text-green-400"
                    : (data.elo_change ?? 0) < 0
                      ? "text-red-400"
                      : "text-muted-foreground"
                }`}
              >
                {(data.elo_change ?? 0) > 0 ? "+" : ""}
                {data.elo_change ?? 0}
              </p>
            </div>
          </div>

          {/* Performance Rating card */}
          {pr != null && (
            <div className="rounded-xl border border-primary/30 bg-primary/5 p-5 text-center">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                {t("performanceRating")}
              </p>
              <div className="mt-2 flex items-center justify-center gap-3">
                <span
                  className="text-4xl font-bold"
                  style={{ color: getRatingColor(pr) }}
                >
                  {pr}
                </span>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {t("performanceRatingDesc")}
              </p>
            </div>
          )}

          {/* Final Leaderboard (if available) */}
          {leaderboard.length > 0 && (
            <div className="rounded-xl border border-border bg-card">
              <div className="border-b border-border px-5 py-3">
                <h2 className="text-sm font-semibold text-foreground">{t("finalStandings")}</h2>
              </div>
              <LeaderboardTable
                entries={leaderboard}
              />
            </div>
          )}

          {/* Problems summary */}
          {result?.problems && result.problems.length > 0 && (
            <div className="rounded-xl border border-border bg-card">
              <div className="border-b border-border px-5 py-3">
                <h2 className="text-sm font-semibold text-foreground">{t("problemSummary")}</h2>
              </div>
              <div className="divide-y divide-border">
                {result.problems.map((problem) => (
                  <div key={problem.problem_id} className="flex items-center gap-4 px-5 py-3">
                    {problem.solved ? (
                      <CheckCircle2 className="size-4 shrink-0 text-green-400" />
                    ) : (
                      <XCircle className="size-4 shrink-0 text-red-400" />
                    )}
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-foreground">
                        {problem.index} - {problem.name}
                      </p>
                    </div>
                    <span
                      className="shrink-0 text-sm font-bold"
                      style={{ color: getRatingColor(problem.rating) }}
                    >
                      {problem.rating}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <div className="flex justify-center gap-3">
        <Button onClick={() => navigate("/contest")}>{t("newContest")}</Button>
        <Button variant="outline" onClick={() => navigate("/dashboard")}>
          {t("dashboard")}
        </Button>
      </div>
    </div>
  );
}
