import type { RepoSummary } from "@/lib/api";

interface RepoHeaderProps {
  repo: RepoSummary;
  onChangeRepo: () => void;
}

export function RepoHeader({ repo, onChangeRepo }: RepoHeaderProps) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <a
          href={repo.url}
          target="_blank"
          rel="noopener noreferrer"
          title={repo.name}
          className="min-w-0 truncate font-mono text-sm font-semibold underline-offset-4 hover:underline"
        >
          {repo.name}
        </a>
        <button
          type="button"
          onClick={onChangeRepo}
          className="shrink-0 rounded-md border border-border px-2 py-1 text-xs hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
        >
          Change repo
        </button>
      </div>
      <p className="text-xs text-muted">
        {repo.stack.language} · {repo.fileCount} files · {repo.functionCount} functions ·{" "}
        {repo.routeCount} routes · {repo.testFileCount} test files
      </p>
    </div>
  );
}
