"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

const MAX_QUERY_LENGTH = 200;
const FOCUS_SHORTCUT_KEY = "/";

function isTypingTarget(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
  );
}

interface RepoSearchProps {
  onSearch: (query: string) => void;
  /** Called by the "/" shortcut before focusing, so a collapsed sidebar can open first. */
  onReveal?: () => void;
}

export function RepoSearch({ onSearch, onReveal }: RepoSearchProps) {
  const [query, setQuery] = useState("");
  const $inputRef = useRef<HTMLInputElement>(null);
  const isEmpty = query.trim().length === 0;

  useEffect(() => {
    // "/" focuses search, unless the user is already typing somewhere.
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== FOCUS_SHORTCUT_KEY || event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;
      event.preventDefault();
      onReveal?.();
      // Wait a frame: a just-revealed input cannot take focus while it is still display: none.
      requestAnimationFrame(() => $inputRef.current?.focus());
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onReveal]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isEmpty) onSearch(query.trim());
  }

  return (
    <form onSubmit={handleSubmit} role="search" className="flex flex-col gap-1">
      <label htmlFor="repo-search" className="sr-only">
        Search this repo
      </label>
      <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-2 transition-colors focus-within:border-accent focus-within:ring-2 focus-within:ring-accent-soft">
        <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4 shrink-0 fill-none stroke-muted" strokeWidth="1.5">
          <circle cx="7" cy="7" r="4.5" />
          <path d="M10.5 10.5L14 14" strokeLinecap="round" />
        </svg>
        <input
          ref={$inputRef}
          id="repo-search"
          type="search"
          value={query}
          maxLength={MAX_QUERY_LENGTH}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search this repo"
          aria-keyshortcuts={FOCUS_SHORTCUT_KEY}
          className="min-w-0 flex-1 bg-transparent py-2 text-sm outline-none placeholder:text-muted"
        />
        {isEmpty ? (
          <kbd aria-hidden="true" className="rounded border border-border px-1.5 font-mono text-xs text-muted">
            {FOCUS_SHORTCUT_KEY}
          </kbd>
        ) : (
          <button
            type="submit"
            className="shrink-0 rounded-md bg-accent px-2 py-0.5 text-xs font-semibold text-accent-foreground hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Search
          </button>
        )}
      </div>
    </form>
  );
}
