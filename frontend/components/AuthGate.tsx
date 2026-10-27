"use client";

import { useEffect, useState } from "react";

import { CenteredPage, Workspace } from "@/components/Workspace";
import {
  ApiError,
  fetchCurrentUser,
  githubLoginUrl,
  type GitHubUser,
  isUnauthorizedError,
  signOut,
} from "@/lib/api";

// The backend's OAuth callback redirects here with this query when sign-in did not finish.
const LOGIN_FAILED_PARAM = "auth";
const LOGIN_FAILED_NOTICE = "GitHub sign-in did not finish. Please try again.";

type AuthState =
  | { status: "checking" }
  | { status: "signed-out"; notice?: string }
  | { status: "error"; message: string }
  | { status: "signed-in"; user: GitHubUser };

function takeLoginFailedNotice(): string | undefined {
  const url = new URL(window.location.href);
  if (!url.searchParams.has(LOGIN_FAILED_PARAM)) return undefined;
  url.searchParams.delete(LOGIN_FAILED_PARAM);
  window.history.replaceState(null, "", url);
  return LOGIN_FAILED_NOTICE;
}

export function AuthGate() {
  const [state, setState] = useState<AuthState>({ status: "checking" });

  useEffect(() => {
    const controller = new AbortController();
    const notice = takeLoginFailedNotice();
    fetchCurrentUser(controller.signal)
      .then((user) => setState({ status: "signed-in", user }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (isUnauthorizedError(error)) setState({ status: "signed-out", notice });
        else {
          const message =
            error instanceof ApiError ? error.message : "Something went wrong. Please try again.";
          setState({ status: "error", message });
        }
      });
    return () => controller.abort();
  }, []);

  async function handleSignOut() {
    try {
      await signOut();
    } catch {
      // The session is gone either way once the page forgets the user.
    }
    setState({ status: "signed-out" });
  }

  switch (state.status) {
    case "checking":
      return (
        <CenteredPage>
          <p className="animate-pulse text-sm text-muted motion-reduce:animate-none">
            Checking sign-in…
          </p>
        </CenteredPage>
      );
    case "error":
      return (
        <CenteredPage>
          <p
            role="alert"
            className="rounded-lg border border-danger bg-danger-surface p-4 text-sm text-danger"
          >
            {state.message}
          </p>
        </CenteredPage>
      );
    case "signed-out":
      return (
        <CenteredPage>
          <SignIn notice={state.notice} />
        </CenteredPage>
      );
    case "signed-in":
      return <Workspace user={state.user} onSignOut={handleSignOut} />;
  }
}

const FLOW_STEPS = [
  { title: "Ask", detail: "Investigate the code and confirm the bug" },
  { title: "Fix", detail: "Plan, patch, and repair failed attempts" },
  { title: "Verify", detail: "Tests, lint, build, and an independent review" },
  { title: "Pull request", detail: "Opened from your GitHub account" },
];

function SignIn({ notice }: { notice?: string }) {
  return (
    <section className="flex flex-col gap-5 rounded-2xl border border-border bg-surface p-5 shadow-2xl shadow-black/40 sm:p-8">
      <ol className="grid gap-3 sm:grid-cols-4">
        {FLOW_STEPS.map((step, index) => (
          <li key={step.title} className="flex flex-col gap-1 rounded-xl border border-border bg-surface-raised p-3">
            <span className="font-mono text-xs text-accent">0{index + 1}</span>
            <span className="text-sm font-semibold">{step.title}</span>
            <span className="text-xs text-muted">{step.detail}</span>
          </li>
        ))}
      </ol>
      <div className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">Sign in to get started</h2>
        <p className="text-sm text-muted">
          Connect your GitHub account to add a public repository. Pull requests for fixes will be
          opened from your account.
        </p>
      </div>
      {notice && (
        <p role="alert" className="rounded-lg border border-danger bg-danger-surface p-3 text-sm text-danger">
          {notice}
        </p>
      )}
      <a
        href={githubLoginUrl()}
        className="inline-flex items-center gap-2 self-start rounded-lg bg-accent px-5 py-2.5 text-sm font-semibold text-accent-foreground shadow-lg shadow-accent-soft transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <GitHubIcon />
        Continue with GitHub
      </a>
    </section>
  );
}

function GitHubIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4 fill-current">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}
