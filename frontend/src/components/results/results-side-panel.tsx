"use client";

import { useState } from "react";

import { DocChatPanel } from "@/components/doc-chat";
import { RefineChatPanel } from "@/components/refine-chat";
import type { SaveAction } from "@/components/export-bar";
import { cn } from "@/lib/utils";

type SideTab = "refine" | "chat";

interface ResultsSidePanelProps {
  runId: string;
  chatSessionKey?: string;
  disabled?: boolean;
  saveAction: SaveAction;
  onRefined: (newRunId: string) => void;
  onUsageLimit?: (message: string) => void;
}

export function ResultsSidePanel({
  runId,
  chatSessionKey,
  disabled,
  saveAction,
  onRefined,
  onUsageLimit,
}: ResultsSidePanelProps) {
  const [tab, setTab] = useState<SideTab>("refine");

  return (
    <aside className="w-full lg:w-[340px] shrink-0 flex flex-col border-t lg:border-t-0 lg:border-l border-border bg-card min-h-0 max-h-[50vh] lg:max-h-none">
      <div className="shrink-0 flex gap-4 border-b border-border px-4 pt-3">
        {(
          [
            { id: "refine", label: "Refine" },
            { id: "chat", label: "Ask docs" },
          ] as const
        ).map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setTab(item.id)}
            className={cn(
              "pb-2 text-sm font-medium transition-colors border-b-2 -mb-px",
              tab === item.id
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className={cn("flex flex-1 flex-col min-h-0", tab !== "refine" && "hidden")}>
        <RefineChatPanel
          runId={runId}
          chatSessionKey={chatSessionKey}
          disabled={disabled}
          saveAction={saveAction}
          variant="panel"
          onRefined={onRefined}
          onUsageLimit={onUsageLimit}
        />
      </div>

      <div className={cn("flex flex-1 flex-col min-h-0", tab !== "chat" && "hidden")}>
        <DocChatPanel runId={runId} disabled={disabled} variant="panel" />
      </div>
    </aside>
  );
}
