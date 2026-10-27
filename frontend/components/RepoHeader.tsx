import type { RepoSummary } from "@/lib/api";

interface RepoHeaderProps {
  repo: RepoSummary;
  onChangeRepo: () => void;
}

export function RepoHeader({ repo, onChangeRepo }: RepoHeaderProps) {
  const stats = [
    { label: "files", value: repo.fileCount },
    { label: "functions", value: repo.functionCount },
    { label: "routes", value: repo.routeCount },
    { label: "test files", value: repo.testFileCount },
  ];
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <a
            href={repo.url}
            target="_blank"
            rel="noopener noreferrer"
            title={repo.name}
            className="min-w-0 truncate font-mono text-sm font-semibold underline-offset-4 hover:text-accent hover:underline"
          >
            {repo.name}
          </a>
          <span className="self-start rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent">
            {repo.stack.language}
          </span>
        </div>
        <button
          type="button"
          onClick={onChangeRepo}
          className="shrink-0 rounded-md border border-border px-2 py-1 text-xs text-muted transition-colors hover:bg-surface-raised hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"
        >
          Change repo
        </button>
      </div>
      <ul className="grid grid-cols-2 gap-2 text-xs">
        {stats.map((stat) => (
          <li key={stat.label} className="rounded-lg bg-surface-raised px-2 py-1.5">
            <span className="font-mono font-semibold">{stat.value}</span>{" "}
            <span className="text-muted">{stat.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
