import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Dumbbell, Star, BookOpen } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import api from "@/services/api";
import type { ApiResponse, TopicInfo } from "@/types";

function StarRating({ count, max = 5 }: { count: number; max?: number }) {
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: max }, (_, i) => (
        <Star
          key={i}
          className={`size-3.5 ${i < count ? "fill-yellow-400 text-yellow-400" : "text-muted-foreground/30"}`}
        />
      ))}
    </div>
  );
}

export default function TrainingPage() {
  const [topics, setTopics] = useState<TopicInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .get<ApiResponse<TopicInfo[]>>("/training/topics")
      .then((res) => setTopics(res.data.data))
      .catch((err) => {
        const msg = (err as { response?: { data?: { error?: { message?: string } } } })?.response
          ?.data?.error?.message;
        setError(msg ?? "Failed to load topics");
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <LoadingSpinner text="Loading topics..." className="py-20" />;
  }

  if (error) {
    return (
      <div className="mx-auto max-w-4xl text-center">
        <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Topic Training</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose a topic to practice and improve your skills. Earn stars and tokens as you progress.
        </p>
      </div>

      {topics.length === 0 ? (
        <div className="rounded-xl border border-border bg-card px-4 py-12 text-center">
          <BookOpen className="mx-auto size-10 text-muted-foreground" />
          <p className="mt-3 text-sm text-muted-foreground">No topics available yet.</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {topics.map((topic) => {
            const progress =
              topic.total_problems > 0
                ? Math.round((topic.solved_count / topic.total_problems) * 100)
                : 0;

            return (
              <Link
                key={topic.id}
                to={`/training/${topic.id}`}
                className="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-green-500/10">
                      <Dumbbell className="size-5 text-green-400" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-sm font-semibold text-foreground group-hover:text-primary">
                        {topic.name}
                      </h3>
                      {topic.description && (
                        <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
                          {topic.description}
                        </p>
                      )}
                    </div>
                  </div>
                </div>

                <div className="mt-4 flex items-center justify-between">
                  <StarRating count={topic.stars} />
                  <span className="text-xs text-muted-foreground">
                    {topic.solved_count}/{topic.total_problems}
                  </span>
                </div>

                {/* Progress bar */}
                <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-green-400 transition-all"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                <p className="mt-1 text-right text-xs text-muted-foreground">{progress}%</p>

                {topic.cf_tags.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {topic.cf_tags.slice(0, 3).map((tag) => (
                      <span
                        key={tag}
                        className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
