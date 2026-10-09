"use client";

import { type ReactNode, useCallback, useEffect, useState } from "react";

import { PromptForm } from "@/components/PromptForm";
import { RepoConnect } from "@/components/RepoConnect";
import { RepoDetails } from "@/components/RepoDetails";
import { RepoFileList } from "@/components/RepoFileList";
import { RepoAsk } from "@/components/RepoAsk";
import { RepoHeader } from "@/components/RepoHeader";
import { RepoSearch } from "@/components/RepoSearch";
import { RunIssueForm } from "@/components/RunIssueForm";
import { RunView } from "@/components/RunView";
import { SearchResults } from "@/components/SearchResults";
import { fetchRepo, type RepoSummary } from "@/lib/api";
import { useRepoMap } from "@/lib/use-repo-map";

// Remembers the linked repo across page refreshes. The backend registry is in memory,
// so after a backend restart the stored id is stale and is cleared on the 404.
const REPO_STORAGE_KEY = "patchpilot.repoId";

type WorkspaceState =
  | { status: "restoring" }
  | { status: "disconnected"; notice?: string; lastUrl?: string }
  | { status: "connected"; repo: RepoSummary };

const REPO_MISSING_NOTICE =
  "The backend restarted and no longer has this repository. Click Connect to clone it again.";

