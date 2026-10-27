"use client";

/**
 * Side-by-side diff panes (wireframe-aligned).
 * Uses Monaco DiffEditor when `monaco-editor` is available; otherwise a
 * lightweight line-oriented pane that matches the Code Review mock.
 */

import { useEffect, useState } from "react";

export type DiffFile = {
  path: string;
  original: string;
  modified: string;
  added_lines?: number;
  removed_lines?: number;
};

type MonacoMod = {
  DiffEditor: React.ComponentType<{
    height: string;
    language?: string;
    original: string;
    modified: string;
    options?: Record<string, unknown>;
    theme?: string;
  }>;
};

function FallbackDiff({ file }: { file: DiffFile }) {
  const left = file.original.split("\n");
  const right = file.modified.split("\n");
  const max = Math.max(left.length, right.length);
  return (
    <div
      className="grid grid-cols-2 bg-white border border-rino-border rounded-2xl overflow-hidden"
      role="region"
      aria-label={`Diff ${file.path}`}
    >
      <div className="min-w-0 overflow-x-auto font-mono text-xs leading-[1.85]">
        <div className="bg-[#FAFAF9] px-3.5 py-2.5 font-sans text-xs font-semibold text-rino-muted border-b border-rino-border">
          Original
        </div>
        {Array.from({ length: max }).map((_, i) => {
          const line = left[i];
          const gone = line !== undefined && right[i] !== line && line !== undefined;
          const missing = line === undefined;
          return (
            <div
              key={`l-${i}`}
              className={`flex gap-3 px-3.5 whitespace-pre ${
                missing
                  ? ""
                  : gone
                    ? "bg-[#FEF2F2] text-[#991B1B] line-through"
                    : ""
              }`}
            >
              <span className="text-[#78716C] w-6 text-right flex-none">
                {missing ? "" : i + 1}
              </span>
              <span>{missing ? " " : line}</span>
            </div>
          );
        })}
      </div>
      <div className="min-w-0 overflow-x-auto font-mono text-xs leading-[1.85] border-l border-rino-border">
        <div className="bg-[#FAFAF9] px-3.5 py-2.5 font-sans text-xs font-semibold text-rino-muted border-b border-rino-border">
          Suggested fix
        </div>
        {Array.from({ length: max }).map((_, i) => {
          const line = right[i];
          const added = line !== undefined && left[i] !== line;
          const missing = line === undefined;
          return (
            <div
              key={`r-${i}`}
              className={`flex gap-3 px-3.5 whitespace-pre ${
                missing
                  ? ""
                  : added
                    ? "bg-[#F0FDF4] text-[#166534] font-semibold"
                    : ""
              }`}
            >
              <span className="text-[#78716C] w-6 text-right flex-none">
                {missing ? "" : i + 1}
              </span>
              <span>{missing ? " " : line}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SideBySideDiff({
  files,
  activePath,
}: {
  files: DiffFile[];
  activePath?: string;
}) {
  const [Monaco, setMonaco] = useState<MonacoMod | null>(null);
  const file =
    files.find((f) => f.path === activePath) || files[0] || null;

  useEffect(() => {
    let cancelled = false;
    // Optional Monaco — ignore if the package is not installed.
    // @ts-expect-error optional dependency
    import("@monaco-editor/react")
      .then((mod: { DiffEditor?: MonacoMod["DiffEditor"] }) => {
        if (!cancelled && mod?.DiffEditor) {
          setMonaco({ DiffEditor: mod.DiffEditor });
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!file) {
    return (
      <p className="m-0 text-sm text-rino-muted">No verified diff yet.</p>
    );
  }

  if (Monaco) {
    return (
      <div className="border border-rino-border rounded-2xl overflow-hidden bg-white">
        <div className="bg-[#FAFAF9] px-3.5 py-2.5 text-xs font-semibold text-rino-muted border-b border-rino-border font-mono">
          {file.path}
        </div>
        <Monaco.DiffEditor
          height="360px"
          language="python"
          original={file.original}
          modified={file.modified}
          theme="light"
          options={{
            readOnly: true,
            renderSideBySide: true,
            minimap: { enabled: false },
            fontSize: 12,
            scrollBeyondLastLine: false,
          }}
        />
      </div>
    );
  }

  return <FallbackDiff file={file} />;
}
