"use client";

import { Check, Loader2, MessageSquare, Play, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import type { SaveAction } from "@/components/export-bar";
import {
  ApiError,
  refinePlan,
  refineRun,
  type RefinePlanMessage,
  type RefinePreviewRow,
} from "@/lib/api";
import { toastError } from "@/lib/toast";
import { cn } from "@/lib/utils";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  planned_changes?: string[];
  preview?: RefinePreviewRow[];
}

function formatPreviewValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value || "—";
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    const text = JSON.stringify(value);
    return text.length > 80 ? `${text.slice(0, 77)}…` : text;
  } catch {
    return String(value);
  }
}

function PreviewPanel({ preview }: { preview: RefinePreviewRow[] }) {
  if (preview.length === 0) return null;

  return (
    <div className="mt-2 ml-1 rounded-md border border-primary/20 bg-primary/5 p-2.5 space-y-2">
      <p className="text-xs font-medium text-foreground">Preview after apply</p>
      {preview.map((row) => (
        <div key={row.document_id} className="space-y-1">
          {row.filename && (
            <p className="text-[11px] text-muted-foreground truncate">{row.filename}</p>
          )}
          {row.fields.map((item) => (
            <div
              key={`${row.document_id}-${item.field}`}
              className="text-xs font-mono leading-relaxed"
            >
              <span className="text-muted-foreground">{item.field}:</span>{" "}
              <span className="text-destructive/80 line-through">
                {formatPreviewValue(item.before)}
              </span>
              <span className="text-muted-foreground"> → </span>
              <span className="text-green-700 dark:text-green-400 font-semibold">
                {formatPreviewValue(item.after)}
              </span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

interface RefineChatPanelProps {
  runId: string;
  chatSessionKey?: string;
  disabled?: boolean;
  saveAction?: SaveAction;
  variant?: "card" | "panel";
  onRefined: (newRunId: string, summary: string) => void;
  onUsageLimit?: (message: string) => void;
}

function RefineSaveDisclaimer({ saveAction }: { saveAction?: SaveAction }) {
  if (saveAction === "version") {
    return (
      <p className="v2-callout-warning text-xs leading-relaxed">
        <span className="font-semibold">Draft only.</span> Refinements update this
        run&apos;s results on screen. Your saved workflow version stays the same until
        you click <span className="font-semibold">Save as New Version</span>.
      </p>
    );
  }

  if (saveAction === "workflow") {
    return (
      <p className="v2-callout-warning text-xs leading-relaxed">
        <span className="font-semibold">Draft only.</span> Refinements update this
        run&apos;s results on screen. Nothing is saved as a reusable workflow until
        you click <span className="font-semibold">Save as Workflow</span>.
      </p>
    );
  }

  return (
    <p className="v2-callout-warning text-xs leading-relaxed">
      <span className="font-semibold">Draft only.</span> Refinements update this run
      only. The original run and any saved workflow stay unchanged until you explicitly
      save.
    </p>
  );
}

export function RefineChatPanel({
  runId,
  chatSessionKey,
  disabled,
  saveAction,
  variant = "card",
  onRefined,
  onUsageLimit,
}: RefineChatPanelProps) {
  const sessionKey = chatSessionKey ?? runId;
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [readyToApply, setReadyToApply] = useState(false);
  const [accumulatedInstruction, setAccumulatedInstruction] = useState("");

  useEffect(() => {
    setHistory([]);
    setMessage("");
    setReadyToApply(false);
    setAccumulatedInstruction("");
  }, [sessionKey]);

  useEffect(() => {
    if (!loading && !applying && !disabled) {
      // Use requestAnimationFrame to ensure focus happens after DOM settles
      // (Apply button rendering can steal focus on state change)
      requestAnimationFrame(() => {
        textareaRef.current?.focus();
      });
    }
  }, [loading, applying, disabled, readyToApply, history.length]);

  async function handleSend() {
    const text = message.trim();
    if (!text || loading || applying) return;

    const planHistory: RefinePlanMessage[] = [
      ...history.map((item) => ({ role: item.role, content: item.text })),
      { role: "user", content: text },
    ];

    setLoading(true);
    setMessage("");
    setHistory((prev) => [...prev, { role: "user", text }]);

    try {
      const result = await refinePlan(runId, text, planHistory);

      setHistory((prev) => [
        ...prev,
        {
          role: "assistant",
          text: result.message,
          planned_changes: result.planned_changes,
          preview: result.ready ? result.preview : undefined,
        },
      ]);

      if (result.ready && result.accumulated_instruction) {
        setReadyToApply(true);
        setAccumulatedInstruction(result.accumulated_instruction);
      } else if (result.ready) {
        setReadyToApply(true);
        setAccumulatedInstruction(
          result.accumulated_instruction ||
            `Apply these refinements: ${(result.planned_changes || []).join("; ")}. User request: ${text}`,
        );
      } else {
        setReadyToApply(false);
        setAccumulatedInstruction("");
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        onUsageLimit?.(e.message);
      } else if (e instanceof ApiError && e.status === 503) {
        toastError("Service is temporarily at capacity. Try again shortly.");
      } else {
        toastError(e instanceof ApiError ? e.message : "Plan mode failed.");
      }
      setHistory((prev) => prev.slice(0, -1));
      setMessage(text);
    } finally {
      setLoading(false);
      // Explicit refocus after all state updates settle
      requestAnimationFrame(() => {
        textareaRef.current?.focus();
      });
    }
  }

  async function handleApply() {
    if (!accumulatedInstruction || applying) return;

    setApplying(true);
    setHistory((prev) => [
      ...prev,
      {
        role: "assistant",
        text: "⏳ Applying changes and re-running extraction for all documents...",
      },
    ]);

    try {
      const result = await refineRun(runId, accumulatedInstruction);
      setHistory((prev) => {
        // Replace the "applying..." message with the real summary
        const updated = prev.slice(0, -1);
        return [
          ...updated,
          { role: "assistant", text: `✓ ${result.refine_summary}` },
        ];
      });
      setReadyToApply(false);
      setAccumulatedInstruction("");
      onRefined(result.run.run_id, result.refine_summary);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        onUsageLimit?.(e.message);
      } else if (e instanceof ApiError && e.status === 503) {
        toastError("Service is temporarily at capacity. Try again shortly.");
      } else {
        toastError(e instanceof ApiError ? e.message : "Refine failed.");
      }
      // Remove the "applying..." message
      setHistory((prev) => prev.slice(0, -1));
    } finally {
      setApplying(false);
    }
  }

  const chatMessages = (
    <div className="flex-1 overflow-y-auto space-y-2 p-4 min-h-0">
      {history.length === 0 && (
        <p className="text-xs text-muted-foreground">
          Describe what to change — I&apos;ll clarify and plan before
          re-running.
        </p>
      )}
      {history.map((item, index) => (
        <div key={index}>
          <div
            className={cn(
              "rounded-lg px-3 py-2 text-sm max-w-[90%]",
              item.role === "user"
                ? "ml-auto bg-foreground text-background"
                : "bg-surface-2 text-foreground",
            )}
          >
            {item.role === "assistant" && item.text.startsWith("✓") ? (
              <span className="text-green-600">{item.text}</span>
            ) : (
              item.text
            )}
          </div>
          {/* Show planned changes as pills */}
          {item.planned_changes && item.planned_changes.length > 0 && (
            <div className="mt-1.5 space-y-1 ml-1">
              {item.planned_changes.map((change, i) => (
                <div
                  key={i}
                  className="flex items-start gap-1.5 text-xs text-muted-foreground"
                >
                  <Check className="h-3 w-3 mt-0.5 text-primary shrink-0" />
                  <span>{change}</span>
                </div>
              ))}
            </div>
          )}
          {item.preview && item.preview.length > 0 && (
            <PreviewPanel preview={item.preview} />
          )}
        </div>
      ))}
    </div>
  );

  const inputArea = (
    <div className="shrink-0 border-t border-border p-3 space-y-2">
      <Textarea
        ref={textareaRef}
        placeholder={
          readyToApply
            ? "Looks good? Click Apply — or keep refining..."
            : 'e.g. "also extract payment_status"'
        }
        rows={3}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        disabled={disabled || loading || applying}
        className="rounded-[7px] resize-none"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            void handleSend();
          }
        }}
      />
      <div className="flex gap-2">
        <Button
          type="button"
          variant={readyToApply ? "outline" : "default"}
          className="flex-1"
          onClick={() => void handleSend()}
          disabled={disabled || loading || applying || !message.trim()}
        >
          {loading ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Thinking...
            </>
          ) : (
            <>
              <Send className="mr-2 h-4 w-4" />
              Send
            </>
          )}
        </Button>
        {readyToApply && (
          <Button
            type="button"
            className="flex-1"
            onClick={() => void handleApply()}
            disabled={applying}
          >
            {applying ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Re-running...
              </>
            ) : (
              <>
                <Play className="mr-2 h-4 w-4" />
                Apply
              </>
            )}
          </Button>
        )}
      </div>
      {readyToApply && (
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Apply updates the shared extraction rules and re-runs{" "}
          <span className="font-medium text-foreground">
            all documents in this run
          </span>
          .
        </p>
      )}
    </div>
  );

  if (variant === "panel") {
    return (
      <div className="flex flex-1 flex-col min-h-0 min-w-0">
        <div className="shrink-0 px-4 py-3 border-b border-border space-y-2">
          <p className="text-xs text-muted-foreground">
            Tell me what to change — I&apos;ll plan first, then apply to all
            documents in this run.
          </p>
          <RefineSaveDisclaimer saveAction={saveAction} />
        </div>
        {chatMessages}
        {inputArea}
      </div>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <MessageSquare className="h-5 w-5" />
          Refine results
        </CardTitle>
        <CardDescription>
          Not quite right? Tell me what to change — I&apos;ll plan the fix
          before re-running.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <RefineSaveDisclaimer saveAction={saveAction} />
        {history.length > 0 && (
          <div className="space-y-2 rounded-md border bg-muted/30 p-3 text-sm max-h-48 overflow-y-auto">
            {history.map((item, index) => (
              <div key={index}>
                <p>
                  <span className="font-medium">
                    {item.role === "user" ? "You" : "Agent"}:
                  </span>{" "}
                  {item.role === "assistant" && item.text.startsWith("✓") ? (
                    <span className="text-green-600">{item.text}</span>
                  ) : (
                    item.text
                  )}
                </p>
                {item.planned_changes && item.planned_changes.length > 0 && (
                  <div className="ml-4 mt-1 space-y-0.5">
                    {item.planned_changes.map((change, i) => (
                      <p key={i} className="text-xs text-muted-foreground">
                        • {change}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <Textarea
          ref={variant === "card" ? textareaRef : undefined}
          placeholder={
            readyToApply
              ? "Looks good? Click Apply — or keep refining..."
              : 'e.g. "also extract payment_status and flag unpaid ones"'
          }
          rows={3}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          disabled={disabled || loading || applying}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
        />
        <div className="flex gap-2">
          <Button
            type="button"
            variant={readyToApply ? "outline" : "default"}
            className="flex-1"
            onClick={() => void handleSend()}
            disabled={disabled || loading || applying || !message.trim()}
          >
            {loading ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Thinking...
              </>
            ) : (
              <>
                <Send className="mr-2 h-4 w-4" />
                Send
              </>
            )}
          </Button>
          {readyToApply && (
            <Button
              type="button"
              className="flex-1"
              onClick={() => void handleApply()}
              disabled={applying}
            >
              {applying ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Re-running...
                </>
              ) : (
                <>
                  <Play className="mr-2 h-4 w-4" />
                  Apply
                </>
              )}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
