import { ProblemStatementViewer } from "@/components/ProblemStatementViewer";

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
 * ProblemViewer renders a Codeforces problem statement in-app.
 *
 * Delegates to ProblemStatementViewer which fetches the statement from
 * the backend API, renders LaTeX via KaTeX, formats sample I/O pairs,
 * and handles blind-box / loading / error states.
 *
 * Existing consumers (TrainingDetailPage, ContestDetailPage,
 * FreePlaySessionPage, PvE challenge pages) continue to pass the same
 * props -- the interface is fully backward-compatible.
 */
export function ProblemViewer({
  contestId,
  index,
  blindBox,
  className,
}: ProblemViewerProps) {
  return (
    <ProblemStatementViewer
      contestId={contestId}
      index={index}
      blindBox={blindBox}
      className={className}
    />
  );
}
