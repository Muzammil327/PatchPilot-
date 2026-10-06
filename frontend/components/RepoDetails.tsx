import type { ReactNode } from "react";

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
      <p className="text-sm text-muted">Select a file on the left to see its symbols.</p>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">Stack</h2>
        <ul className="flex flex-wrap gap-2">
          {stackLabels.map((label) => (
            <li key={label} className="rounded-full border border-border bg-surface px-3 py-1 text-xs">
              {label}
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-medium">Scripts</h2>
        {scriptEntries.length === 0 ? (
          <p className="text-sm text-muted">No test, lint, or build scripts found.</p>
        ) : (
          <ul className="flex flex-col gap-1 font-mono text-xs">
            {scriptEntries.map(([name, command]) => (
              <li key={name}>
                <span className="font-semibold">{name}</span>
                <span className="text-muted"> → {command}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <RepoRoutes state={mapState} />
    </div>
  );
}

function FileDetails({ state, path }: { state: RepoMapState; path: string }) {
  switch (state.status) {
    case "loading":
      return (
        <p className="animate-pulse text-sm text-muted motion-reduce:animate-none">
          Loading symbols…
        </p>
      );
    case "error":
      return (
        <p role="alert" className="text-sm text-danger">
          {state.message}
        </p>
      );
    case "success": {
      const { byPath, testsBySource, sourcesByTest } = state.index;
      const fileMap = byPath.get(path);
      if (!fileMap) {
        return (
          <p className="text-sm text-muted">Symbols are only mapped for JS/TS files.</p>
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

  if (isEmpty) return <p className="text-sm text-muted">No top-level symbols found.</p>;

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
