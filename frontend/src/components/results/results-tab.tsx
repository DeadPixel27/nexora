"use client";

import { AlertTriangle, Loader2 } from "lucide-react";

import { ResultsTable } from "@/components/run-display";
import type { FieldConfidence, ValidationWarning } from "@/lib/api";

interface ResultsTabPanelProps {
  rows: Record<string, unknown>[];
  flagCount: number;
  filteredCount?: number;
  runtimeLabel?: string;
  isUpdating?: boolean;
  fieldConfidence?: Record<string, FieldConfidence>;
  validationWarnings?: Record<string, ValidationWarning[]>;
}

function flattenWarnings(
  warnings?: Record<string, ValidationWarning[]>,
): ValidationWarning[] {
  if (!warnings) return [];
  return Object.values(warnings).flat();
}

export function ResultsTabPanel({
  rows,
  flagCount,
  filteredCount = 0,
  runtimeLabel,
  isUpdating = false,
  fieldConfidence,
  validationWarnings,
}: ResultsTabPanelProps) {
  const allWarnings = flattenWarnings(validationWarnings);

  return (
    <div className="relative flex flex-col flex-1 min-h-0 overflow-hidden">
      {allWarnings.length > 0 && (
        <div className="flex items-center gap-2 px-4 py-2 border-b border-amber-200 bg-amber-50 text-xs text-amber-700">
          <AlertTriangle className="h-3.5 w-3.5" />
          <span>
            {allWarnings.length} field
            {allWarnings.length > 1 ? "s" : ""} flagged for review
          </span>
        </div>
      )}
      <div className="flex flex-wrap gap-2 px-4 py-3 border-b border-border">
        <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium">
          {rows.length} rows extracted
        </span>
        <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium">
          {flagCount} flagged
        </span>
        {filteredCount > 0 && (
          <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
            {filteredCount} row{filteredCount === 1 ? "" : "s"} filtered by rules
          </span>
        )}
        {runtimeLabel && (
          <span className="inline-flex items-center rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium">
            {runtimeLabel}
          </span>
        )}
      </div>
      <div className="flex-1 overflow-auto p-4">
        <ResultsTable
          rows={rows}
          fieldConfidence={fieldConfidence}
          validationWarnings={validationWarnings}
        />
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
