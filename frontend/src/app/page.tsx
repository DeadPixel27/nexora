"use client";

import { ArrowRight, ChevronDown, ChevronUp, Loader2, Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { UsageLimitModal } from "@/components/modals/usage-limit-modal";
import { UploadZone } from "@/components/upload-zone";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSignIn } from "@/hooks/use-sign-in";
import {
  ApiError,
  getAccessToken,
  getTemplate,
  listTemplates,
  runAdhoc,
  runTemplate,
  uploadFiles,
  type PipelineTemplateSummary,
} from "@/lib/api";
import { FREE_PAGES_PER_MONTH } from "@/lib/free-plan";
import { savePendingRun } from "@/lib/pending-run";
import { resumePendingRun } from "@/lib/resume-pending-run";
import { toastError } from "@/lib/toast";
import { ensureUser, SignInRequiredError } from "@/lib/user-session";
import { cn } from "@/lib/utils";

/** SMB money-ops templates shown prominently at launch. */
const PRIMARY_TEMPLATE_IDS = new Set([
  "invoice",
  "receipt",
  "purchase_order",
  "bank_statement",
]);

export default function HomePage() {
  const router = useRouter();
  const { openSignIn } = useSignIn();
  const [files, setFiles] = useState<File[]>([]);
  const [task, setTask] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(
    null,
  );
  const [templates, setTemplates] = useState<PipelineTemplateSummary[]>([]);
  const [showMoreTemplates, setShowMoreTemplates] = useState(false);
  const [loading, setLoading] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);
  const [showUsageLimit, setShowUsageLimit] = useState(false);
  const [usageLimitMsg, setUsageLimitMsg] = useState("");
  const resumeStarted = useRef(false);
  const templatesLoaded = useRef(false);

  const applyTemplate = useCallback(async (templateId: string) => {
    setSelectedTemplateId(templateId);
    try {
      const template = await getTemplate(templateId);
      setTask(template.default_task || template.task_description || "");
    } catch {
      /* keep current task */
    }
  }, []);

  useEffect(() => {
    if (templatesLoaded.current) return;
    templatesLoaded.current = true;
    listTemplates()
      .then((data) => setTemplates(data.templates))
      .catch(() => {
        /* templates optional */
      });
  }, []);

  const primaryTemplates = templates.filter((t) =>
    PRIMARY_TEMPLATE_IDS.has(t.template_id),
  );
  const moreTemplates = templates.filter(
    (t) => !PRIMARY_TEMPLATE_IDS.has(t.template_id),
  );

  async function handleSelectTemplate(templateId: string) {
    if (selectedTemplateId === templateId) {
      setSelectedTemplateId(null);
      setTask("");
      return;
    }
    await applyTemplate(templateId);
  }

  const promptSignIn = useCallback(
    async (intent: {
      kind: "run" | "sample";
      files?: File[];
      templateId?: string | null;
      task?: string;
    }) => {
      try {
        await savePendingRun(intent);
      } catch {
        /* best-effort; still open sign-in */
      }
      openSignIn();
    },
    [openSignIn],
  );

  const handleApiError = useCallback(
    async (
      err: unknown,
      intent?: {
        kind: "run" | "sample";
        files?: File[];
        templateId?: string | null;
        task?: string;
      },
    ) => {
      if (err instanceof SignInRequiredError) {
        if (intent) {
          await promptSignIn(intent);
        } else {
          openSignIn();
        }
        return;
      }
      if (err instanceof ApiError) {
        switch (err.status) {
          case 401:
            if (intent) {
              await promptSignIn(intent);
            } else {
              openSignIn();
            }
            break;
          case 429:
            setUsageLimitMsg(err.message);
            setShowUsageLimit(true);
            break;
          case 503:
            toastError(
              "Service is temporarily at capacity. Please try again in a few minutes.",
            );
            break;
          default:
            toastError(err.message);
        }
      } else {
        toastError(
          err instanceof Error
            ? err.message
            : "Something went wrong. Please try again.",
        );
      }
    },
    [openSignIn, promptSignIn],
  );

  const executeSample = useCallback(async () => {
    setPhase("Loading sample…");
    const response = await fetch("/samples/sample-invoice.pdf");
    if (!response.ok) {
      throw new Error("Sample invoice is missing.");
    }
    const blob = await response.blob();
    const file = new File([blob], "sample-invoice.pdf", {
      type: "application/pdf",
    });
    setPhase("Uploading sample…");
    const upload = await uploadFiles([file]);
    setPhase("Starting pipeline…");
    const run = await runTemplate(upload.upload_id, "invoice");
    router.push(`/results/${run.run_id}`);
  }, [router]);

  const executeRun = useCallback(
    async (runFiles: File[], runTask: string, templateId: string | null) => {
      setPhase("Uploading documents…");
      const upload = await uploadFiles(runFiles);
      setPhase("Starting pipeline…");
      const run = templateId
        ? await runTemplate(upload.upload_id, templateId)
        : await runAdhoc(upload.upload_id, runTask.trim());
      router.push(`/results/${run.run_id}`);
    },
    [router],
  );

  async function handleTrySample() {
    const intent = { kind: "sample" as const };
    setLoading(true);
    try {
      await ensureUser();
      await executeSample();
    } catch (err) {
      await handleApiError(err, intent);
    } finally {
      setLoading(false);
      setPhase(null);
    }
  }

  async function handleRun() {
    if (!files.length) {
      toastError("Add at least one document.");
      return;
    }
    if (!selectedTemplateId && !task.trim()) {
      toastError("Describe what you want extracted or done.");
      return;
    }

    const intent = {
      kind: "run" as const,
      files,
      templateId: selectedTemplateId,
      task: task.trim(),
    };

    setLoading(true);
    try {
      await ensureUser();
      await executeRun(files, task, selectedTemplateId);
    } catch (err) {
      await handleApiError(err, intent);
    } finally {
      setLoading(false);
      setPhase(null);
    }
  }

  useEffect(() => {
    if (!getAccessToken()) return;
    if (resumeStarted.current) return;
    resumeStarted.current = true;

    void (async () => {
      try {
        setLoading(true);
        setPhase("Starting your run…");
        const runId = await resumePendingRun();
        if (!runId) {
          setLoading(false);
          setPhase(null);
          return;
        }
        router.push(`/results/${runId}`);
      } catch (err) {
        setLoading(false);
        setPhase(null);
        await handleApiError(err);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- run once on mount
  }, []);

  return (
    <div className="v2-page">
      <main className="flex flex-1 flex-col items-center overflow-y-auto px-4 py-10">
        <div className="w-full max-w-[700px] space-y-6">
          <div className="text-center space-y-3">
            <h1 className="font-serif text-[30px] font-semibold leading-tight tracking-tight">
              Extract AP documents.{" "}
              <em className="text-primary not-italic">Send them anywhere.</em>
            </h1>
            <p className="text-sm text-muted-foreground max-w-[540px] mx-auto">
              Upload invoices, receipts, POs, and bank statements. Nexora extracts
              structured fields, pushes to Google Sheets, emails results to your
              team, or runs a workflow when you forward attachments to inbound
              email.
            </p>
          </div>

          <UploadZone files={files} onFilesChange={setFiles} disabled={loading} />

          {templates.length > 0 && (
            <div className="space-y-3">
              <p className="text-center text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Document type
              </p>
              <div className="flex flex-wrap gap-2 justify-center">
                {primaryTemplates.map((template) => (
                  <button
                    key={template.template_id}
                    type="button"
                    disabled={loading}
                    onClick={() => void handleSelectTemplate(template.template_id)}
                    className={cn(
                      "px-4 py-2 rounded-lg text-sm font-semibold border transition-all",
                      "border-border bg-card hover:border-primary hover:bg-primary/5",
                      selectedTemplateId === template.template_id &&
                        "border-primary bg-primary/10 text-primary shadow-sm",
                    )}
                  >
                    {template.name}
                  </button>
                ))}
              </div>

              {moreTemplates.length > 0 && (
                <div className="space-y-2">
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => setShowMoreTemplates((v) => !v)}
                    className="mx-auto flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    More templates
                    {showMoreTemplates ? (
                      <ChevronUp className="h-3.5 w-3.5" />
                    ) : (
                      <ChevronDown className="h-3.5 w-3.5" />
                    )}
                  </button>
                  {showMoreTemplates && (
                    <div className="flex flex-wrap gap-2 justify-center">
                      {moreTemplates.map((template) => (
                        <button
                          key={template.template_id}
                          type="button"
                          disabled={loading}
                          onClick={() =>
                            void handleSelectTemplate(template.template_id)
                          }
                          className={cn(
                            "px-3 py-1.5 rounded-md text-[11px] font-semibold border transition-all",
                            "border-border bg-card hover:border-primary hover:bg-primary/5",
                            selectedTemplateId === template.template_id &&
                              "border-primary bg-primary/10 text-primary",
                          )}
                        >
                          {template.name}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              <div className="flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void handleTrySample()}
                  disabled={loading}
                  className="gap-2"
                >
                  <Play className="h-4 w-4" />
                  Try with sample invoice
                </Button>
              </div>
            </div>
          )}

          {selectedTemplateId ? (
            <div className="space-y-2">
              <div className="rounded-lg border border-border bg-muted/30 px-4 py-3 text-sm text-muted-foreground leading-relaxed">
                {task || "Loading template instructions…"}
              </div>
              <p className="text-center text-xs text-muted-foreground">
                Template instructions are fixed. Customize on the results page
                via <span className="font-medium text-foreground">Refine</span>.
                Click the template again to clear and use your own task.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <Input
                placeholder="Extract vendor name, amount, due date…"
                value={task}
                onChange={(e) => setTask(e.target.value)}
                disabled={loading}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleRun();
                }}
                className="w-full"
              />
            </div>
          )}

          <div className="flex justify-center">
            <Button
              onClick={() => void handleRun()}
              disabled={loading}
              size="lg"
              className="min-w-[140px]"
            >
              {loading ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {phase ?? "Running…"}
                </>
              ) : (
                <>
                  Run
                  <ArrowRight className="ml-2 h-4 w-4" />
                </>
              )}
            </Button>
          </div>

          <p className="text-center text-xs text-muted-foreground pt-2">
            {FREE_PAGES_PER_MONTH} pages free · Results in seconds
          </p>
        </div>
      </main>
      <UsageLimitModal
        open={showUsageLimit}
        onClose={() => setShowUsageLimit(false)}
        message={usageLimitMsg}
      />
    </div>
  );
}
