import Image from "next/image";

import type { GitHubUser } from "@/lib/api";

const AVATAR_SIZE_PX = 28;

interface UserMenuProps {
  user: GitHubUser;
  onSignOut: () => void;
}

export function UserMenu({ user, onSignOut }: UserMenuProps) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Image
        src={user.avatarUrl}
        alt=""
        width={AVATAR_SIZE_PX}
        height={AVATAR_SIZE_PX}
        className="shrink-0 rounded-full border border-border"
      />
      <span className="flex min-w-0 flex-1 flex-col leading-tight" title={user.name ?? user.login}>
        {user.name && <span className="truncate font-medium">{user.name}</span>}
        <span className="truncate font-mono text-xs text-muted">@{user.login}</span>
      </span>
      <button
        type="button"
        onClick={onSignOut}
        className="shrink-0 rounded-md border border-border px-2 py-1 text-xs text-muted transition-colors hover:border-danger hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
      >
        Sign out
      </button>
    </div>
  );
}
