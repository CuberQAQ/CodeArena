/**
 * ProblemStatementViewer -- renders a Codeforces problem statement in-app.
 *
 * Features:
 * - Fetches statement from the backend API
 * - Renders LaTeX via KaTeX (inline + display mode)
 * - Formats sample input/output pairs with copy buttons
 * - Shows skeleton while loading, error fallback with CF external link
 * - Respects blindBox mode (no API call until opened)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Check, Copy, AlertCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import katex from "katex";
import {
  getProblemStatement,
  type ProblemStatementData,
  type SampleTest,
} from "@/services/problemApi";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ProblemStatementViewerProps {
  /** Codeforces contest ID (e.g. 1920) */
  contestId: string | number;
  /** Problem index within the contest (e.g. "A", "B1") */
  index: string;
  /** Whether the problem is in blind-box mode */
  blindBox?: boolean;
  /** Optional extra class name for the root container */
  className?: string;
}

// ---------------------------------------------------------------------------
// LaTeX rendering helper
// ---------------------------------------------------------------------------

/**
 * Replace all `<script type="math/tex">` tags in CF HTML with KaTeX output.
 *
 * CF uses two script types:
 * - `<script type="math/tex">...</script>`        -> inline mode
 * - `<script type="math/tex; mode=display">`       -> display mode
 */
function renderLatexInHtml(html: string): string {
  // Replace display-mode LaTeX first (more specific pattern)
  let result = html.replace(
    /<script\s+type="math\/tex;\s*mode=display"[^>]*>([\s\S]*?)<\/script>/gi,
    (_, tex) => {
      try {
        return katex.renderToString(tex.trim(), {
          displayMode: true,
          throwOnError: false,
        });
      } catch {
        // Fallback: show raw LaTeX in a code block
        return `<code class="katex-error">${escapeHtml(tex.trim())}</code>`;
      }
    },
  );

  // Replace inline LaTeX
  result = result.replace(
    /<script\s+type="math\/tex"[^>]*>([\s\S]*?)<\/script>/gi,
    (_, tex) => {
      try {
        return katex.renderToString(tex.trim(), {
          displayMode: false,
          throwOnError: false,
        });
      } catch {
        return `<code class="katex-error">${escapeHtml(tex.trim())}</code>`;
      }
    },
  );

  return result;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Skeleton placeholder while statement loads. */
function StatementSkeleton() {
  return (
    <div className="space-y-4 p-6 animate-pulse" data-testid="statement-skeleton">
      {/* Title */}
      <div className="h-7 w-3/5 rounded bg-muted" />
      {/* Limits */}
      <div className="flex gap-4">
        <div className="h-4 w-28 rounded bg-muted" />
        <div className="h-4 w-28 rounded bg-muted" />
      </div>
      {/* Body lines */}
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="h-4 rounded bg-muted"
          style={{ width: `${60 + ((i * 37) % 35)}%` }}
        />
      ))}
      {/* Sample block */}
      <div className="h-32 w-full rounded bg-muted" />
    </div>
  );
}

/** Copy button for sample blocks. */
function CopyButton({ text }: { text: string }) {
  const { t } = useTranslation("common");
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    });
  }, [text]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="absolute right-2 top-2 flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      title={copied ? t("copied") : "Copy"}
    >
      {copied ? (
        <>
          <Check className="size-3.5 text-green-400" />
          <span className="text-green-400">{t("copied")}</span>
        </>
      ) : (
        <Copy className="size-3.5" />
      )}
    </button>
  );
}

