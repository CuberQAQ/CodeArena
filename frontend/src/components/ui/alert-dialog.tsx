/**
 * Simple confirmation dialog (modal overlay).
 *
 * Used for destructive or confirmation actions (e.g. skipping a problem
 * with Elo penalty). Renders a fixed overlay + centered card.
 *
 * Does NOT depend on @base-ui/react alert-dialog to avoid
 * ESM barrel-export tree-shaking warnings.
 *
 * Usage:
 *   <ConfirmDialog open={show} onClose={() => setShow(false)} onConfirm={handleConfirm}
 *     title="Confirm?" message="Are you sure?"
 *     cancelText="Cancel" confirmText="Confirm"
 *   />
 */

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  cancelText?: string;
  confirmText?: string;
  /** Additional class for the confirm button (e.g. destructive styling) */
  confirmClassName?: string;
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  cancelText = "Cancel",
  confirmText = "Confirm",
  confirmClassName,
}: ConfirmDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  // Trap focus inside dialog
  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    return () => {
      previouslyFocused?.focus?.();
    };
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-[2px]"
        onClick={onClose}
      />
      {/* Dialog card */}
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="relative z-10 w-full max-w-md rounded-xl border border-border bg-card p-6 shadow-xl outline-none"
      >
        <h3 className="text-lg font-semibold text-foreground">{title}</h3>
        <p className="mt-2 text-sm text-muted-foreground">{message}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className={cn(
              "inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition-colors",
              "text-muted-foreground hover:bg-muted",
            )}
          >
            {cancelText}
          </button>
          <button
            onClick={onConfirm}
            className={cn(
              "inline-flex items-center justify-center rounded-lg px-4 py-2 text-sm font-medium transition-colors",
              confirmClassName ?? "bg-primary text-primary-foreground hover:bg-primary/90",
            )}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
