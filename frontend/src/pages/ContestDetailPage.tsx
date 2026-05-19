import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle2,
  Circle,
  Clock,
  ExternalLink,
  Loader2,
  Trophy,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { extractApiError, formatTime, getRatingColor } from "@/utils";
import api from "@/services/api";
import type { ApiResponse, ContestSessionInfo, ContestResult } from "@/types";

type Phase = "loading" | "active" | "completed";

export default function ContestDetailPage() {
  const { id: contestId } = useParams<{ id: string }>();
  const navigate = useNavigate();
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

  const handleEndContest = useCallback(async () => {
    if (!contestId) return;
    setLoading(true);
    try {
      await api.post(`/contest/${contestId}/end`);
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
      setError(extractApiError(err, "Failed to end contest"));
    } finally {
      setLoading(false);
    }
  }, [contestId]);

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
        }
      } catch (err) {
        setError(extractApiError(err, "Failed to load contest"));
        setPhase("active");
      }
    };
    doFetch();
  }, [contestId]);

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
      setError(extractApiError(err, "Failed to submit result"));
    } finally {
      setLoading(false);
    }
  };

  // ── LOADING ─────────────────────────────────────────────────────
  if (phase === "loading") {
    return <LoadingSpinner text="Loading contest..." className="py-20" />;
  }

  // ── ACTIVE CONTEST ──────────────────────────────────────────────
  if (phase === "active" && contest) {
    const progress = contest.total_problems > 0
      ? Math.round((contest.problems_solved / contest.total_problems) * 100)
      : 0;

    return (
      <div className="mx-auto max-w-4xl space-y-5">
        {/* Header with timer */}
        <div className="flex items-center justify-between">
          <button
            onClick={() => navigate("/contest")}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            Back to Contests
          </button>
          <div className="flex items-center gap-3">
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
              End Contest
            </Button>
          </div>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">Solved</p>
            <p className="mt-1 text-xl font-bold text-green-400">{contest.problems_solved}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">Total</p>
            <p className="mt-1 text-xl font-bold text-foreground">{contest.total_problems}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">Submissions</p>
            <p className="mt-1 text-xl font-bold text-foreground">{contest.submissions}</p>
          </div>
        </div>

        {/* Progress bar */}
        <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-green-400 transition-all"
            style={{ width: `${progress}%` }}
          />
        </div>

        {/* Submit panel */}
        {selectedProblem && (
          <div className="rounded-xl border border-primary/30 bg-card p-5 space-y-4">
            <h3 className="text-sm font-semibold text-foreground">
              Reporting result for problem
            </h3>
            <div className="flex items-center gap-3">
              <span className="text-sm text-muted-foreground">Solved?</span>
              <Button
                size="sm"
                variant={submitSolved ? "default" : "outline"}
                onClick={() => setSubmitSolved(true)}
              >
                Yes
              </Button>
              <Button
                size="sm"
                variant={!submitSolved ? "destructive" : "outline"}
                onClick={() => setSubmitSolved(false)}
              >
                No
              </Button>
            </div>
            {submitSolved && (
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">Attempts:</span>
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
                Submit
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setSelectedProblem(null)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* Problem list */}
        <div className="rounded-xl border border-border bg-card">
          <div className="border-b border-border px-5 py-3">
            <h2 className="text-sm font-semibold text-foreground">
              Problems ({contest.problems.length})
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
                        Report
                      </Button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    );
  }

  // ── COMPLETED ───────────────────────────────────────────────────
  const data = result ?? contest;
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <button
        onClick={() => navigate("/contest")}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Back to Contests
      </button>

      <div className="text-center">
        <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl bg-primary/10">
          <Trophy className="size-8 text-primary" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">Contest Complete</h1>
        <p className="mt-1 text-sm capitalize text-muted-foreground">
          {data?.tier ?? "Contest"}
        </p>
      </div>

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground">Solved</p>
              <p className="mt-1 text-xl font-bold text-green-400">{data.problems_solved}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground">Total</p>
              <p className="mt-1 text-xl font-bold text-foreground">{data.total_problems}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground">Submissions</p>
              <p className="mt-1 text-xl font-bold text-foreground">{data.submissions}</p>
            </div>
            <div className="rounded-xl border border-border bg-card p-4 text-center">
              <p className="text-xs text-muted-foreground">Elo Change</p>
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

          {/* Problems summary */}
          {result?.problems && result.problems.length > 0 && (
            <div className="rounded-xl border border-border bg-card">
              <div className="border-b border-border px-5 py-3">
                <h2 className="text-sm font-semibold text-foreground">Problem Summary</h2>
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
        <Button onClick={() => navigate("/contest")}>New Contest</Button>
        <Button variant="outline" onClick={() => navigate("/dashboard")}>
          Dashboard
        </Button>
      </div>
    </div>
  );
}
