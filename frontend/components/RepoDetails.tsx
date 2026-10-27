import type { ReactNode } from "react";

import { EmptyState, SkeletonLines } from "@/components/EmptyState";
import { RepoRoutes } from "@/components/RepoRoutes";
import type { FileMap, RepoSummary } from "@/lib/api";
import type { RepoMapState } from "@/lib/use-repo-map";

interface RepoDetailsProps {
  repo: RepoSummary;
  mapState: RepoMapState;
  selectedPath: string | null;
  onClearSelection: () => void;
}

export function RepoDetails({ repo, mapState, selectedPath, onClearSelection }: RepoDetailsProps) {
  if (!selectedPath) return <RepoOverview repo={repo} mapState={mapState} />;

  const file = repo.files.find((candidate) => candidate.path === selectedPath);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h2 className="break-all font-mono text-sm font-semibold">{selectedPath}</h2>
          {file && (
            <p className="text-xs text-muted">
              {file.language} · {file.sizeBytes} bytes
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={onClearSelection}
          className="shrink-0 rounded-md border border-border px-2 py-1 text-xs hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
        >
          Overview
        </button>
      </div>
      <FileDetails state={mapState} path={selectedPath} />
    </div>
  );
}

function RepoOverview({ repo, mapState }: { repo: RepoSummary; mapState: RepoMapState }) {
  const { stack } = repo;
  const scriptEntries = Object.entries(stack.scripts);
  const stackLabels = [
    stack.language,
    ...stack.frameworks,
    ...(stack.packageManager ? [stack.packageManager] : []),
  ];

  return (
    <div className="flex flex-col gap-5">
      <StartHere />

      {repo.testFileCount === 0 && (
        <p role="note" className="rounded-xl border border-danger bg-danger-surface p-3 text-sm text-danger">
          No test files were detected. Fix runs verify patches with the repository&apos;s tests, so
          results here may end as &ldquo;Needs review&rdquo;.
        </p>
      )}

      <div className="grid gap-5 md:grid-cols-2">
        <OverviewCard title="Stack">
          <ul className="flex flex-wrap gap-2">
            {stackLabels.map((label) => (
              <li
                key={label}
                className="rounded-full border border-border bg-surface-raised px-3 py-1 text-xs"
              >
                {label}
              </li>
            ))}
          </ul>
        </OverviewCard>

        <OverviewCard title="Scripts">
          {scriptEntries.length === 0 ? (
            <EmptyState title="No test, lint, or build scripts">
              The agent can still edit code, but it cannot run checks to verify the fix.
            </EmptyState>
          ) : (
            <ul className="flex flex-col gap-1 font-mono text-xs">
              {scriptEntries.map(([name, command]) => (
                <li key={name} className="truncate" title={command}>
                  <span className="font-semibold text-accent">{name}</span>
                  <span className="text-muted"> → {command}</span>
                </li>
              ))}
            </ul>
          )}
        </OverviewCard>
      </div>

      <RepoRoutes state={mapState} />
    </div>
  );
}

const START_STEPS = [
  { title: "Ask about a bug", detail: "Use the Ask panel below. A confirmed bug moves to Fix." },
  { title: "Browse the code", detail: "Pick a file on the left to see its symbols and tests." },
  { title: "Search", detail: "Press / to search the repository." },
];

function StartHere() {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
      <h2 className="text-sm font-semibold">Start here</h2>
      <ol className="grid gap-3 sm:grid-cols-3">
        {START_STEPS.map((step, index) => (
          <li key={step.title} className="flex gap-3 rounded-lg bg-surface-raised p-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-accent-soft font-mono text-xs font-semibold text-accent">
              {index + 1}
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="text-sm font-medium">{step.title}</span>
              <span className="text-xs text-muted">{step.detail}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function OverviewCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
      {children}
    </section>
  );
}

function FileDetails({ state, path }: { state: RepoMapState; path: string }) {
  switch (state.status) {
    case "loading":
      return <SkeletonLines label="Loading symbols…" lines={4} />;
    case "error":
      return (
        <p role="alert" className="rounded-lg border border-danger bg-danger-surface p-3 text-sm text-danger">
          {state.message}
        </p>
      );
    case "success": {
      const { byPath, testsBySource, sourcesByTest } = state.index;
      const fileMap = byPath.get(path);
      if (!fileMap) {
        return (
          <EmptyState title="No symbol map for this file">
            Functions, classes, and imports are mapped for JS/TS files only.
          </EmptyState>
        );
      }
      return (
        <FileSymbols
          fileMap={fileMap}
          testedBy={testsBySource.get(path) ?? []}
          covers={sourcesByTest.get(path) ?? []}
        />
      );
    }
  }
}

interface FileSymbolsProps {
  fileMap: FileMap;
  testedBy: string[];
  covers: string[];
}

function FileSymbols({ fileMap, testedBy, covers }: FileSymbolsProps) {
  const { functions, classes, imports, exports } = fileMap;
  const isEmpty =
    functions.length +
      classes.length +
      imports.length +
      exports.length +
      testedBy.length +
      covers.length ===
    0;

  if (isEmpty) {
    return (
      <EmptyState title="No top-level symbols">
        This file has no top-level functions, classes, imports, or exports.
      </EmptyState>
    );
  }

  return (
    <dl className="flex flex-col gap-4 font-mono text-xs">
      {functions.length > 0 && (
        <SymbolGroup label="Functions">
          {functions.map((fn) => (
            <li key={`${fn.name}:${fn.line}`}>
              {fn.name} <span className="text-muted">:{fn.line}</span>
            </li>
          ))}
        </SymbolGroup>
      )}
      {classes.length > 0 && (
        <SymbolGroup label="Classes">
          {classes.map((cls) => (
            <li key={`${cls.name}:${cls.line}`}>
              {cls.name} <span className="text-muted">:{cls.line}</span>
              {cls.methods.length > 0 && (
                <span className="text-muted"> — {cls.methods.join(", ")}</span>
              )}
            </li>
          ))}
        </SymbolGroup>
      )}
      {imports.length > 0 && (
        <SymbolGroup label="Imports">
          {imports.map((ref, index) => (
            <li key={`${ref.source}:${index}`}>
              {ref.source}
              {ref.names.length > 0 && (
                <span className="text-muted"> ← {ref.names.join(", ")}</span>
              )}
            </li>
          ))}
        </SymbolGroup>
      )}
      {exports.length > 0 && (
        <SymbolGroup label="Exports">
          <li>{exports.join(", ")}</li>
        </SymbolGroup>
      )}
      {testedBy.length > 0 && (
        <SymbolGroup label="Tested by">
          {testedBy.map((testFile) => (
            <li key={testFile}>{testFile}</li>
          ))}
        </SymbolGroup>
      )}
      {covers.length > 0 && (
        <SymbolGroup label="Tests">
          {covers.map((sourceFile) => (
            <li key={sourceFile}>{sourceFile}</li>
          ))}
        </SymbolGroup>
      )}
    </dl>
  );
}

function SymbolGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="mb-1 font-sans text-sm font-medium text-foreground">{label}</dt>
      <dd>
        <ul className="flex flex-col gap-0.5">{children}</ul>
      </dd>
    </div>
  );
}
