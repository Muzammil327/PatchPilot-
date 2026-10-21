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

function SignIn({ notice }: { notice?: string }) {
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-border p-4 sm:p-6">
      <h2 className="text-lg font-semibold">Sign in</h2>
      <p className="text-sm text-muted">
        Connect your GitHub account to add a public repository. Pull requests for fixes will be
        opened from your account.
      </p>
      {notice && (
        <p role="alert" className="rounded-lg border border-danger bg-danger-surface p-3 text-sm text-danger">
          {notice}
        </p>
      )}
      <a
        href={githubLoginUrl()}
        className="self-start rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-foreground transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        Continue with GitHub
      </a>
    </section>
  );
}
