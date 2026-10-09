const FILE_HEADER = /^diff --git a\/(.+?) b\/(.+)$/;

type DiffLineKind = "file" | "meta" | "hunk" | "add" | "remove" | "context";

const LINE_CLASS: Record<Exclude<DiffLineKind, "file">, string> = {
  meta: "text-muted",
  hunk: "text-accent",
  add: "bg-diff-add",
  remove: "bg-diff-remove",
  context: "",
};

function classify(line: string): DiffLineKind {
  if (line.startsWith("diff --git ")) return "file";
  if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("index ")) return "meta";
  if (line.startsWith("new file") || line.startsWith("deleted file")) return "meta";
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "remove";
  return "context";
}

interface DiffViewProps {
  diff: string;
  onSelectFile: (path: string) => void;
}

export function DiffView({ diff, onSelectFile }: DiffViewProps) {
  const lines = diff.replace(/\n$/, "").split("\n");

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface py-2 font-mono text-xs">
      {lines.map((line, index) => {
        const kind = classify(line);
        if (kind === "file") {
          const path = FILE_HEADER.exec(line)?.[2] ?? line;
          return (
            <button
              // Diff lines have no stable identity beyond their position.
              key={index}
              type="button"
              onClick={() => onSelectFile(path)}
              className="mt-2 block w-full px-3 py-1 text-left font-semibold first:mt-0 hover:underline focus-visible:outline-2 focus-visible:outline-accent"
            >
              {path}
            </button>
          );
        }
        return (
          <div key={index} className={`whitespace-pre px-3 ${LINE_CLASS[kind]}`}>
            {line || " "}
          </div>
        );
      })}
    </div>
  );
}
