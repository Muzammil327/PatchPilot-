"use client";

import { type ReactNode, useCallback, useEffect, useState } from "react";

import { BrandMark } from "@/components/BrandMark";
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
import { UserMenu } from "@/components/UserMenu";
import { fetchActiveRunId, fetchRepo, type GitHubUser, type RepoSummary } from "@/lib/api";
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

interface WorkspaceProps {
  user: GitHubUser;
  onSignOut: () => void;
}

export function Workspace({ user, onSignOut }: WorkspaceProps) {
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
          <UserMenu user={user} onSignOut={onSignOut} />
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
          user={user}
          onSignOut={onSignOut}
        />
      );
  }
}

export function CenteredPage({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-12 sm:px-8 sm:py-20">
      <header className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <BrandMark className="size-10" />
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">PatchPilot</h1>
        </div>
        <p className="text-lg text-foreground sm:text-xl">
          The AI engineer that <span className="text-accent">proves its fix</span> before it opens
          the pull request.
        </p>
        <ul className="flex flex-wrap gap-2 text-xs text-muted">
          <li className="rounded-full border border-border bg-surface px-3 py-1">NVIDIA Nemotron</li>
          <li className="rounded-full border border-border bg-surface px-3 py-1">
            Nebius Token Factory
          </li>
          <li className="rounded-full border border-border bg-surface px-3 py-1">
            Sandboxed tests + independent review
          </li>
        </ul>
      </header>
      {children}
    </main>
  );
}

