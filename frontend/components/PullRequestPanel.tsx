"use client";

import { useEffect, useRef, useState } from "react";

import { ApiError, createPullRequest } from "@/lib/api";

type PullRequestState =
  | { status: "idle" }
  | { status: "opening" }
  | { status: "opened"; url: string }
  | { status: "error"; message: string };

interface PullRequestPanelProps {
  repoId: string;
  runId: string;
  existingUrl: string | null;
  isVerified: boolean;
  onOpened: () => void;
}

export function PullRequestPanel({
  repoId,
  runId,
  existingUrl,
  isVerified,
  onOpened,
}: PullRequestPanelProps) {
  const [state, setState] = useState<PullRequestState>({ status: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const url = state.status === "opened" ? state.url : existingUrl;
  const isOpening = state.status === "opening";

  async function handleOpen() {
    if (isOpening) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ status: "opening" });
    try {
      const opened = await createPullRequest(repoId, runId, controller.signal);
      setState({ status: "opened", url: opened });
      onOpened();
    } catch (error) {
      if (controller.signal.aborted) return;
      const message =
        error instanceof ApiError ? error.message : "Could not open the pull request.";
      setState({ status: "error", message });
    }
  }

  if (url) {
    return (
      <p className="text-sm">
        Pull request opened:{" "}
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="font-mono text-accent underline-offset-4 hover:underline focus-visible:outline-2 focus-visible:outline-accent"
        >
          {url}
        </a>
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted">
        Applied to PatchPilot&apos;s working copy only; the GitHub repository is unchanged.
        {!isVerified && " The fix is not verified, so the pull request opens as a draft."}
      </p>
      <button
        type="button"
        onClick={handleOpen}
        disabled={isOpening}
        className="self-start rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isOpening ? "Opening pull request…" : "Create pull request"}
      </button>
      <div aria-live="polite">
        {isOpening && (
          <p className="text-sm text-muted">
            Forking if needed and opening the pull request on GitHub…
          </p>
        )}
        {state.status === "error" && (
          <p
            role="alert"
            className="rounded-lg border border-danger bg-danger-surface p-3 text-sm text-danger"
          >
            {state.message}
          </p>
        )}
      </div>
    </div>
  );
}