function readStoredRepoId(): string | null {
  try {
    return window.localStorage.getItem(REPO_STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStoredRepoId(repoId: string | null) {
  try {
    if (repoId) window.localStorage.setItem(REPO_STORAGE_KEY, repoId);
    else window.localStorage.removeItem(REPO_STORAGE_KEY);
  } catch {
    // Storage unavailable (private mode, blocked): the repo just isn't remembered.
  }
}

async function restoreRepo(signal: AbortSignal): Promise<RepoSummary | null> {
  const repoId = readStoredRepoId();
  if (!repoId) return null;
  try {
    return await fetchRepo(repoId, signal);
  } catch (error) {
    if (signal.aborted) throw error;
    writeStoredRepoId(null);
    return null;
  }
}

export function Workspace() {
  const [state, setState] = useState<WorkspaceState>({ status: "restoring" });

  useEffect(() => {
    const controller = new AbortController();
    restoreRepo(controller.signal)
      .then((repo) =>
        setState(repo ? { status: "connected", repo } : { status: "disconnected" }),
      )
      .catch(() => {
        // Aborted on unmount; nothing to update.
      });
    return () => controller.abort();
  }, []);

  function handleConnected(repo: RepoSummary) {
    writeStoredRepoId(repo.repoId);
    setState({ status: "connected", repo });
  }

  function handleChangeRepo() {
    writeStoredRepoId(null);
    setState({ status: "disconnected" });
  }

  const handleRepoMissing = useCallback((lastUrl: string) => {
    writeStoredRepoId(null);
    setState({ status: "disconnected", notice: REPO_MISSING_NOTICE, lastUrl });
  }, []);

  switch (state.status) {
    case "restoring":
      return (
        <CenteredPage>
          <p className="animate-pulse text-sm text-muted motion-reduce:animate-none">
            Loading workspace…
          </p>
        </CenteredPage>
      );
    case "disconnected":
      return (
        <CenteredPage>
          <RepoConnect
            onConnected={handleConnected}
            initialUrl={state.lastUrl}
            notice={state.notice}
          />
          <PromptForm />
        </CenteredPage>
      );
    case "connected":
      return (
        <ConnectedWorkspace
          key={state.repo.repoId}
          repo={state.repo}
          onChangeRepo={handleChangeRepo}
          onRepoMissing={handleRepoMissing}
        />
      );
  }
}

function CenteredPage({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-12 sm:px-8 sm:py-16">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">PatchPilot</h1>
        <p className="text-muted">
          Autonomous coding agent powered by NVIDIA Nemotron on Nebius Token Factory.
        </p>
      </header>
      {children}
    </main>
  );
}

interface ConnectedWorkspaceProps {
  repo: RepoSummary;
  onChangeRepo: () => void;
  onRepoMissing: (lastUrl: string) => void;
}

type DetailView =
  | { kind: "overview" }
  | { kind: "file"; path: string }
  | { kind: "search"; query: string }
  | { kind: "run"; runId: string };

type BottomTab = "ask" | "fix";

const BOTTOM_TABS: { id: BottomTab; label: string }[] = [
  { id: "ask", label: "Ask" },
  { id: "fix", label: "Fix an issue" },
];

function ConnectedWorkspace({ repo, onChangeRepo, onRepoMissing }: ConnectedWorkspaceProps) {
  const mapState = useRepoMap(repo.repoId);
  const [view, setView] = useState<DetailView>({ kind: "overview" });
  const [bottomTab, setBottomTab] = useState<BottomTab>("ask");
  const [latestRunId, setLatestRunId] = useState<string | null>(null);
  const selectedPath = view.kind === "file" ? view.path : null;
  const handleRepoMissing = useCallback(() => onRepoMissing(repo.url), [onRepoMissing, repo.url]);
  const isMapRepoMissing = mapState.status === "error" && mapState.isRepoMissing;

  useEffect(() => {
    if (isMapRepoMissing) handleRepoMissing();
  }, [isMapRepoMissing, handleRepoMissing]);

  function showOverview() {
    setView({ kind: "overview" });
  }

  function selectFile(path: string) {
    setView({ kind: "file", path });
  }

  function showRun(runId: string) {
    setLatestRunId(runId);
    setView({ kind: "run", runId });
  }

  return (
    <main className="grid flex-1 lg:h-dvh lg:flex-none lg:grid-cols-[20rem_1fr] lg:grid-rows-1 lg:overflow-hidden">
      <aside className="flex flex-col gap-4 border-b border-border p-4 lg:min-h-0 lg:overflow-y-auto lg:border-r lg:border-b-0">
        <h1 className="text-lg font-semibold tracking-tight">PatchPilot</h1>
        <RepoHeader repo={repo} onChangeRepo={onChangeRepo} />
        <RepoSearch onSearch={(query) => setView({ kind: "search", query })} />
        <RepoFileList
          files={repo.files}
          fileCount={repo.fileCount}
          selectedPath={selectedPath}
          onSelect={selectFile}
        />
      </aside>

      <div className="flex flex-col lg:min-h-0">
        <section aria-label="Details" className="flex-1 p-4 sm:p-6 lg:min-h-0 lg:overflow-y-auto">
          {view.kind === "search" ? (
            <SearchResults
              key={view.query}
              repoId={repo.repoId}
              query={view.query}
              onSelectFile={selectFile}
              onClose={showOverview}
              onRepoMissing={handleRepoMissing}
            />
          ) : view.kind === "run" ? (
            <RunView
              key={view.runId}
              repoId={repo.repoId}
              runId={view.runId}
              onSelectFile={selectFile}
              onRepoMissing={handleRepoMissing}
              onClose={showOverview}
            />
          ) : (
            <RepoDetails
              repo={repo}
              mapState={mapState}
              selectedPath={selectedPath}
              onClearSelection={showOverview}
            />
          )}
        </section>
        <section aria-label="Ask or fix" className="flex flex-col gap-3 border-t border-border p-4 sm:p-6">
          <div role="tablist" aria-label="Assistant mode" className="flex gap-1">
            {BOTTOM_TABS.map((tab) => (
              <button
                key={tab.id}
                id={`tab-${tab.id}`}
                type="button"
                role="tab"
                aria-selected={bottomTab === tab.id}
                aria-controls={`panel-${tab.id}`}
                onClick={() => setBottomTab(tab.id)}
                className={`rounded-md px-3 py-1 text-sm font-medium focus-visible:outline-2 focus-visible:outline-accent ${
                  bottomTab === tab.id ? "bg-surface text-foreground" : "text-muted hover:text-foreground"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
          {/* Both panels stay mounted so an answer or a draft survives switching tabs. */}
          <div id="panel-ask" role="tabpanel" aria-labelledby="tab-ask" hidden={bottomTab !== "ask"}>
            <RepoAsk
              repoId={repo.repoId}
              onSelectFile={selectFile}
              onRepoMissing={handleRepoMissing}
            />
          </div>
          <div id="panel-fix" role="tabpanel" aria-labelledby="tab-fix" hidden={bottomTab !== "fix"}>
            <RunIssueForm
              repoId={repo.repoId}
              onRunStarted={showRun}
              onRepoMissing={handleRepoMissing}
            />
            {latestRunId && view.kind !== "run" && (
              <button
                type="button"
                onClick={() => showRun(latestRunId)}
                className="mt-2 text-sm text-accent underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-accent"
              >
                View latest run
              </button>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
