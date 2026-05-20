import { useState, useCallback } from "react";
import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";
import { LoadingSpinner } from "@/components/LoadingSpinner";

interface ProblemViewerProps {
  /** Codeforces contest ID (e.g. 1920) */
  contestId: string | number;
  /** Problem index within the contest (e.g. "A", "B1") */
  index: string;
  /** Whether the problem is in blind-box mode (PvE) */
  blindBox: boolean;
  /** Optional extra class name for the root container */
  className?: string;
}

/**
 * ProblemViewer renders a Codeforces problem either inside an iframe
 * (non-blind-box modes: free pick, training, contest) or as an
 * external link (blind-box / PvE mode).
 *
 * NOTE: Codeforces sets `X-Frame-Options: SAMEORIGIN` and
 * `Content-Security-Policy: frame-ancestors 'self'`, which blocks
 * cross-origin embedding in most browsers. The iframe will likely
 * display a blank frame. Since this blocking cannot be detected via
 * JavaScript events (no error fires, onLoad still triggers), the
 * component always shows a fallback link beneath the iframe.
 */
export function ProblemViewer({
  contestId,
  index,
  blindBox,
  className,
}: ProblemViewerProps) {
  const { t } = useTranslation("common");
  const [loading, setLoading] = useState(!blindBox);

  const problemUrl = `https://codeforces.com/problemset/problem/${contestId}/${index}`;

  const handleLoad = useCallback(() => {
    setLoading(false);
  }, []);

  // Blind-box mode: render a link to open in a new tab
  if (blindBox) {
    return (
      <div className={className}>
        <div className="flex min-h-[600px] flex-col items-center justify-center gap-4 rounded-lg border border-border bg-card p-8">
          <ExternalLink className="size-12 text-muted-foreground" />
          <p className="text-center text-sm text-muted-foreground">
            {t("problemViewer.openInNewTab")}
          </p>
          <a
            href={problemUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-primary underline underline-offset-4 hover:text-primary/80"
          >
            {t("problemViewer.openOnCodeforces")}
            <ExternalLink className="size-4" />
          </a>
        </div>
      </div>
    );
  }

  // Non-blind-box mode: embed via iframe with loading state and fallback link
  return (
    <div className={className}>
      <div className="relative min-h-[600px] w-full overflow-hidden rounded-lg border border-border">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-card">
            <LoadingSpinner size="lg" text={t("problemViewer.loadingProblem")} />
          </div>
        )}

        {/*
         * NOTE: This iframe will likely be blocked by Codeforces'
         * X-Frame-Options / CSP frame-ancestors policy. The onLoad
         * event fires but the browser shows a blank frame. A fallback
         * link is always shown below so users can access the problem.
         */}
        <iframe
          src={problemUrl}
          title={`Codeforces ${contestId}${index}`}
          className="h-full min-h-[600px] w-full border-0"
          onLoad={handleLoad}
          sandbox="allow-scripts allow-same-origin"
          loading="lazy"
        />
      </div>

      {/* Fallback link -- always visible so users can open on CF directly */}
      <div className="mt-2 flex items-center justify-center gap-2">
        <p className="text-xs text-muted-foreground">
          {t("problemViewer.iframeNote")}
        </p>
        <a
          href={problemUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-primary hover:text-primary/80"
        >
          <ExternalLink className="size-3" />
          {t("problemViewer.openOnCodeforces")}
        </a>
      </div>
    </div>
  );
}
