/**
 * ProblemStatementViewer -- renders a Codeforces problem statement in-app.
 *
 * CF math appears in three formats depending on problem age:
 * 1. `$$$...$$$` — newer CF problems (MathJax inline delimiter)
 * 2. `<script type="math/tex">` — older CF problems
 * 3. `<span class="tex-span">` — already MathJax-rendered (leave as-is)
 *
 * We handle (1) and (2) via KaTeX on the frontend.
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
  contestId: string | number;
  index: string;
  blindBox?: boolean;
  className?: string;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatementSkeleton() {
  return (
    <div className="space-y-4 p-6 animate-pulse" data-testid="statement-skeleton">
      <div className="h-7 w-3/5 rounded bg-muted" />
      <div className="flex gap-4">
        <div className="h-4 w-28 rounded bg-muted" />
        <div className="h-4 w-28 rounded bg-muted" />
      </div>
      {Array.from({ length: 8 }).map((_, i) => (
        <div
          key={i}
          className="h-4 rounded bg-muted"
          style={{ width: `${60 + ((i * 37) % 35)}%` }}
        />
      ))}
      <div className="h-32 w-full rounded bg-muted" />
    </div>
  );
}

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
// CF HTML / LaTeX rendering
// ---------------------------------------------------------------------------

/**
 * Render CF math in HTML to KaTeX output.
 *
 * Handles:
 * - `$$$...$$$` — CF's newer MathJax inline delimiter
 * - `<script type="math/tex; mode=display">` — display-mode LaTeX
 * - `<script type="math/tex">` — inline LaTeX
 * - `<span class="MathJax_Preview">` — MathJax preview spans (stripped)
 * - `.property-title` labels are stripped (we show limits separately)
 */
function renderCfHtml(html: string): string {
  let result = html;

  // Strip MathJax preview spans (would duplicate KaTeX output)
  result = result.replace(/<span class="MathJax_Preview"[^>]*>[\s\S]*?<\/span>/g, "");

  // Strip tex-span elements (MathJax-rendered output, would duplicate KaTeX output)
  result = result.replace(/<span class="tex-span"[^>]*>[\s\S]*?<\/span>/g, "");

  // Replace $$$...$$$ (CF's newer inline math delimiter, supports multiline)
  result = result.replace(/\$\$\$([\s\S]*?)\$\$\$/g, (_, tex) => {
    try {
      return katex.renderToString(tex.trim(), { throwOnError: false });
    } catch {
      return `<code>${tex.trim()}</code>`;
    }
  });

  // Replace <script type="math/tex; mode=display">
  result = result.replace(
    /<script\s+type="math\/tex;\s*mode=display"[^>]*>([\s\S]*?)<\/script>/gi,
    (_, tex) => {
      try {
        return katex.renderToString(tex.trim(), { displayMode: true, throwOnError: false });
      } catch {
        return `<code>${tex.trim()}</code>`;
      }
    },
  );

  // Replace <script type="math/tex"> (inline)
  result = result.replace(
    /<script\s+type="math\/tex"[^>]*>([\s\S]*?)<\/script>/gi,
    (_, tex) => {
      try {
        return katex.renderToString(tex.trim(), { throwOnError: false });
      } catch {
        return `<code>${tex.trim()}</code>`;
      }
    },
  );

  // Strip .property-title divs (CF labels like "time limit per test")
  result = result.replace(/<div class="property-title"[^>]*>[\s\S]*?<\/div>/g, "");

  return result;
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

  useEffect(() => {
    if (!blindBox) {
      void fetchStatement();
    }
  }, [blindBox, fetchStatement]);

  useEffect(() => {
    if (prevBlindBoxRef.current && !blindBox) {
      void fetchStatement();
    }
    prevBlindBoxRef.current = blindBox;
  }, [blindBox, fetchStatement]);

  const renderedBody = useMemo(
    () => (statement?.body_html ? renderCfHtml(statement.body_html) : ""),
    [statement],
  );
  const renderedInputSpec = useMemo(
    () => (statement?.input_spec_html ? renderCfHtml(statement.input_spec_html) : ""),
    [statement],
  );
  const renderedOutputSpec = useMemo(
    () => (statement?.output_spec_html ? renderCfHtml(statement.output_spec_html) : ""),
    [statement],
  );
  const renderedNote = useMemo(
    () => (statement?.note_html ? renderCfHtml(statement.note_html) : ""),
    [statement],
  );

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

  // --- Success ---
  const problemUrl = `https://codeforces.com/problemset/problem/${contestId}/${index}`;

  return (
    <div className={className}>
      <div className="rounded-lg border border-border bg-card">
        {/* Header */}
        <div className="border-b border-border px-6 py-4">
          <h2 className="text-xl font-bold text-foreground">
            {index}. {statement.title}
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

        {/* Problem body — styled via cf-prose class */}
        <div className="cf-prose prose prose-sm max-w-none dark:prose-invert px-6 py-4">
          {renderedBody && <div dangerouslySetInnerHTML={{ __html: renderedBody }} />}
          {renderedInputSpec && (
            <div className="mt-4" dangerouslySetInnerHTML={{ __html: renderedInputSpec }} />
          )}
          {renderedOutputSpec && (
            <div className="mt-4" dangerouslySetInnerHTML={{ __html: renderedOutputSpec }} />
          )}
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
        {renderedNote && (
          <div className="border-t border-border px-6 py-4">
            <div className="cf-prose prose prose-sm max-w-none dark:prose-invert" dangerouslySetInnerHTML={{ __html: renderedNote }} />
          </div>
        )}

        {/* Footer */}
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
