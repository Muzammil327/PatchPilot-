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
      <h2 className="text-sm font-medium">
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
    <ul className={`font-mono text-xs ${folder.path ? "ml-2 border-l border-border pl-2" : ""}`}>
      {folder.folders.map((child) => {
        const isOpen = openFolders.has(child.path);
        return (
          <li key={child.path}>
            <button
              type="button"
              onClick={() => onToggleFolder(child.path)}
              aria-expanded={isOpen}
              className="flex w-full items-center gap-1 rounded px-1 py-0.5 text-left hover:bg-surface focus-visible:outline-2 focus-visible:outline-accent"
            >
              <span aria-hidden="true" className="w-3 text-muted">
                {isOpen ? "▾" : "▸"}
              </span>
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
              className={`flex w-full items-center gap-1 rounded px-1 py-0.5 text-left focus-visible:outline-2 focus-visible:outline-accent ${
                isSelected ? "bg-accent text-accent-foreground" : "hover:bg-surface"
              }`}
            >
              <span aria-hidden="true" className="w-3" />
              <span className="truncate">{fileName(file.path)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
