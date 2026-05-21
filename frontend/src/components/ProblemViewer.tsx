import { ExternalLink } from "lucide-react";
import { useTranslation } from "react-i18next";

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
 * ProblemViewer renders an external link to view a Codeforces problem.
 *
 * Previously this component attempted to embed Codeforces via iframe in
 * non-blind-box modes, but Codeforces sets `X-Frame-Options: SAMEORIGIN`
 * and `Content-Security-Policy: frame-ancestors 'self'`, which blocks
 * cross-origin embedding. Both modes now use an external-link card.
 */
export function ProblemViewer({
  contestId,
  index,
  blindBox,
  className,
}: ProblemViewerProps) {
  const { t } = useTranslation("common");

  const problemUrl = `https://codeforces.com/problemset/problem/${contestId}/${index}`;

  // Blind-box mode: hide problem info, show generic "open in new tab" card
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

  // Non-blind-box mode: show problem info + prominent link to Codeforces
  return (
    <div className={className}>
      <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 rounded-lg border border-border bg-card p-8">
        <ExternalLink className="size-12 text-muted-foreground" />
        <p className="text-lg font-medium text-foreground">
          Problem {contestId}
          {index}
        </p>
        <a
          href={problemUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          {t("problemViewer.openOnCodeforces")}
          <ExternalLink className="size-4" />
        </a>
      </div>
    </div>
  );
}
