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
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { StreakEffect } from "@/components/animations/StreakEffect";
import { CoinAnimation } from "@/components/animations/CoinAnimation";
import { extractApiError, formatTime, getRatingColor } from "@/utils";
import api from "@/services/api";
import type {
  ApiResponse,
  TopicDetail,
  TrainingSessionInfo,
  SubmitTrainingResponse,
} from "@/types";

type Phase = "loading" | "topic" | "session" | "result";

export default function TrainingDetailPage() {
  const { id: topicId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>("loading");
  const [topic, setTopic] = useState<TopicDetail | null>(null);
  const [session, setSession] = useState<TrainingSessionInfo | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [selectedProblem, setSelectedProblem] = useState<string | null>(null);
  const [submitSolved, setSubmitSolved] = useState(true);
  const [submitAttempts, setSubmitAttempts] = useState(1);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [lastTokensEarned, setLastTokensEarned] = useState(0);
  const [tokenTriggerKey, setTokenTriggerKey] = useState(0);

  useEffect(() => {
    if (!topicId) return;
    api
      .get<ApiResponse<TopicDetail>>(`/training/topics/${topicId}`)
      .then((res) => {
        setTopic(res.data.data);
        setPhase("topic");
      })
      .catch(() => {
        setError("Failed to load topic details");
        setPhase("topic");
      });
  }, [topicId]);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

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
      setError(extractApiError(err, "Failed to start training session"));
    } finally {
      setLoading(false);
    }
  };

  const submitProblem = async () => {
    if (!session || !selectedProblem) return;
    setError("");
    setLoading(true);
    try {
      const res = await api.post<ApiResponse<SubmitTrainingResponse>>(
        `/training/session/${session.id}/submit`,
        {
          problem_id: selectedProblem,
          solved: submitSolved,
          attempts: submitAttempts,
          time_spent: elapsed,
        },
      );
      const data = res.data.data;
      // Trigger coin animation if tokens earned
      if (data.tokens_earned > 0) {
        setLastTokensEarned(data.tokens_earned);
        setTokenTriggerKey((k) => k + 1);
      }
      // Refresh session
      const sessRes = await api.get<ApiResponse<TrainingSessionInfo>>(
        `/training/session/${session.id}`,
      );
      setSession(sessRes.data.data);
      setSelectedProblem(null);
      // Refresh topic for updated solved counts
      if (topicId) {
        const topicRes = await api.get<ApiResponse<TopicDetail>>(`/training/topics/${topicId}`);
        setTopic(topicRes.data.data);
      }
      if (data.elo_change != null) {
        // Show brief notification inline
      }
    } catch (err) {
      setError(extractApiError(err, "Failed to submit result"));
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
      setError(extractApiError(err, "Failed to abandon session"));
    } finally {
      setLoading(false);
    }
  };

  const handleReset = () => {
    setSession(null);
    setSelectedProblem(null);
    setPhase("topic");
    setElapsed(0);
    setError("");
  };

  // ── LOADING ─────────────────────────────────────────────────────
  if (phase === "loading") {
    return <LoadingSpinner text="Loading topic..." className="py-20" />;
  }

  // ── TOPIC VIEW ──────────────────────────────────────────────────
  if (phase === "topic" && topic) {
    return (
      <div className="mx-auto max-w-4xl space-y-5">
        <button
          onClick={() => navigate("/training")}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          Back to Topics
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
            Start Training
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
              Problems ({topic.problems?.length ?? 0})
            </h2>
          </div>
          {(!topic.problems || topic.problems.length === 0) ? (
            <div className="px-5 py-8 text-center text-sm text-muted-foreground">
              No problems available for this topic.
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
                        Solved in {formatTime(problem.time_spent)} ({problem.attempts} attempts)
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

  // ── SESSION IN PROGRESS ─────────────────────────────────────────
  if (phase === "session" && session && topic) {
    const currentProblem = topic.problems?.find((p) => p.problem_id === selectedProblem);

    return (
      <div className="mx-auto max-w-4xl space-y-5">
        <div className="flex items-center justify-between">
          <button
            onClick={() => navigate("/training")}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
          >
            <ArrowLeft className="size-4" />
            Topics
          </button>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Clock className="size-4" />
              <span className="font-mono">{formatTime(elapsed)}</span>
            </div>
            <Button variant="destructive" size="sm" onClick={abandonSession} disabled={loading}>
              <StopCircle className="mr-1.5 size-3.5" />
              End Session
            </Button>
          </div>
        </div>

        {/* Session info */}
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">Solved</p>
            <p className="mt-1 text-xl font-bold text-green-400">{session.problems_solved}</p>
          </div>
          <div className="rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">Total</p>
            <p className="mt-1 text-xl font-bold text-foreground">{session.total_problems}</p>
          </div>
          <div className="relative rounded-xl border border-border bg-card p-4 text-center">
            <p className="text-xs text-muted-foreground">Streak</p>
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

        {/* Submit result panel */}
        {selectedProblem && currentProblem && (
          <div className="rounded-xl border border-primary/30 bg-card p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-foreground">
                Reporting: {currentProblem.contest_id}
                {currentProblem.index} - {currentProblem.name}
              </h3>
              {currentProblem.rating && (
                <span
                  className="text-sm font-bold"
                  style={{ color: getRatingColor(currentProblem.rating) }}
                >
                  {currentProblem.rating}
                </span>
              )}
            </div>
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
            <h2 className="text-sm font-semibold text-foreground">Problems</h2>
          </div>
          <div className="divide-y divide-border">
            {topic.problems?.map((problem) => {
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

  // ── RESULT ──────────────────────────────────────────────────────
  if (phase === "result") {
    return (
      <div className="mx-auto max-w-2xl space-y-5 text-center">
        <div className="mx-auto flex size-16 items-center justify-center rounded-2xl bg-green-500/10">
          <Trophy className="size-8 text-green-400" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">Training Session Complete</h1>
        {session && (
          <p className="text-sm text-muted-foreground">
            Solved {session.problems_solved} out of {session.total_problems} problems
          </p>
        )}
        <div className="flex justify-center gap-3">
          <Button onClick={handleReset}>Train Again</Button>
          <Button variant="outline" onClick={() => navigate("/training")}>
            Back to Topics
          </Button>
        </div>
      </div>
    );
  }

  // Fallback
  return <LoadingSpinner className="py-20" />;
}