interface ConnectedWorkspaceProps {
  repo: RepoSummary;
  onChangeRepo: () => void;
  onRepoMissing: (lastUrl: string) => void;
  user: GitHubUser;
  onSignOut: () => void;
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

function ConnectedWorkspace({
  repo,
  onChangeRepo,
  onRepoMissing,
  user,
  onSignOut,
}: ConnectedWorkspaceProps) {
  const mapState = useRepoMap(repo.repoId);
  const [view, setView] = useState<DetailView>({ kind: "overview" });
  const [bottomTab, setBottomTab] = useState<BottomTab>("ask");
  const [latestRunId, setLatestRunId] = useState<string | null>(null);
  // While a run is in progress only its progress shows; Ask and Fix return when it ends.
  const [runningRunId, setRunningRunId] = useState<string | null>(null);
  // Once a run's pull request is open that fix is done; Ask and Fix wait for "Start a new fix".
  const [pullRequestRunId, setPullRequestRunId] = useState<string | null>(null);
  // Bugs go through Ask first; Fix opens once Ask confirms one (or the user chooses "Fix anyway").
  const [fixHandoff, setFixHandoff] = useState<{ issue: string; key: number } | null>(null);
  const isFixUnlocked = fixHandoff !== null || latestRunId !== null;
  const selectedPath = view.kind === "file" ? view.path : null;
  const handleRepoMissing = useCallback(() => onRepoMissing(repo.url), [onRepoMissing, repo.url]);
  const isMapRepoMissing = mapState.status === "error" && mapState.isRepoMissing;

  useEffect(() => {
    if (isMapRepoMissing) handleRepoMissing();
  }, [isMapRepoMissing, handleRepoMissing]);

  useEffect(() => {
    // After a reload the run may still be going; show it instead of a form that would conflict.
    const controller = new AbortController();
    fetchActiveRunId(repo.repoId, controller.signal)
      .then((runId) => {
        if (!runId) return;
        setLatestRunId(runId);
        setRunningRunId(runId);
        setView({ kind: "run", runId });
      })
      .catch(() => {
        // Aborted, or the lookup failed: the form stays usable and reports a conflict itself.
      });
    return () => controller.abort();
  }, [repo.repoId]);

  const handleRunEnded = useCallback((runId: string) => {
    setRunningRunId((current) => (current === runId ? null : current));
  }, []);

  const handlePullRequestOpened = useCallback((runId: string) => {
    setPullRequestRunId(runId);
  }, []);

  function handleStartNewFix() {
    setPullRequestRunId(null);
    // An empty handoff remounts the form, so the finished issue's text is cleared.
    setFixHandoff({ issue: "", key: Date.now() });
  }

  function showOverview() {
    setView({ kind: "overview" });
  }

  function selectFile(path: string) {
    setView({ kind: "file", path });
  }

  function handleFixIssue(issue: string) {
    setFixHandoff({ issue, key: Date.now() });
    setBottomTab("fix");
  }

  function showRun(runId: string) {
    setLatestRunId(runId);
    setView({ kind: "run", runId });
  }

  function handleRunStarted(runId: string) {
    setRunningRunId(runId);
    showRun(runId);
  }

  return (
    <main className="grid flex-1 lg:h-dvh lg:flex-none lg:grid-cols-[20rem_1fr] lg:grid-rows-1 lg:overflow-hidden">
      <aside className="flex flex-col gap-4 border-b border-border p-4 lg:min-h-0 lg:overflow-y-auto lg:border-r lg:border-b-0">
        <div className="flex items-center gap-2">
          <BrandMark className="size-7" />
          <h1 className="text-lg font-semibold tracking-tight">PatchPilot</h1>
        </div>
        <UserMenu user={user} onSignOut={onSignOut} />
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
              onEnded={handleRunEnded}
              onPullRequestOpened={handlePullRequestOpened}
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
        {runningRunId && (
          <section
            aria-label="Run in progress"
            className="flex flex-wrap items-center gap-3 border-t border-border p-4 text-sm sm:p-6"
          >
            <p className="text-muted">
              The agent is working on this repository. Ask and Fix return when the run ends.
            </p>
            {view.kind !== "run" && (
              <button
                type="button"
                onClick={() => showRun(runningRunId)}
                className="text-accent underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-accent"
              >
                View run
              </button>
            )}
          </section>
        )}
        {!runningRunId && pullRequestRunId && (
          <section
            aria-label="Fix complete"
            className="flex flex-wrap items-center gap-3 border-t border-border p-4 text-sm sm:p-6"
          >
            <p className="text-muted">The pull request for this fix is open.</p>
            {!(view.kind === "run" && view.runId === pullRequestRunId) && (
              <button
                type="button"
                onClick={() => showRun(pullRequestRunId)}
                className="text-accent underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-accent"
              >
                View run
              </button>
            )}
            <button
              type="button"
              onClick={handleStartNewFix}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Start a new fix
            </button>
          </section>
        )}
        {/* Hidden rather than unmounted, so a draft or an answer survives the run. */}
        <section
          aria-label="Ask or fix"
          hidden={runningRunId !== null || pullRequestRunId !== null}
          className="flex flex-col gap-3 border-t border-border p-4 sm:p-6"
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <div
              role="tablist"
              aria-label="Assistant mode"
              className="flex gap-1 rounded-lg border border-border bg-surface p-1"
            >
              {BOTTOM_TABS.map((tab) => {
                const isLocked = tab.id === "fix" && !isFixUnlocked;
                return (
                  <button
                    key={tab.id}
                    id={`tab-${tab.id}`}
                    type="button"
                    role="tab"
                    aria-selected={bottomTab === tab.id}
                    aria-controls={`panel-${tab.id}`}
                    aria-describedby={isLocked ? "fix-locked-hint" : undefined}
                    disabled={isLocked}
                    onClick={() => setBottomTab(tab.id)}
                    className={`rounded-md px-3 py-1 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50 ${
                      bottomTab === tab.id
                        ? "bg-surface-raised text-foreground shadow-sm"
                        : "text-muted hover:text-foreground"
                    }`}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>
            {!isFixUnlocked && (
              <span id="fix-locked-hint" className="text-xs text-muted">
                Ask about the bug first. Fix opens once it is confirmed.
              </span>
            )}
          </div>
          {/* Both panels stay mounted so an answer or a draft survives switching tabs. */}
          <div id="panel-ask" role="tabpanel" aria-labelledby="tab-ask" hidden={bottomTab !== "ask"}>
            <RepoAsk
              repoId={repo.repoId}
              onSelectFile={selectFile}
              onRepoMissing={handleRepoMissing}
              onFixIssue={handleFixIssue}
            />
          </div>
          <div id="panel-fix" role="tabpanel" aria-labelledby="tab-fix" hidden={bottomTab !== "fix"}>
            <RunIssueForm
              // A new handoff remounts the form, replacing any draft with the confirmed issue.
              key={fixHandoff?.key ?? "manual"}
              initialIssue={fixHandoff?.issue}
              repoId={repo.repoId}
              onRunStarted={handleRunStarted}
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
