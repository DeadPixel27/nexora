"use client";

import { Check, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, joinWaitlist } from "@/lib/api";
import { FREE_PAGES_PER_MONTH } from "@/lib/free-plan";
import { toastError, toastSuccess } from "@/lib/toast";
import { loadStoredUser } from "@/lib/user-session";
import { cn } from "@/lib/utils";
import {
  WAITLIST_SOURCES,
  normalizeWaitlistSource,
  type WaitlistSource,
} from "@/lib/waitlist-source";

const MAX_FEEDBACK_CHARS = 1000;

function PricingCard({
  title,
  price,
  features,
  cta,
  highlight,
}: {
  title: string;
  price: string;
  features: string[];
  cta: React.ReactNode;
  highlight?: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border p-6 space-y-5 flex flex-col",
        highlight
          ? "border-primary bg-primary/5 shadow-sm"
          : "border-border bg-card",
      )}
    >
      <div>
        <h3 className="font-serif text-lg font-semibold">{title}</h3>
        <p className="text-2xl font-bold mt-1">{price}</p>
      </div>
      <ul className="space-y-2 flex-1">
        {features.map((f, i) => (
          <li key={i} className="flex items-start gap-2 text-sm">
            <Check className="h-4 w-4 text-primary mt-0.5 shrink-0" />
            <span>{f}</span>
          </li>
        ))}
      </ul>
      {cta}
    </div>
  );
}

function sourceBanner(source: WaitlistSource): React.ReactNode {
  if (source === WAITLIST_SOURCES.pagesExhausted) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        You&apos;ve hit this month&apos;s free page limit. Join the Pro waitlist
        and we&apos;ll notify you when higher limits open.
      </div>
    );
  }
  return null;
}

function PricingPageInner() {
  const searchParams = useSearchParams();
  const source = normalizeWaitlistSource(searchParams.get("source"));

  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [feedback, setFeedback] = useState("");
  const [loading, setLoading] = useState(false);
  const [joined, setJoined] = useState(false);

  const stored = loadStoredUser();
  const banner = sourceBanner(source);

  async function handleJoinWaitlist(e: React.FormEvent) {
    e.preventDefault();
    const waitlistEmail = email.trim() || stored?.email || "";
    if (!waitlistEmail) {
      toastError("Email is required.");
      return;
    }

    setLoading(true);
    try {
      const result = await joinWaitlist(
        waitlistEmail,
        name.trim() || stored?.name || "",
        source,
        feedback.trim().slice(0, MAX_FEEDBACK_CHARS),
      );
      setJoined(true);
      toastSuccess(result.message);
    } catch (err) {
      toastError(
        err instanceof ApiError ? err.message : "Failed to join waitlist.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="v2-page">
      <PageHeader
        title="Pricing"
        description="Extract data from any document with AI"
      />
      <main className="flex-1 overflow-y-auto px-4 py-8">
        <div className="mx-auto max-w-[800px] space-y-10">
          {banner}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <PricingCard
              title="Free"
              price="$0"
              features={[
                `${FREE_PAGES_PER_MONTH} pages/month`,
                "All templates (invoice, receipt, contract, etc.)",
                "Chat refinement",
                "CSV & JSON export",
                "Email delivery",
                "Google Sheets push",
                "Inbound email → workflow runs",
              ]}
              cta={
                <Link href="/">
                  <Button variant="outline" className="w-full">
                    Start extracting
                  </Button>
                </Link>
              }
            />

            <PricingCard
              title="Pro"
              price="Coming soon"
              highlight
              features={[
                "Unlimited pages",
                "Priority extraction (faster models)",
                "Custom templates",
                "API access",
                "Webhook integrations",
                "Priority support",
              ]}
              cta={
                joined ? (
                  <div className="flex items-center justify-center gap-2 py-2 text-sm text-primary font-medium">
                    <Check className="h-4 w-4" />
                    You&apos;re on the list!
                  </div>
                ) : (
                  <form onSubmit={handleJoinWaitlist} className="space-y-3">
                    {!stored?.email && (
                      <>
                        <div className="space-y-1">
                          <Label htmlFor="waitlist-email" className="text-xs">
                            Email
                          </Label>
                          <Input
                            id="waitlist-email"
                            type="email"
                            placeholder="you@company.com"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            disabled={loading}
                            required
                          />
                        </div>
                        <div className="space-y-1">
                          <Label htmlFor="waitlist-name" className="text-xs">
                            Name (optional)
                          </Label>
                          <Input
                            id="waitlist-name"
                            placeholder="Your name"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            disabled={loading}
                          />
                        </div>
                      </>
                    )}
                    <div className="space-y-1">
                      <Label htmlFor="waitlist-feedback" className="text-xs">
                        Anything we should know? (optional)
                      </Label>
                      <Textarea
                        id="waitlist-feedback"
                        placeholder="e.g. higher page limits, API access, Sheets automation…"
                        value={feedback}
                        onChange={(e) =>
                          setFeedback(e.target.value.slice(0, MAX_FEEDBACK_CHARS))
                        }
                        disabled={loading}
                        rows={3}
                        className="min-h-[4.5rem] resize-y text-sm"
                      />
                      <p className="text-[11px] text-muted-foreground tabular-nums">
                        {feedback.length}/{MAX_FEEDBACK_CHARS}
                      </p>
                    </div>
                    <Button type="submit" className="w-full" disabled={loading}>
                      {loading && (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      )}
                      {stored?.email ? "Join waitlist" : "Join Pro waitlist"}
                    </Button>
                  </form>
                )
              }
            />
          </div>

          <div className="text-center text-sm text-muted-foreground space-y-1">
            <p>
              Questions?{" "}
              <a
                href="mailto:deadpixel27@nexora.app"
                className="text-primary underline"
              >
                deadpixel27@nexora.app
              </a>
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function PricingPage() {
  return (
    <Suspense
      fallback={
        <div className="v2-page items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      }
    >
      <PricingPageInner />
    </Suspense>
  );
}
