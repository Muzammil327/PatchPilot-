import type { ReactNode } from "react";

interface EmptyStateProps {
  title: string;
  /** What the user can do next. */
  children?: ReactNode;
}

/** A quiet "nothing here" message with a hint, used wherever a list can be empty. */
export function EmptyState({ title, children }: EmptyStateProps) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-dashed border-border p-3">
      <svg viewBox="0 0 16 16" aria-hidden="true" className="mt-0.5 size-4 shrink-0 fill-none stroke-muted" strokeWidth="1.5">
        <circle cx="8" cy="8" r="6.25" strokeDasharray="2.5 2" />
      </svg>
      <div className="flex flex-col gap-0.5 text-sm">
        <p className="font-medium">{title}</p>
        {children && <p className="text-muted">{children}</p>}
      </div>
    </div>
  );
}

interface SkeletonLinesProps {
  label: string;
  lines?: number;
}

const SKELETON_WIDTHS = ["w-11/12", "w-4/5", "w-2/3", "w-3/4"];

/** Placeholder bars while content loads; the label is announced to screen readers. */
export function SkeletonLines({ label, lines = 3 }: SkeletonLinesProps) {
  return (
    <div className="flex flex-col gap-2" role="status">
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="flex flex-col gap-2 motion-safe:animate-pulse">
        {Array.from({ length: lines }, (_, index) => (
          <span
            key={index}
            className={`h-2.5 rounded bg-surface-raised ${SKELETON_WIDTHS[index % SKELETON_WIDTHS.length]}`}
          />
        ))}
      </div>
    </div>
  );
}
