import type { GitHubUser } from "@/lib/api";

interface UserMenuProps {
  user: GitHubUser;
  onSignOut: () => void;
}

export function UserMenu({ user, onSignOut }: UserMenuProps) {
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="min-w-0 truncate text-muted" title={user.name ?? user.login}>
        Signed in as <span className="font-mono text-foreground">@{user.login}</span>
      </span>
      <button
        type="button"
        onClick={onSignOut}
        className="shrink-0 rounded-md border border-border px-2 py-1 text-xs hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
      >
        Sign out
      </button>
    </div>
  );
}