/** Single sample input/output pair. */
function SampleBlock({
  sample,
  index: _index,
}: {
  sample: SampleTest;
  index: number;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="relative rounded-lg border border-border bg-muted/30">
        <div className="border-b border-border px-3 py-1.5 text-xs font-medium text-muted-foreground">
          {t("problemViewer.input", { defaultValue: "Input" })}
        </div>
        <pre className="overflow-x-auto p-3 text-sm font-mono whitespace-pre">
          {sample.input}
        </pre>
        <CopyButton text={sample.input} />
      </div>
      <div className="relative rounded-lg border border-border bg-muted/30">
        <div className="border-b border-border px-3 py-1.5 text-xs font-medium text-muted-foreground">
          {t("problemViewer.output", { defaultValue: "Output" })}
        </div>
        <pre className="overflow-x-auto p-3 text-sm font-mono whitespace-pre">
          {sample.output}
        </pre>
        <CopyButton text={sample.output} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ProblemStatementViewer({
  contestId,
  index,
  blindBox = false,
  className,
}: ProblemStatementViewerProps) {
  const { t } = useTranslation("common");
  const [statement, setStatement] = useState<ProblemStatementData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prevBlindBoxRef = useRef(blindBox);

  const problemId = `${contestId}${index}`;

  const fetchStatement = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await getProblemStatement(problemId);
      setStatement(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load problem");
    } finally {
      setLoading(false);
    }
  }, [problemId]);

  // Fetch on mount when not in blind-box mode
  useEffect(() => {
    if (!blindBox) {
      void fetchStatement();
    }
  }, [blindBox, fetchStatement]);

  // Auto-fetch when blindBox transitions from true to false
  useEffect(() => {
    if (prevBlindBoxRef.current && !blindBox) {
      void fetchStatement();
    }
    prevBlindBoxRef.current = blindBox;
  }, [blindBox, fetchStatement]);

  // Render the full_html with LaTeX processed
  const renderedHtml = useMemo(() => {
    if (!statement?.full_html) return "";
    return renderLatexInHtml(statement.full_html);
  }, [statement]);

  // --- Blind-box mode ---
  if (blindBox) {
    const problemUrl = `https://codeforces.com/problemset/problem/${contestId}/${index}`;
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

  // --- Loading ---
  if (loading) {
    return (
      <div className={className}>
        <div className="rounded-lg border border-border bg-card">
          <StatementSkeleton />
        </div>
      </div>
    );
  }

  // --- Error fallback ---
  if (error || !statement) {
    const fallbackUrl =
      statement?.fallback_url ??
      `https://codeforces.com/problemset/problem/${contestId}/${index}`;
    return (
      <div className={className}>
        <div className="flex min-h-[300px] flex-col items-center justify-center gap-4 rounded-lg border border-border bg-card p-8">
          <AlertCircle className="size-10 text-muted-foreground" />
          <p className="text-center text-sm text-muted-foreground">
            {t("problemViewer.loadFailed")}
          </p>
          <a
            href={fallbackUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            {t("problemViewer.openOnCodeforces")}
            <ExternalLink className="size-4" />
          </a>
          <button
            type="button"
            onClick={fetchStatement}
            className="mt-2 text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            {t("retry")}
          </button>
        </div>
      </div>
    );
  }

  // --- Success: render statement ---
  const problemUrl = `https://codeforces.com/problemset/problem/${contestId}/${index}`;

  return (
    <div className={className}>
      <div className="rounded-lg border border-border bg-card">
        {/* Header */}
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-xl font-bold text-foreground">
            {statement.index}. {statement.title}
          </h2>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            {statement.time_limit && (
              <span>{t("problemViewer.timeLimit", { defaultValue: "Time limit: {{limit}}", limit: statement.time_limit })}</span>
            )}
            {statement.memory_limit && (
              <span>{t("problemViewer.memoryLimit", { defaultValue: "Memory limit: {{limit}}", limit: statement.memory_limit })}</span>
            )}
          </div>
        </div>

        {/* Problem body */}
        <div className="problem-statement prose prose-sm max-w-none px-6 py-4 dark:prose-invert">
          <div dangerouslySetInnerHTML={{ __html: renderedHtml }} />
        </div>

        {/* Samples */}
        {statement.samples && statement.samples.length > 0 && (
          <div className="border-t border-border px-6 py-4 space-y-4">
            <h3 className="text-base font-semibold text-foreground">
              {t("problemViewer.samples", { defaultValue: "Examples" })}
            </h3>
            {statement.samples.map((sample, i) => (
              <SampleBlock key={i} sample={sample} index={i} />
            ))}
          </div>
        )}

        {/* Note */}
        {statement.note_html && (
          <div className="border-t border-border px-6 py-4">
            <div
              className="prose prose-sm max-w-none dark:prose-invert"
              dangerouslySetInnerHTML={{ __html: renderLatexInHtml(statement.note_html) }}
            />
          </div>
        )}

        {/* Footer: CF external link */}
        <div className="border-t border-border px-6 py-3">
          <a
            href={problemUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground underline underline-offset-4 hover:text-foreground"
          >
            {t("problemViewer.viewOnCodeforces", { defaultValue: "View original page on Codeforces" })}
            <ExternalLink className="size-3.5" />
          </a>
        </div>
      </div>
    </div>
  );
}
