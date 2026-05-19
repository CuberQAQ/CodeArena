import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Swords, Loader2, Clock, Trophy, ExternalLink, X, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { extractApiError, formatTime, getRatingColor } from "@/utils";
import api from "@/services/api";
import type {
  ApiResponse,
  QueueStatus,
  StartChallengeResponse,
  ChallengeDetail,
  SubmitResultResponse,
  QuitChallengeResponse,
} from "@/types";

type Phase = "idle" | "queuing" | "matched" | "in_progress" | "result";

export default function ChallengePage() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string>("");
  const [challenge, setChallenge] = useState<ChallengeDetail | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [solved, setSolved] = useState(false);
  const [attempts, setAttempts] = useState(0);
  const [quitSubmissions, setQuitSubmissions] = useState(0);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (timerRef.current) clearInterval(timerRef.current);
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
          setPhase("matched");
        }
      } catch {
        // Continue polling on transient errors
      }
    }, 2000);
  }, []);

  // Timer for in-progress phase
  const startTimer = useCallback(() => {
    setElapsed(0);
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
  }, []);

  // Join queue
  const handleJoinQueue = async () => {
    setError("");
    setLoading(true);
    try {
      const res = await api.post<ApiResponse<QueueStatus>>("/challenge/queue");
      const status = res.data.data;
      if (status.matched && status.session_id) {
        setSessionId(status.session_id);
        setPhase("matched");
      } else {
        setPhase("queuing");
        startPolling();
      }
    } catch (err) {
      setError(extractApiError(err, "Failed to join queue"));
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
      setSessionId(data.session_id);
      setPhase("in_progress");
      startTimer();
      // Fetch full details
      const detailRes = await api.get<ApiResponse<ChallengeDetail>>(
        `/challenge/${data.session_id}`,
      );
      setChallenge(detailRes.data.data);
    } catch (err) {
      setError(extractApiError(err, "Failed to start challenge"));
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
        // Fetch final details
        const detailRes = await api.get<ApiResponse<ChallengeDetail>>(
          `/challenge/${sessionId}`,
        );
        setChallenge(detailRes.data.data);
        setPhase("result");
      } else {
        // Waiting for opponent
        setPhase("result");
        if (timerRef.current) clearInterval(timerRef.current);
        // Poll for final result
        const pollResult = setInterval(async () => {
          try {
            const detailRes = await api.get<ApiResponse<ChallengeDetail>>(
              `/challenge/${sessionId}`,
            );
            const detail = detailRes.data.data;
            if (detail.status === "completed" || detail.result) {
              clearInterval(pollResult);
              setChallenge(detail);
            }
          } catch {
            // Continue polling
          }
        }, 3000);
      }
    } catch (err) {
      setError(extractApiError(err, "Failed to submit result"));
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
      const detailRes = await api.get<ApiResponse<ChallengeDetail>>(
        `/challenge/${sessionId}`,
      );
      setChallenge(detailRes.data.data);
      setPhase("result");
    } catch (err) {
      setError(extractApiError(err, "Failed to quit challenge"));
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
  };

  // ── IDLE ────────────────────────────────────────────────────────
  if (phase === "idle") {
    return (
      <div className="mx-auto max-w-2xl">
        <div className="text-center">
          <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl bg-primary/10">
            <Swords className="size-8 text-primary" />
          </div>
          <h1 className="text-2xl font-bold text-foreground">Random Challenge</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Get matched with an opponent of similar skill and solve a problem head-to-head.
            The faster solver wins Elo and tokens!
          </p>
        </div>

        {error && (
          <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="mt-8 flex justify-center">
          <Button size="lg" onClick={handleJoinQueue} disabled={loading}>
            {loading ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                Joining...
              </>
            ) : (
              <>
                <Swords className="mr-2 size-4" />
                Find Opponent
              </>
            )}
          </Button>
        </div>

        <div className="mt-8 rounded-xl border border-border bg-card p-5">
          <h3 className="text-sm font-semibold text-foreground">How it works</h3>
          <ol className="mt-3 space-y-2 text-sm text-muted-foreground">
            <li>1. Click "Find Opponent" to enter the matchmaking queue</li>
            <li>2. Once matched, both players receive the same problem</li>
            <li>3. Solve the problem on Codeforces as fast as you can</li>
            <li>4. Report your result -- first to solve wins more tokens</li>
            <li>5. Both players&apos; Elo ratings are updated based on the outcome</li>
          </ol>
        </div>
      </div>
    );
  }

  // ── QUEUING ─────────────────────────────────────────────────────
  if (phase === "queuing") {
    return (
      <div className="mx-auto max-w-2xl text-center">
        <div className="mx-auto mb-6 flex size-20 items-center justify-center rounded-full bg-primary/10">
          <Loader2 className="size-10 animate-spin text-primary" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">Finding Opponent...</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Waiting for a suitable opponent. This may take a moment.
        </p>
        <Button variant="outline" className="mt-8" onClick={handleLeaveQueue}>
          <X className="mr-2 size-4" />
          Cancel
        </Button>
      </div>
    );
  }

  // ── MATCHED ─────────────────────────────────────────────────────
  if (phase === "matched") {
    return (
      <div className="mx-auto max-w-2xl text-center">
        <div className="mx-auto mb-6 flex size-20 items-center justify-center rounded-full bg-green-500/10">
          <Trophy className="size-10 text-green-400" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">Opponent Found!</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Your match is ready. Click start to reveal the problem!
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
                Starting...
              </>
            ) : (
              "Start Challenge"
            )}
          </Button>
        </div>
      </div>
    );
  }

  // ── IN PROGRESS ─────────────────────────────────────────────────
  if (phase === "in_progress") {
    const problem = challenge?.problem;
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
          <span className="text-sm font-medium text-muted-foreground">Challenge in progress</span>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Problem card */}
        {problem && (
          <div className="rounded-xl border border-border bg-card p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-foreground">
                  {problem.name}
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  {problem.contest_id}
                  {problem.index}
                </p>
              </div>
              {problem.rating && (
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
              <div className="mt-3 flex flex-wrap gap-1.5">
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
            <Button
              variant="outline"
              className="mt-4"
              onClick={() => window.open(problem.url, "_blank")}
            >
              <ExternalLink className="mr-2 size-4" />
              Open on Codeforces
            </Button>
          </div>
        )}

        {/* Submit result */}
        <div className="rounded-xl border border-border bg-card p-5 space-y-4">
          <h3 className="text-sm font-semibold text-foreground">Report Your Result</h3>

          <div className="flex items-center gap-3">
            <label className="text-sm text-muted-foreground">Did you solve it?</label>
            <Button
              size="sm"
              variant={solved ? "default" : "outline"}
              onClick={() => setSolved(true)}
            >
              <CheckCircle2 className="mr-1.5 size-3.5" />
              Yes
            </Button>
            <Button
              size="sm"
              variant={!solved ? "destructive" : "outline"}
              onClick={() => setSolved(false)}
            >
              <XCircle className="mr-1.5 size-3.5" />
              No
            </Button>
          </div>

          {solved && (
            <div className="flex items-center gap-3">
              <label className="text-sm text-muted-foreground">Attempts:</label>
              <input
                type="number"
                min={1}
                value={attempts || 1}
                onChange={(e) => setAttempts(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-20 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:border-primary focus:outline-none"
              />
            </div>
          )}

          <div className="flex gap-3">
            <Button onClick={handleSubmit} disabled={loading}>
              {loading ? <Loader2 className="mr-2 size-4 animate-spin" /> : null}
              Submit Result
            </Button>
            <Button variant="destructive" onClick={handleQuit} disabled={loading}>
              {loading ? <Loader2 className="mr-2 size-4 animate-spin" /> : <X className="mr-2 size-4" />}
              Quit
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // ── RESULT ──────────────────────────────────────────────────────
  if (phase === "result" && challenge) {
    const isWin = challenge.result === "win";
    const isDraw = challenge.result === "draw";
    const isQuit = challenge.result === "quit" || challenge.status === "quit";

    return (
      <div className="mx-auto max-w-2xl space-y-5">
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
            {isWin ? "Victory!" : isDraw ? "Draw" : isQuit ? "Challenge Abandoned" : "Defeat"}
          </h1>
          {challenge.elo_change != null && (
            <p
              className={`mt-2 text-lg font-bold ${
                challenge.elo_change > 0
                  ? "text-green-400"
                  : challenge.elo_change < 0
                    ? "text-red-400"
                    : "text-muted-foreground"
              }`}
            >
              Elo: {challenge.elo_change > 0 ? "+" : ""}
              {challenge.elo_change}
            </p>
          )}
        </div>

        {/* Problem summary */}
        {challenge.problem && (
          <div className="rounded-xl border border-border bg-card p-5">
            <h3 className="text-sm font-semibold text-foreground">Problem</h3>
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
              View on Codeforces
            </a>
          </div>
        )}

        {/* Stats */}
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">Your Time</p>
            <p className="mt-1 text-lg font-bold text-foreground">
              {challenge.challenger_time != null ? formatTime(challenge.challenger_time) : "-"}
            </p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">Submissions</p>
            <p className="mt-1 text-lg font-bold text-foreground">
              {challenge.challenger_submissions}
            </p>
          </div>
        </div>

        <div className="flex justify-center gap-3">
          <Button onClick={handleReset}>New Challenge</Button>
          <Button variant="outline" onClick={() => navigate("/dashboard")}>
            Back to Dashboard
          </Button>
        </div>
      </div>
    );
  }

  // Fallback for result without challenge data
  return (
    <div className="mx-auto max-w-2xl text-center">
      <LoadingSpinner text="Loading result..." className="py-20" />
      <Button variant="outline" className="mt-4" onClick={handleReset}>
        Back
      </Button>
    </div>
  );
}
