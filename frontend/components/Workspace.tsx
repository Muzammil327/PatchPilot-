"use client";

import { type ReactNode, useEffect, useState } from "react";

import { PromptForm } from "@/components/PromptForm";
import { RepoConnect } from "@/components/RepoConnect";
import { RepoDetails } from "@/components/RepoDetails";
import { RepoFileList } from "@/components/RepoFileList";
import { RepoHeader } from "@/components/RepoHeader";
import { fetchRepo, type RepoSummary } from "@/lib/api";
import { useRepoMap } from "@/lib/use-repo-map";

// Remembers the linked repo across page refreshes. The backend registry is in memory,
// so after a backend restart the stored id is stale and is cleared on the 404.
const REPO_STORAGE_KEY = "patchpilot.repoId";

type WorkspaceState =
  | { status: "restoring" }
  | { status: "disconnected" }
  | { status: "connected"; repo: RepoSummary };

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
          <RepoConnect onConnected={handleConnected} />
        </CenteredPage>
      );
    case "connected":
      return (
        <ConnectedWorkspace
          key={state.repo.repoId}
          repo={state.repo}
          onChangeRepo={handleChangeRepo}
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
}

function ConnectedWorkspace({ repo, onChangeRepo }: ConnectedWorkspaceProps) {
  const mapState = useRepoMap(repo.repoId);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  return (
    <main className="grid flex-1 lg:h-dvh lg:flex-none lg:grid-cols-[20rem_1fr] lg:grid-rows-1 lg:overflow-hidden">
      <aside className="flex flex-col gap-4 border-b border-border p-4 lg:min-h-0 lg:overflow-y-auto lg:border-r lg:border-b-0">
        <h1 className="text-lg font-semibold tracking-tight">PatchPilot</h1>
        <RepoHeader repo={repo} onChangeRepo={onChangeRepo} />
        <RepoFileList
          files={repo.files}
          fileCount={repo.fileCount}
          selectedPath={selectedPath}
          onSelect={setSelectedPath}
        />
      </aside>

      <div className="flex flex-col lg:min-h-0">
        <section aria-label="File details" className="flex-1 p-4 sm:p-6 lg:min-h-0 lg:overflow-y-auto">
          <RepoDetails
            repo={repo}
            mapState={mapState}
            selectedPath={selectedPath}
            onClearSelection={() => setSelectedPath(null)}
          />
        </section>
        <section aria-label="Prompt" className="border-t border-border p-4 sm:p-6">
          <PromptForm />
        </section>
      </div>
    </main>
  );
}
