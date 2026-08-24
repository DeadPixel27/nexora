"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import {
  ApiError,
  getWorkflowTemplateVersions,
  listInboundAddresses,
  revertWorkflowToVersion,
  type InboundAddress,
  type TemplateVersionSummary,
  type WorkflowResponse,
} from "@/lib/api";
import { toastError, toastSuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";

interface DetailSidebarProps {
  workflow: WorkflowResponse;
  onWorkflowUpdated: () => void | Promise<void>;
}

export function DetailSidebar({
  workflow,
  onWorkflowUpdated,
}: DetailSidebarProps) {
  const [versions, setVersions] = useState<TemplateVersionSummary[]>([]);
  const [reverting, setReverting] = useState<string | null>(null);
  const [inboundAddress, setInboundAddress] = useState<InboundAddress | null>(
    null,
  );

  const settingsHref = `/workflows/${workflow.workflow_id}/settings`;

  const loadVersions = useCallback(async () => {
    try {
      const list = await getWorkflowTemplateVersions(workflow.workflow_id);
      setVersions(list);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 404)) {
        toastError("Failed to load versions.");
      }
    }
  }, [workflow.workflow_id]);

  const loadInbound = useCallback(async () => {
    try {
      const addresses = await listInboundAddresses();
      setInboundAddress(
        addresses.find((a) => a.workflow_id === workflow.workflow_id) ?? null,
      );
    } catch {
      setInboundAddress(null);
    }
  }, [workflow.workflow_id]);

  useEffect(() => {
    void loadVersions();
  }, [loadVersions]);

  useEffect(() => {
    void loadInbound();
  }, [loadInbound]);

  async function handleSetCurrent(versionId: string) {
    setReverting(versionId);
    try {
      await revertWorkflowToVersion(workflow.workflow_id, versionId);
      toastSuccess("Workflow updated to selected version.");
      await loadVersions();
      await onWorkflowUpdated();
    } catch (e) {
      toastError(e instanceof ApiError ? e.message : "Failed to update version.");
    } finally {
      setReverting(null);
    }
  }

  const truncatedInbound = inboundAddress
    ? inboundAddress.full_address.length > 28
      ? `${inboundAddress.full_address.slice(0, 26)}…`
      : inboundAddress.full_address
    : null;

  return (
    <aside className="space-y-6">
      <Link
        href={settingsHref}
        className={cn(buttonVariants({ variant: "outline" }), "w-full text-xs h-9")}
      >
        Workflow Settings
      </Link>

      <section className="space-y-2">
        <h3 className="v2-section-title">Output paths</h3>
        <div className="rounded-md px-3 py-2 text-xs bg-green-50 text-green-800">
          {workflow.default_email?.trim()
            ? `Email — ${workflow.default_email.trim()}`
            : "Email — configure in settings"}
        </div>
        <div className="rounded-md px-3 py-2 text-xs bg-blue-50 text-blue-800">
          {workflow.default_sheets_url?.trim()
            ? "Push to Sheets — configured"
            : "Push to Sheets — share sheet + URL in settings"}
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="v2-section-title">Ingestion paths</h3>
        <div className="flex items-center justify-between rounded-md border px-3 py-2 text-xs">
          <span>UI Upload</span>
          <span className="v2-badge-success">active</span>
        </div>
        <div className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-xs">
          <span className="shrink-0">Inbound Email</span>
          {inboundAddress ? (
            <Link
              href={settingsHref}
              className="v2-badge-success hover:underline truncate max-w-[11rem]"
              title={inboundAddress.full_address}
            >
              {truncatedInbound}
            </Link>
          ) : (
            <Link
              href={settingsHref}
              className="v2-badge-muted hover:underline shrink-0"
            >
              Configure in settings
            </Link>
          )}
        </div>
      </section>

      <section className="space-y-2">
        <h3 className="v2-section-title">Versions</h3>
        {versions.length === 0 && (
          <p className="text-xs text-muted-foreground">No versions yet.</p>
        )}
        {versions.map((version) => {
          const isCurrent =
            version.version_id === workflow.current_template_version_id ||
            version.is_current;
          return (
            <div
              key={version.version_id}
              className={cn(
                "rounded-md border px-3 py-2 text-xs space-y-1",
                isCurrent && "border-l-[3px] border-l-primary bg-primary/5",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">
                  v{version.version_number}
                  {isCurrent && " · current"}
                </span>
              </div>
              <p className="text-muted-foreground line-clamp-2">
                {version.refine_summary || "Initial version"}
              </p>
              {!isCurrent && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs px-2"
                  disabled={reverting === version.version_id}
                  onClick={() => void handleSetCurrent(version.version_id)}
                >
                  Set as current
                </Button>
              )}
            </div>
          );
        })}
      </section>

      <section className="space-y-2">
        <h3 className="v2-section-title">Pipeline steps</h3>
        <div className="space-y-1">
          {workflow.steps.map((step, index) => (
            <div key={step.step_order}>
              <div className="flex items-center gap-2 text-xs">
                <span className="h-1.5 w-1.5 rounded-full bg-primary shrink-0" />
                <span className="font-medium">{step.agent_type}</span>
              </div>
              {index < workflow.steps.length - 1 && (
                <p className="text-muted-foreground text-center text-[10px] py-0.5">
                  ↓
                </p>
              )}
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
