import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ExternalLink, Loader2, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { extractApiError } from "@/utils";
import api from "@/services/api";

export default function CFBindPage() {
  const navigate = useNavigate();
  const { user, fetchUser } = useAuthStore();
  const [cfHandle, setCfHandle] = useState(user?.cf_handle ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);
    try {
      // Use the profile update endpoint to set cf_handle
      // Since there's no dedicated CF bind endpoint, we store it via profile
      await api.put("/auth/profile", { cf_handle: cfHandle });
      await fetchUser();
      setSuccess("Codeforces handle bound successfully!");
    } catch (err) {
      setError(extractApiError(err, "Failed to bind Codeforces handle"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <button
        onClick={() => navigate("/profile")}
        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        Back to Profile
      </button>

      <div className="text-center">
        <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl bg-primary/10">
          <ExternalLink className="size-8 text-primary" />
        </div>
        <h1 className="text-2xl font-bold text-foreground">Bind Codeforces Handle</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Link your Codeforces account to track your submissions and get personalized problems.
        </p>
      </div>

      {user?.cf_handle && user.cf_handle_verified && (
        <div className="flex items-center gap-2 rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
          <CheckCircle2 className="size-4 shrink-0" />
          Currently bound: <strong>{user.cf_handle}</strong> (verified)
        </div>
      )}

      {user?.cf_handle && !user.cf_handle_verified && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-400">
          Handle <strong>{user.cf_handle}</strong> is pending verification.
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {success && (
        <div className="rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
          {success}
        </div>
      )}

      <form onSubmit={handleSubmit} className="rounded-xl border border-border bg-card p-6 space-y-4">
        <div className="space-y-2">
          <label htmlFor="cfHandle" className="block text-sm font-medium text-foreground">
            Codeforces Handle
          </label>
          <input
            id="cfHandle"
            type="text"
            required
            value={cfHandle}
            onChange={(e) => setCfHandle(e.target.value)}
            className="w-full rounded-lg border border-input bg-background px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary focus:outline-none focus:ring-2 focus:ring-ring/30"
            placeholder="Enter your CF handle"
          />
        </div>

        <Button type="submit" className="w-full" disabled={loading || !cfHandle.trim()}>
          {loading ? (
            <>
              <Loader2 className="mr-2 size-4 animate-spin" />
              Binding...
            </>
          ) : (
            "Bind Handle"
          )}
        </Button>
      </form>

      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="text-sm font-semibold text-foreground">Why bind your CF handle?</h3>
        <ul className="mt-3 space-y-2 text-sm text-muted-foreground">
          <li>Track your submission history automatically</li>
          <li>Get problems matched to your skill level</li>
          <li>Earn PP (Performance Points) from CF activity</li>
          <li>Verify solves for challenges and contests</li>
        </ul>
      </div>
    </div>
  );
}
