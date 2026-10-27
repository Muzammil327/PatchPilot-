"use client";

import { useMemo, useState } from "react";

import type { RepoFile } from "@/lib/api";

interface TreeFolder {
  name: string;
  path: string;
  folders: TreeFolder[];
  files: RepoFile[];
}

function buildTree(files: RepoFile[]): TreeFolder {
  const root: TreeFolder = { name: "", path: "", folders: [], files: [] };
  for (const file of files) {
    const parts = file.path.split("/");
    let folder = root;
    for (const name of parts.slice(0, -1)) {
      const path = folder.path ? `${folder.path}/${name}` : name;
      let child = folder.folders.find((candidate) => candidate.name === name);
      if (!child) {
        child = { name, path, folders: [], files: [] };
        folder.folders.push(child);
      }
      folder = child;
    }
    folder.files.push(file);
  }
  sortTree(root);
  return root;
}

function sortTree(folder: TreeFolder) {
  folder.folders.sort((a, b) => a.name.localeCompare(b.name));
  folder.files.sort((a, b) => a.path.localeCompare(b.path));
  folder.folders.forEach(sortTree);
}

function withAncestors(folders: Set<string>, filePath: string): Set<string> {
  const parts = filePath.split("/").slice(0, -1);
  const ancestors = parts.map((_, index) => parts.slice(0, index + 1).join("/"));
  if (ancestors.every((folder) => folders.has(folder))) return folders;
  return new Set([...folders, ...ancestors]);
}

function fileName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

interface RepoFileListProps {
  files: RepoFile[];
  fileCount: number;
  selectedPath: string | null;
  onSelect: (path: string) => void;
}

export function RepoFileList({ files, fileCount, selectedPath, onSelect }: RepoFileListProps) {
  const tree = useMemo(() => buildTree(files), [files]);
  const [openFolders, setOpenFolders] = useState<Set<string>>(
    () => new Set(tree.folders.map((folder) => folder.path)),
  );
  // When a file is selected from elsewhere (search, ask), open its folders so it shows.
  // Adjusting state during render is React's pattern for reacting to a prop change.
  const [revealedPath, setRevealedPath] = useState<string | null>(null);
  if (selectedPath !== revealedPath) {
    setRevealedPath(selectedPath);
    if (selectedPath) setOpenFolders((current) => withAncestors(current, selectedPath));
  }

  function handleToggleFolder(path: string) {
    setOpenFolders((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }

  return (
    <div className="flex min-h-0 flex-col gap-2">
      <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
        Files
        {files.length < fileCount && (
          <span className="font-normal text-muted">
            {" "}
            (showing {files.length} of {fileCount})
          </span>
        )}
      </h2>
      {files.length === 0 ? (
        <p className="text-sm text-muted">No source files found.</p>
      ) : (
        <FolderContents
          folder={tree}
          openFolders={openFolders}
          selectedPath={selectedPath}
          onToggleFolder={handleToggleFolder}
          onSelect={onSelect}
        />
      )}
    </div>
  );
}

interface FolderContentsProps {
  folder: TreeFolder;
  openFolders: Set<string>;
  selectedPath: string | null;
  onToggleFolder: (path: string) => void;
  onSelect: (path: string) => void;
}

function FolderContents({
  folder,
  openFolders,
  selectedPath,
  onToggleFolder,
  onSelect,
}: FolderContentsProps) {
  return (
    <ul className={`font-mono text-xs ${folder.path ? "ml-3 border-l border-border pl-1.5" : ""}`}>
      {folder.folders.map((child) => {
        const isOpen = openFolders.has(child.path);
        return (
          <li key={child.path}>
            <button
              type="button"
              onClick={() => onToggleFolder(child.path)}
              aria-expanded={isOpen}
              className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
            >
              <svg
                viewBox="0 0 16 16"
                aria-hidden="true"
                className={`size-3 shrink-0 fill-none stroke-muted transition-transform motion-reduce:transition-none ${isOpen ? "rotate-90" : ""}`}
                strokeWidth="2"
              >
                <path d="M6 4l4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <FolderIcon />
              <span className="truncate">{child.name}</span>
            </button>
            {isOpen && (
              <FolderContents
                folder={child}
                openFolders={openFolders}
                selectedPath={selectedPath}
                onToggleFolder={onToggleFolder}
                onSelect={onSelect}
              />
            )}
          </li>
        );
      })}
      {folder.files.map((file) => {
        const isSelected = file.path === selectedPath;
        return (
          <li key={file.path}>
            <button
              type="button"
              onClick={() => onSelect(file.path)}
              aria-current={isSelected ? "true" : undefined}
              className={`flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left transition-colors focus-visible:outline-2 focus-visible:outline-accent ${
                isSelected ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface hover:text-foreground"
              }`}
            >
              <span aria-hidden="true" className="w-3 shrink-0" />
              <FileIcon />
              <span className="truncate">{fileName(file.path)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function FolderIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className="size-3.5 shrink-0 fill-accent-soft stroke-accent" strokeWidth="1.25">
      <path d="M1.5 4.5a1 1 0 011-1h3.6l1.4 1.5h5.9a1 1 0 011 1v6.5a1 1 0 01-1 1h-10.9a1 1 0 01-1-1z" strokeLinejoin="round" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className="size-3.5 shrink-0 fill-none stroke-current" strokeWidth="1.25">
      <path d="M4 1.5h5l3 3v10H4z" strokeLinejoin="round" />
      <path d="M9 1.5v3h3" strokeLinejoin="round" />
    </svg>
  );
}
