import { EmptyState, ErrorState, SkeletonLines } from "@/components/EmptyState";
import type { RepoMapState } from "@/lib/use-repo-map";

export function RepoRoutes({ state }: { state: RepoMapState }) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Routes</h3>
      <RoutesBody state={state} />
    </section>
  );
}

function RoutesBody({ state }: { state: RepoMapState }) {
  switch (state.status) {
    case "loading":
      return <SkeletonLines label="Loading routes…" />;
    case "error":
      return (
        <ErrorState message={state.message} onRetry={state.isRepoMissing ? undefined : state.retry} />
      );
    case "success": {
      const { routes } = state.index;
      if (routes.length === 0) {
        return (
          <EmptyState title="No routes found">
            Routes are detected in JS/TS code. Libraries and CLIs usually have none.
          </EmptyState>
        );
      }
      return (
        <ul className="max-h-60 overflow-auto rounded-lg border border-border bg-background p-3 font-mono text-xs">
          {routes.map((route) => (
            <li
              key={`${route.method} ${route.path} ${route.file}`}
              className="flex justify-between gap-4 py-0.5"
            >
              <span className="truncate">
                <span className="inline-block w-14 font-semibold text-accent">{route.method}</span>
                {route.path}
                <span className="text-muted"> · {route.kind}</span>
              </span>
              <span className="shrink-0 truncate text-muted">
                {route.file}:{route.line}
              </span>
            </li>
          ))}
        </ul>
      );
    }
  }
}
