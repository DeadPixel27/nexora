"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { ExportBar } from "@/components/export-bar";
import { ALL_RESULTS_ID } from "@/components/results/all-results-id";
import { DocumentTabPanel } from "@/components/results/document-tab";
import { DocResultsPane } from "@/components/results/doc-results-pane";
import { DocsPanel } from "@/components/results/docs-panel";
import { ResultsTabPanel } from "@/components/results/results-tab";
import { useRunResultsContext } from "@/components/results/run-results-context";
import { StepStatusList } from "@/components/run-display";
import { TopBar } from "@/components/top-bar";
import { getUploadDocuments, type RunResponse } from "@/lib/api";

const STORAGE_NAME_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(\.[a-z0-9]+)?$/i;

function looksLikeStorageName(name: string): boolean {
  return STORAGE_NAME_RE.test(name);
}

function pickDisplayName(...candidates: Array<string | undefined | null>): string | undefined {
  const usable = candidates
    .map((c) => (typeof c === "string" ? c.trim() : ""))
    .filter(Boolean);
  return (
    usable.find((name) => !looksLikeStorageName(name)) ?? usable[0] ?? undefined
  );
}

function formatRunTime(createdAt: string | null | undefined): string | null {
  if (!createdAt) return null;
  const date = new Date(createdAt);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function PipelinePanel({
  isRunning,
  title = "Pipeline",
}: {
  isRunning: boolean;
  title?: string;
}) {
  const { runState } = useRunResultsContext();
  const run = runState.run;
  if (!run) return null;

  return (
    <>
      <div className="shrink-0 flex gap-4 border-b border-border px-4">
        <span className="pb-2 text-sm font-medium border-b-2 border-primary text-primary -mb-px">
          {title}
        </span>
      </div>
      <div className="flex-1 overflow-auto p-4 space-y-4 min-h-0">
        {isRunning && (
          <div className="flex items-center gap-2 text-muted-foreground text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            Pipeline running…
          </div>
        )}
        <StepStatusList
          steps={run.steps}
          plannedSteps={run.planned_steps}
          showProgress={isRunning}
        />
        {run.status === "failed" && run.error_message && (
          <p className="text-sm text-destructive">{run.error_message}</p>
        )}
      </div>
    </>
  );
}

function inferPipelineExtractionMethod(
  run?: RunResponse | null,
): string | undefined {
  if (!run?.steps?.length) return undefined;
  const completed = run.steps.filter((s) => s.status === "completed");
  if (completed.some((s) => s.agent_type === "processor.ocr")) {
    return "rapidocr";
  }
  if (completed.some((s) => s.agent_type === "processor.text_extract")) {
    return "pymupdf";
  }
  return undefined;
}

function flagCountForRows(rows: Record<string, unknown>[]): number {
  return rows.reduce((count, row) => {
    const flags = row.flags;
    if (flags && typeof flags === "object" && !Array.isArray(flags)) {
      return (
        count +
        Object.values(flags as Record<string, unknown>).filter(Boolean).length
      );
    }
    if (Array.isArray(flags)) return count + flags.length;
    return count;
  }, 0);
}

interface RunResultsFrameProps {
  refinePanel: ReactNode;
}

export function RunResultsFrame({ refinePanel }: RunResultsFrameProps) {
  const { runState, pageConfig, setHasCompletedResults, setRefineDisabled } =
    useRunResultsContext();
  const { run, isRunning, loading, error } = runState;

  const [selectedId, setSelectedId] = useState<string>(ALL_RESULTS_ID);
  const [docNames, setDocNames] = useState<Record<string, string>>({});
  const [docMethods, setDocMethods] = useState<Record<string, string>>({});
  const [docTypes, setDocTypes] = useState<Record<string, string>>({});
  const [refineUnlocked, setRefineUnlocked] = useState(false);
  const [lastCompletedRun, setLastCompletedRun] = useState(
    run?.status === "completed" ? run : null,
  );

  useEffect(() => {
    if (run?.status === "completed") {
      setRefineUnlocked(true);
      setLastCompletedRun(run);
    }
  }, [run]);

  useEffect(() => {
    setRefineDisabled(isRunning);
  }, [isRunning, setRefineDisabled]);

  const displayRun =
    run?.status === "completed" ? run : (lastCompletedRun ?? run);
  const rows = displayRun?.result?.rows ?? [];
  const flagCount = flagCountForRows(rows);
  const filteredCount = displayRun?.result?.filtered_count ?? 0;

  const hasCompletedResults =
    refineUnlocked && displayRun?.status === "completed";
  const isRerunning = isRunning && hasCompletedResults;
  const showPipelineProgress =
    !hasCompletedResults &&
    Boolean(run) &&
    (isRunning || run!.status !== "completed");

  useEffect(() => {
    setHasCompletedResults(hasCompletedResults);
  }, [hasCompletedResults, setHasCompletedResults]);

  const uploadId = run?.upload_id || displayRun?.upload_id;

  useEffect(() => {
    if (!uploadId) return;
    getUploadDocuments(uploadId)
      .then((res) => {
        const names: Record<string, string> = {};
        const methods: Record<string, string> = {};
        const types: Record<string, string> = {};
        for (const doc of res.documents) {
          names[doc.document_id] = doc.filename;
          if (doc.extraction_method) {
            methods[doc.document_id] = doc.extraction_method;
          }
          if (doc.file_type) {
            types[doc.document_id] = doc.file_type;
          }
        }
        setDocNames(names);
        setDocMethods(methods);
        setDocTypes(types);
      })
      .catch(() => {
        /* optional */
      });
  }, [uploadId]);

  const docSourceRun = hasCompletedResults ? displayRun : run;
  const fallbackMethod = inferPipelineExtractionMethod(displayRun ?? run);
  const validationWarnings = displayRun?.result?.validation_warnings;
  const files = useMemo(() => {
    const fromDocs: Record<string, string> = {};
    for (const doc of docSourceRun?.documents ?? []) {
      if (doc.document_id && doc.filename) {
        fromDocs[doc.document_id] = doc.filename;
      }
    }
    const fromRows: Record<string, string> = {};
    for (const row of rows) {
      const id = typeof row.document_id === "string" ? row.document_id : "";
      const name = typeof row.filename === "string" ? row.filename : "";
      if (id && name) fromRows[id] = name;
    }
    return (docSourceRun?.document_ids ?? []).map((id) => ({
      id,
      name:
        pickDisplayName(fromDocs[id], fromRows[id], docNames[id]) ??
        id.slice(0, 8),
      warningCount: validationWarnings?.[id]?.length ?? 0,
    }));
  }, [
    docSourceRun?.document_ids,
    docSourceRun?.documents,
    rows,
    docNames,
    validationWarnings,
  ]);
  const totalWarnings = useMemo(
    () =>
      Object.values(validationWarnings ?? {}).reduce(
        (sum, list) => sum + list.length,
        0,
      ),
    [validationWarnings],
  );

  const showDocsPanel = files.length > 0;
  const showingAll = selectedId === ALL_RESULTS_ID;
  const selectedDocId = showingAll ? null : selectedId;

  const docRows = useMemo(() => {
    if (!selectedDocId) return [];
    return rows.filter((row) => row.document_id === selectedDocId);
  }, [rows, selectedDocId]);

  const docFlagCount = flagCountForRows(docRows);

  const statusBadge =
    displayRun?.status === "completed" ? (
      <span className="v2-badge-success">{displayRun.status}</span>
    ) : displayRun?.status === "running" ? (
      <span className="v2-badge-muted">{displayRun.status}</span>
    ) : displayRun ? (
      <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold bg-destructive/10 text-destructive">
        {displayRun.status}
      </span>
    ) : null;

  const meta = displayRun
    ? [
        displayRun.task_description,
        `${displayRun.document_ids.length} documents`,
        formatRunTime(displayRun.created_at),
      ]
        .filter(Boolean)
        .join(" · ")
    : undefined;

  if (loading && !run) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error && !run) {
    return (
      <div className="flex flex-1 items-center justify-center p-4">
        <p className="text-destructive" role="alert">
          {error}
        </p>
      </div>
    );
  }

  if (!run || !displayRun) return null;

  return (
    <>
      <TopBar
        backHref={pageConfig.backHref}
        backLabel={pageConfig.backLabel}
        title={pageConfig.title ?? "Pipeline Results"}
        meta={meta}
        badge={
          <>
            {statusBadge}
            {pageConfig.versionLabel && (
              <span className="v2-badge-success ml-1">
                {pageConfig.versionLabel}
              </span>
            )}
          </>
        }
      />

      {hasCompletedResults && (
        <ExportBar
          runId={displayRun.run_id}
          rows={rows}
          saveAction={pageConfig.saveAction ?? "workflow"}
          workflowId={pageConfig.workflowId ?? displayRun.workflow_id ?? undefined}
          defaultEmail={pageConfig.defaultEmail}
          defaultSheetsUrl={pageConfig.defaultSheetsUrl}
          defaultSheetName={pageConfig.defaultSheetName}
          onWorkflowSaved={pageConfig.onWorkflowSaved}
          onVersionSaved={pageConfig.onVersionSaved}
        />
      )}

      <div className="flex flex-1 min-h-0 flex-col lg:flex-row">
        <div className="flex flex-1 min-h-0 min-w-0">
        {showDocsPanel && (
          <DocsPanel
            files={files}
            selectedId={selectedId}
            totalWarnings={totalWarnings}
            onSelect={setSelectedId}
          />
        )}

        <div className="flex flex-1 flex-col min-w-0 min-h-0">
          {isRerunning && (
            <div className="shrink-0 flex items-center gap-2 border-b border-primary/20 bg-primary/5 px-4 py-2 text-xs text-primary">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>
                Re-running extraction for all documents with your refinements…
              </span>
            </div>
          )}
          {showPipelineProgress ? (
            <PipelinePanel
              isRunning={isRunning}
              title={hasCompletedResults ? "Re-running" : "Pipeline"}
            />
          ) : showingAll || !selectedDocId ? (
            <ResultsTabPanel
              rows={rows}
              flagCount={flagCount}
              filteredCount={filteredCount}
              isUpdating={isRerunning}
              fieldConfidence={displayRun?.result?.field_confidence}
              validationWarnings={displayRun?.result?.validation_warnings}
            />
          ) : (
            <div className="flex flex-1 min-h-0 flex-col md:flex-row">
              <div className="flex flex-col min-h-0 min-w-0 md:w-1/2 md:max-w-[50%] h-[45vh] md:h-auto">
                <DocumentTabPanel
                  uploadId={displayRun.upload_id}
                  documentId={selectedDocId}
                  filename={
                    files.find((f) => f.id === selectedDocId)?.name ??
                    docNames[selectedDocId] ??
                    "Document"
                  }
                  fileType={docTypes[selectedDocId]}
                  extractionMethod={
                    docMethods[selectedDocId] ?? fallbackMethod
                  }
                />
              </div>
              <DocResultsPane
                rows={docRows}
                flagCount={docFlagCount}
                filteredCount={filteredCount}
                isUpdating={isRerunning}
                fieldConfidence={displayRun?.result?.field_confidence}
                validationWarnings={
                  displayRun?.result?.validation_warnings?.[selectedDocId]
                }
                documentWarnings={displayRun?.result?.validation_warnings}
              />
            </div>
          )}
        </div>
        </div>
        {refinePanel}
      </div>
    </>
  );
}
