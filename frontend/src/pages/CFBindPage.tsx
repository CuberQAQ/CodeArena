import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  ExternalLink,
  Loader2,
  CheckCircle2,
  Copy,
  ShieldCheck,
  Unlink,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/auth";
import { extractApiError } from "@/utils";
import api from "@/services/api";

type BindStep = "idle" | "pending" | "success";

export default function CFBindPage() {
  const navigate = useNavigate();
  const { user, fetchUser } = useAuthStore();

  const [cfHandle, setCfHandle] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  // Determine current step based on user state and local flow
  const isAlreadyVerified = !!(user?.cf_handle && user.cf_handle_verified);
  const hasPendingBinding = !!(
    user?.cf_handle &&
    !user.cf_handle_verified &&
    !verificationCode
  );

  const [step, setStep] = useState<BindStep>(
    isAlreadyVerified ? "success" : "idle",
  );

  const handleCopy = async () => {
    if (!verificationCode) return;
    try {
      await navigator.clipboard.writeText(verificationCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback: select text for manual copy
    }
  };

  const handleBind = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!cfHandle.trim()) return;
    setError("");
    setLoading(true);
    try {
      const res = await api.post("/cf-handle/bind", {
        cf_handle: cfHandle.trim(),
      });
      const data = res.data.data;
      setVerificationCode(data.verification_code);
      setStep("pending");
      await fetchUser();
    } catch (err) {
      setError(extractApiError(err, "Failed to bind Codeforces handle"));
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async () => {
    setError("");
    setLoading(true);
    try {
      await api.post("/cf-handle/verify", {
        cf_handle: user?.cf_handle ?? cfHandle,
        verification_code: verificationCode,
      });
      setStep("success");
      setVerificationCode("");
      await fetchUser();
    } catch (err) {
      setError(extractApiError(err, "Verification failed"));
    } finally {
      setLoading(false);
    }
  };

  const handleUnbind = async () => {
    setError("");
    setLoading(true);
    try {
      await api.delete("/cf-handle/unbind");
      setStep("idle");
      setCfHandle("");
      setVerificationCode("");
      await fetchUser();
    } catch (err) {
      setError(extractApiError(err, "Failed to unbind Codeforces handle"));
    } finally {
      setLoading(false);
    }
  };

  // --- Already verified state ---
  if (isAlreadyVerified && step !== "pending") {
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
          <div className="mx-auto mb-4 flex size-16 items-center justify-center rounded-2xl bg-green-500/10">
            <CheckCircle2 className="size-8 text-green-400" />
          </div>
          <h1 className="text-2xl font-bold text-foreground">
            Codeforces Handle Bound
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Your Codeforces account is linked and verified.
          </p>
        </div>

        <div className="flex items-center justify-center gap-2 rounded-lg border border-green-500/30 bg-green-500/10 px-4 py-3 text-sm text-green-400">
          <ShieldCheck className="size-4 shrink-0" />
          <span>
            Bound handle: <strong>{user.cf_handle}</strong> (verified)
          </span>
        </div>

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        <div className="rounded-xl border border-border bg-card p-6">
          <Button
            variant="destructive"
            className="w-full"
            disabled={loading}
            onClick={handleUnbind}
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 size-4 animate-spin" />
                Unbinding...
              </>
            ) : (
              <>
                <Unlink className="mr-2 size-4" />
                Unbind Handle
              </>
            )}
          </Button>
        </div>
      </div>
    );
  }

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
        <h1 className="text-2xl font-bold text-foreground">
          Bind Codeforces Handle
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Link your Codeforces account to track your submissions and get
          personalized problems.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {/* Pending state info from server (user previously bound but didn't verify) */}
      {hasPendingBinding && step === "idle" && (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/10 px-4 py-3 text-sm text-yellow-400">
          Handle <strong>{user.cf_handle}</strong> is pending verification.
          Enter the handle below and click "Bind" to get a new verification
          code, or provide the code if you still have it.
        </div>
      )}

      {/* Step 1: Input CF handle and initiate binding */}
      {(step === "idle" || (step === "pending" && !verificationCode)) && (
        <form
          onSubmit={handleBind}
          className="rounded-xl border border-border bg-card p-6 space-y-4"
        >
          <div className="space-y-2">
            <label
              htmlFor="cfHandle"
              className="block text-sm font-medium text-foreground"
            >
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

          <Button
            type="submit"
            className="w-full"
            disabled={loading || !cfHandle.trim()}
          >
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
      )}

      {/* Step 2: Show verification code and instruct user */}
      {step === "pending" && verificationCode && (
        <div className="rounded-xl border border-border bg-card p-6 space-y-5">
          <div className="space-y-3">
            <h2 className="text-lg font-semibold text-foreground">
              Verify Your Handle
            </h2>
            <p className="text-sm text-muted-foreground">
              Copy the verification code below and add it to your Codeforces
              profile{" "}
              <strong className="text-foreground">Organization</strong> field.
            </p>
          </div>

          {/* Verification code display */}
          <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
            <code className="flex-1 text-center font-mono text-lg tracking-widest text-foreground">
              {verificationCode}
            </code>
            <Button
              variant="outline"
              size="icon-sm"
              onClick={handleCopy}
              title="Copy verification code"
            >
              <Copy className="size-4" />
            </Button>
          </div>
          {copied && (
            <p className="text-xs text-green-400">Copied to clipboard!</p>
          )}

          {/* Instructions */}
          <ol className="space-y-2 text-sm text-muted-foreground">
            <li className="flex gap-2">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                1
              </span>
              Go to your{" "}
              <a
                href="https://codeforces.com/settings"
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary underline underline-offset-2 hover:text-primary/80"
              >
                Codeforces Settings
              </a>{" "}
              page.
            </li>
            <li className="flex gap-2">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                2
              </span>
              Paste the code into the <strong>Organization</strong> field and
              save.
            </li>
            <li className="flex gap-2">
              <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                3
              </span>
              Come back here and click "Verify" below.
            </li>
          </ol>

          <div className="flex gap-3">
            <Button
              className="flex-1"
              disabled={loading}
              onClick={handleVerify}
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 size-4 animate-spin" />
                  Verifying...
                </>
              ) : (
                <>
                  <ShieldCheck className="mr-2 size-4" />
                  Verify
                </>
              )}
            </Button>
            <Button
              variant="outline"
              disabled={loading}
              onClick={() => {
                setStep("idle");
                setVerificationCode("");
              }}
            >
              Back
            </Button>
          </div>
        </div>
      )}

      {/* Info section */}
      <div className="rounded-xl border border-border bg-card p-5">
        <h3 className="text-sm font-semibold text-foreground">
          Why bind your CF handle?
        </h3>
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
