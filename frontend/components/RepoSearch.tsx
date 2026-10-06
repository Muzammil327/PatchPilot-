"use client";

import { type FormEvent, useState } from "react";

const MAX_QUERY_LENGTH = 200;

interface RepoSearchProps {
  onSearch: (query: string) => void;
}

export function RepoSearch({ onSearch }: RepoSearchProps) {
  const [query, setQuery] = useState("");
  const isEmpty = query.trim().length === 0;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isEmpty) onSearch(query.trim());
  }

  return (
    <form onSubmit={handleSubmit} role="search" className="flex flex-col gap-1">
      <label htmlFor="repo-search" className="text-sm font-medium">
        Search this repo
      </label>
      <div className="flex gap-2">
        <input
          id="repo-search"
          type="search"
          value={query}
          maxLength={MAX_QUERY_LENGTH}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="e.g. heat risk"
          className="min-w-0 flex-1 rounded-md border border-border bg-surface px-2 py-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
        <button
          type="submit"
          disabled={isEmpty}
          className="shrink-0 rounded-md bg-accent px-3 py-1 text-sm font-semibold text-accent-foreground hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50"
        >
          Search
        </button>
      </div>
    </form>
  );
}
