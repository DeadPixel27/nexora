"use client";

import { Loader2, Send } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, chatRunDocuments, type DocChatCitation } from "@/lib/api";
import { toastError } from "@/lib/toast";
import { cn } from "@/lib/utils";

interface Message {
  role: "user" | "assistant";
  text: string;
  citations?: DocChatCitation[];
}

interface DocChatPanelProps {
  runId: string;
  disabled?: boolean;
  className?: string;
  /** panel = fill side pane (no duplicate title; used under Refine | Ask docs tabs) */
  variant?: "default" | "panel";
}

export function DocChatPanel({
  runId,
  disabled,
  className,
  variant = "default",
}: DocChatPanelProps) {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);

  async function onSend() {
    const question = input.trim();
    if (!question || busy || disabled) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", text: question }]);
    setBusy(true);
    try {
      const result = await chatRunDocuments(runId, question);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: result.answer,
          citations: result.citations,
        },
      ]);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : "Document chat failed. Is RAG enabled?";
      toastError(msg);
      setMessages((prev) => [...prev, { role: "assistant", text: msg }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={cn("flex flex-1 flex-col min-h-0", className)}>
      {variant === "panel" ? (
        <div className="shrink-0 px-4 py-3 border-b border-border">
          <p className="text-xs text-muted-foreground">
            Ask questions over this run&apos;s extracted text (RAG).
          </p>
        </div>
      ) : (
        <div className="px-4 py-3 border-b border-border">
          <p className="text-sm font-medium">Ask documents</p>
          <p className="text-xs text-muted-foreground mt-0.5">
            RAG over this run&apos;s extracted text
          </p>
        </div>
      )}
      <div className="flex-1 overflow-auto px-4 py-3 space-y-3 min-h-0">
        {messages.length === 0 && (
          <p className="text-xs text-muted-foreground">
            e.g. &ldquo;What is the invoice total?&rdquo;
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={`${m.role}-${i}`}
            className={cn(
              "text-sm rounded-md px-3 py-2",
              m.role === "user"
                ? "bg-muted ml-4"
                : "bg-primary/5 mr-4 border border-primary/10",
            )}
          >
            <p className="whitespace-pre-wrap">{m.text}</p>
            {m.citations && m.citations.length > 0 && (
              <ul className="mt-2 space-y-1">
                {m.citations.slice(0, 3).map((c, j) => (
                  <li
                    key={`${c.document_id}-${c.chunk_index}-${j}`}
                    className="text-[11px] text-muted-foreground truncate"
                  >
                    {c.filename || "doc"}: {c.snippet}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <div className="p-3 flex gap-2 border-t border-border shrink-0">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about the documents…"
          rows={2}
          disabled={disabled || busy}
          className="min-h-[60px] resize-none text-sm"
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void onSend();
            }
          }}
        />
        <Button
          type="button"
          size="icon"
          disabled={disabled || busy || !input.trim()}
          onClick={() => void onSend()}
          aria-label="Send"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
        </Button>
      </div>
    </div>
  );
}
