import type { RepoMapState } from "@/lib/use-repo-map";

export function RepoRoutes({ state }: { state: RepoMapState }) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">Routes</h3>
      <RoutesBody state={state} />
    </div>
  );
}

function RoutesBody({ state }: { state: RepoMapState }) {
  switch (state.status) {
    case "loading":
      return (
        <p className="animate-pulse text-sm text-muted motion-reduce:animate-none">
          Loading routes…
        </p>
      );
    case "error":
      return (
        <p role="alert" className="text-sm text-danger">
          {state.message}
        </p>
      );
    case "success": {
      const { routes } = state.index;
      if (routes.length === 0) {
        return <p className="text-sm text-muted">No JS/TS routes found.</p>;
      }
      return (
        <ul className="max-h-60 overflow-auto rounded-lg border border-border bg-surface p-3 font-mono text-xs">
          {routes.map((route) => (
            <li
              key={`${route.method} ${route.path} ${route.file}`}
              className="flex justify-between gap-4 py-0.5"
            >
              <span className="truncate">
                <span className="inline-block w-14 font-semibold">{route.method}</span>
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
