"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";

import { type SaveAction } from "@/components/export-bar";
import { UsageLimitModal } from "@/components/modals/usage-limit-modal";
import { RunResultsFrame } from "@/components/results/run-results-frame";
import { ResultsSidePanel } from "@/components/results/results-side-panel";
import type { RunResponse } from "@/lib/api";

export interface RunResultsPageConfig {
  backHref: string;
  backLabel?: string;
  title?: string;
  saveAction?: SaveAction;
  workflowId?: string;
  versionLabel?: string;
  defaultEmail?: string;
  defaultSheetsUrl?: string;
  defaultSheetName?: string;
  onWorkflowSaved?: (workflowId: string) => void;
  onVersionSaved?: () => void;
}

export interface RunResultsRunState {
  run: RunResponse | null;
  isRunning: boolean;
  loading: boolean;
  error: string | null;
}

interface RunResultsContextValue {
  activeRunId: string;
  refining: boolean;
  setRefining: (value: boolean) => void;
  runState: RunResultsRunState;
  setRunState: (state: RunResultsRunState) => void;
  pageConfig: RunResultsPageConfig;
  setPageConfig: (config: RunResultsPageConfig) => void;
  hasCompletedResults: boolean;
  setHasCompletedResults: (value: boolean) => void;
  refineDisabled: boolean;
  setRefineDisabled: (value: boolean) => void;
}

const defaultPageConfig: RunResultsPageConfig = {
  backHref: "/",
};

const defaultRunState: RunResultsRunState = {
  run: null,
  isRunning: false,
  loading: true,
  error: null,
};

const RunResultsContext = createContext<RunResultsContextValue | null>(null);

export function useRunResultsContext() {
  const context = useContext(RunResultsContext);
  if (!context) {
    throw new Error("useRunResultsContext must be used within RunResultsShell");
  }
  return context;
}

function RefinePlaceholder({ running }: { running: boolean }) {
  return (
    <aside className="w-full lg:w-[340px] shrink-0 flex flex-col border-t lg:border-t-0 lg:border-l border-border bg-card min-h-0 max-h-[42vh] lg:max-h-none">
      <div className="shrink-0 p-4 border-b border-border space-y-2">
        <h2 className="font-serif text-base font-semibold">Refine</h2>
        <p className="text-xs text-muted-foreground">
          {running
            ? "Chat refinement unlocks when extraction finishes."
            : "Describe what to change once results are ready."}
        </p>
      </div>
      <div className="flex-1 flex items-center justify-center p-6 text-center">
        {running && (
          <div className="flex flex-col items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Pipeline running…</span>
          </div>
        )}
      </div>
    </aside>
  );
}

interface RunResultsShellProps {
  children: ReactNode;
  makeRunHref: (runId: string) => string;
}

export function RunResultsShell({
  children,
  makeRunHref,
}: RunResultsShellProps) {
  const router = useRouter();
  const params = useParams();
  const routeRunId = params.runId as string;

  const [activeRunId, setActiveRunId] = useState(routeRunId);
  const [refining, setRefining] = useState(false);
  const [runState, setRunState] = useState<RunResultsRunState>(defaultRunState);
  const [pageConfig, setPageConfig] =
    useState<RunResultsPageConfig>(defaultPageConfig);
  const [hasCompletedResults, setHasCompletedResults] = useState(false);
  const [refineDisabled, setRefineDisabled] = useState(false);
  const [showUsageLimit, setShowUsageLimit] = useState(false);
  const [usageLimitMsg, setUsageLimitMsg] = useState("");
  const chatSessionKeyRef = useRef(
    typeof window !== "undefined"
      ? `${routeRunId}-${Date.now()}`
      : routeRunId,
  );
  const refiningRef = useRef(false);

  refiningRef.current = refining;

  useEffect(() => {
    setActiveRunId(routeRunId);
    if (!refiningRef.current) {
      chatSessionKeyRef.current = `${routeRunId}-${Date.now()}`;
      setRunState(defaultRunState);
    }
  }, [routeRunId]);

  const handleRefined = useCallback((newRunId: string) => {
    setRefining(true);
    setActiveRunId(newRunId);
    // Don't router.replace yet - wait until the child run completes
    // to avoid loading flicker and page-refresh feel.
  }, []);

  useEffect(() => {
    // Update URL after refinement completes (deferred from handleRefined)
    if (!refining && activeRunId !== routeRunId) {
      router.replace(makeRunHref(activeRunId), { scroll: false });
    }
  }, [refining, activeRunId, routeRunId, makeRunHref, router]);

  const contextValue = useMemo(
    () => ({
      activeRunId,
      refining,
      setRefining,
      runState,
      setRunState,
      pageConfig,
      setPageConfig,
      hasCompletedResults,
      setHasCompletedResults,
      refineDisabled,
      setRefineDisabled,
    }),
    [
      activeRunId,
      refining,
      runState,
      pageConfig,
      hasCompletedResults,
      refineDisabled,
    ],
  );

  return (
    <RunResultsContext.Provider value={contextValue}>
      <div className="v2-page">
        <RunResultsFrame
          refinePanel={
            hasCompletedResults ? (
              <ResultsSidePanel
                runId={activeRunId}
                chatSessionKey={chatSessionKeyRef.current}
                disabled={refineDisabled}
                saveAction={pageConfig.saveAction ?? "workflow"}
                onRefined={(newRunId) => handleRefined(newRunId)}
                onUsageLimit={(message) => {
                  setUsageLimitMsg(message);
                  setShowUsageLimit(true);
                }}
              />
            ) : (
              <RefinePlaceholder running={refineDisabled} />
            )
          }
        />
      </div>
      {children}
      <UsageLimitModal
        open={showUsageLimit}
        onClose={() => setShowUsageLimit(false)}
        message={usageLimitMsg}
      />
    </RunResultsContext.Provider>
  );
}
