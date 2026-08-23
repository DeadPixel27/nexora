"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

import {
  loadResultsLayout,
  saveResultsLayout,
  type ResultsLayout,
} from "@/components/results/results-layout";
import { ResultsLayoutToggle } from "@/components/results/results-layout-toggle";
import { ResultsVerticalList } from "@/components/results/results-vertical";
import { ResultsTable } from "@/components/run-display";
import type { FieldConfidence, ValidationWarning } from "@/lib/api";

interface DocResultsPaneProps {
  rows: Record<string, unknown>[];
  flagCount: number;
  filteredCount?: number;
  isUpdating?: boolean;
  fieldConfidence?: Record<string, FieldConfidence>;
  validationWarnings?: ValidationWarning[];
  documentWarnings?: Record<string, ValidationWarning[]>;
}

function flattenDocWarnings(
  warnings?: ValidationWarning[],
): ValidationWarning[] {
  return warnings ?? [];
}

export function DocResultsPane({
  rows,
  flagCount,
  filteredCount = 0,
  isUpdating = false,
  fieldConfidence,
  validationWarnings,
  documentWarnings,
}: DocResultsPaneProps) {
  const [layout, setLayout] = useState<ResultsLayout>("vertical");

  useEffect(() => {
    setLayout(loadResultsLayout());
  }, []);

  const onLayoutChange = (next: ResultsLayout) => {
    setLayout(next);
    saveResultsLayout(next);
  };

  const allWarnings = flattenDocWarnings(validationWarnings);

  return (
    <div className="relative flex flex-col flex-1 min-h-0 min-w-0 overflow-hidden border-l border-border bg-background">
      <div className="shrink-0 flex flex-wrap items-center gap-2 px-3 py-2 border-b border-border">
        <ResultsLayoutToggle value={layout} onChange={onLayoutChange} />
        <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium">
          {rows.length} row{rows.length === 1 ? "" : "s"}
        </span>
        <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium">
          {flagCount} flagged
        </span>
        {filteredCount > 0 && (
          <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
            {filteredCount} filtered by rules
          </span>
        )}
      </div>

      {allWarnings.length > 0 && (
        <div className="flex items-center gap-2 px-3 py-2 border-b border-amber-200 bg-amber-50 text-xs text-amber-700">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span>
            {allWarnings.length} field
            {allWarnings.length > 1 ? "s" : ""} flagged for review
          </span>
        </div>
      )}

      <div className="flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden p-3">
        {layout === "vertical" ? (
          <ResultsVerticalList
            rows={rows}
            fieldConfidence={fieldConfidence}
            validationWarnings={documentWarnings}
          />
        ) : (
          <ResultsTable
            rows={rows}
            fieldConfidence={fieldConfidence}
            validationWarnings={documentWarnings}
          />
        )}
      </div>

      {isUpdating && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/60 backdrop-blur-[1px]">
          <div className="flex items-center gap-2 rounded-lg border border-border bg-card px-4 py-2 text-sm text-muted-foreground shadow-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            Updating results…
          </div>
        </div>
      )}
    </div>
  );
}
