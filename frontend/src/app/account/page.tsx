"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { GoogleSignInButton } from "@/components/google-sign-in-button";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useUser } from "@/hooks/use-user";
import { ApiError, getIntegrationsStatus, getUserUsage, updateMyProfile, type IntegrationsStatus, type UsageSummary } from "@/lib/api";
import { FREE_EMAILS_PER_MONTH, FREE_PAGES_PER_MONTH, FREE_RAG_TOKENS_PER_MONTH, FREE_SHEETS_PER_MONTH } from "@/lib/free-plan";
import { hasPendingRun } from "@/lib/pending-run";
import { resumePendingRun } from "@/lib/resume-pending-run";
import { toastError, toastSuccess } from "@/lib/toast";
import {
  applyStoredUserUpdate,
  clearStoredUser,
  isEmailAuthAllowed,
  signInUser,
  signInWithGoogle,
} from "@/lib/user-session";
import { cn } from "@/lib/utils";
import { pricingHref, WAITLIST_SOURCES } from "@/lib/waitlist-source";

function AccountCard({
  title,
  children,
  highlight,
  danger,
  dimmed,
  id,
}: {
  title: string;
  children: React.ReactNode;
  highlight?: boolean;
  danger?: boolean;
  dimmed?: boolean;
  id?: string;
}) {
  return (
    <div
      id={id}
      className={cn(
        "rounded-lg border bg-card p-5 space-y-4 scroll-mt-6",
        highlight && "border-primary/30 bg-primary/5",
        danger && "border-destructive/40",
        dimmed && "opacity-65",
      )}
    >
      <h2 className="font-serif text-base font-semibold">{title}</h2>
      {children}
    </div>
  );
}

function UsageBar({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const warning = pct >= 80;
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span>{label}</span>
        <span className="text-muted-foreground tabular-nums">
          {used.toLocaleString()}/{limit.toLocaleString()}
        </span>
      </div>
      <div className="h-1.5 rounded-sm bg-muted overflow-hidden">
        <div
          className={cn(
            "h-full rounded-sm transition-all",
            warning ? "bg-amber-500" : "bg-primary",
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return (parts[0]?.[0] ?? "A").toUpperCase();
}

export default function AccountPage() {
  const router = useRouter();
  const { user, ready, setUser } = useUser();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [loading, setLoading] = useState(false);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [integrations, setIntegrations] = useState<IntegrationsStatus | null>(null);
  const allowEmailAuth = isEmailAuthAllowed();
  const authProvider = user?.auth_provider;

  useEffect(() => {
    if (user) {
      setDisplayName(user.name);
    }
  }, [user]);

  useEffect(() => {
    if (!user || typeof window === "undefined") return;

    function scrollToHash() {
      const hash = window.location.hash.replace(/^#/, "");
      if (!hash) return;
      document.getElementById(hash)?.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    // Client navigations don't always scroll to hash; do it after paint.
    requestAnimationFrame(scrollToHash);
    window.addEventListener("hashchange", scrollToHash);
    return () => window.removeEventListener("hashchange", scrollToHash);
  }, [user]);

  useEffect(() => {
    if (!user) return;
    getUserUsage()
      .then(setUsage)
      .catch(() => {
        /* silent fail - show defaults */
      });
    getIntegrationsStatus()
      .then(setIntegrations)
      .catch(() => {
        /* silent fail - show unknown */
      });
  }, [user]);

  function handleSignOut() {
    clearStoredUser();
    setUser(null);
    toastSuccess("Signed out.");
  }

  async function handleSaveName() {
    const next = displayName.trim();
    if (!next) {
      toastError("Name is required.");
      return;
    }
    if (user && next === user.name) {
      return;
    }
    setSavingName(true);
    try {
      const updated = await updateMyProfile(next);
      const stored = applyStoredUserUpdate({ name: updated.name });
      if (stored) setUser(stored);
      setDisplayName(updated.name);
      toastSuccess("Name updated.");
    } catch (err) {
      toastError(err instanceof ApiError ? err.message : "Failed to update name.");
    } finally {
      setSavingName(false);
    }
  }

  const finishSignIn = useCallback(
    async (signedIn: { name: string }, isNewUser: boolean) => {
      toastSuccess(
        isNewUser
          ? `Welcome, ${signedIn.name}!`
          : `Welcome back, ${signedIn.name}!`,
      );

      if (!hasPendingRun()) {
        return;
      }

      try {
        const runId = await resumePendingRun();
        if (runId) {
          router.push(`/results/${runId}`);
        }
      } catch (err) {
        toastError(
          err instanceof ApiError
            ? err.message
            : err instanceof Error
              ? err.message
              : "Could not start your run. Try again from home.",
        );
        router.push("/");
      }
    },
    [router],
  );

  async function handleSignIn(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      toastError("Name is required.");
      return;
    }
    if (!email.trim()) {
      toastError("Email is required to sign in.");
      return;
    }
    setLoading(true);
    try {
      const { user: signedIn, isNewUser } = await signInUser(name, email);
      setUser(signedIn);
      await finishSignIn(signedIn, isNewUser);
    } catch (err) {
      toastError(err instanceof ApiError ? err.message : "Failed to sign in.");
    } finally {
      setLoading(false);
    }
  }

  const handleGoogleCredential = useCallback(
    async (idToken: string) => {
      setLoading(true);
      try {
        const { user: signedIn, isNewUser } = await signInWithGoogle(idToken);
        setUser(signedIn);
        await finishSignIn(signedIn, isNewUser);
      } catch (err) {
        toastError(
          err instanceof ApiError ? err.message : "Google sign-in failed.",
        );
      } finally {
        setLoading(false);
      }
    },
    [finishSignIn, setUser],
  );

  if (!ready) {
    return (
      <div className="v2-page items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!user) {
    return (
      <div className="v2-page">
        <PageHeader
          title="Sign in"
          description="Sign in to run documents, save workflows, and sync results."
        />
        <main className="flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-[480px] space-y-4">
            <AccountCard title="Continue with Google">
              <div className="space-y-4">
                <p className="text-sm text-muted-foreground">
                  You can browse templates on the home page without an account.
                  Sign in when you&apos;re ready to upload and run.
                </p>
                <GoogleSignInButton
                  onCredential={handleGoogleCredential}
                  disabled={loading}
                />
                {allowEmailAuth && (
                  <>
                    <div className="relative py-1">
                      <div className="absolute inset-0 flex items-center">
                        <span className="w-full border-t" />
                      </div>
                      <div className="relative flex justify-center text-xs uppercase">
                        <span className="bg-card px-2 text-muted-foreground">
                          or email
                        </span>
                      </div>
                    </div>
                    <form onSubmit={handleSignIn} className="space-y-4">
                      <div className="space-y-2">
                        <Label htmlFor="name">Name</Label>
                        <Input
                          id="name"
                          value={name}
                          onChange={(e) => setName(e.target.value)}
                          disabled={loading}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="email">Email</Label>
                        <Input
                          id="email"
                          type="email"
                          value={email}
                          onChange={(e) => setEmail(e.target.value)}
                          disabled={loading}
                          required
                        />
                      </div>
                      <Button type="submit" className="w-full" disabled={loading}>
                        {loading && (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        )}
                        Sign in / Create account
                      </Button>
                    </form>
                  </>
                )}
              </div>
            </AccountCard>
            <p className="text-center text-sm text-muted-foreground">
              <Link href="/" className="text-primary hover:underline">
                Back to home
              </Link>
            </p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="v2-page">
      <PageHeader title="Account" description="Manage your profile and integrations" />
      <main className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-[680px] space-y-6">
          <AccountCard title="Plan & Usage" highlight>
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="font-semibold text-sm">Free Plan</p>
                <p className="text-xs text-muted-foreground">
                  {usage?.resets_at
                    ? `Resets ${new Date(usage.resets_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}`
                    : `${usage?.pages_limit ?? FREE_PAGES_PER_MONTH} pages/month`}
                </p>
              </div>
              <Link href={pricingHref(WAITLIST_SOURCES.normal)}>
                <Button size="sm" variant="outline">
                  Join Pro waitlist
                </Button>
              </Link>
            </div>
            <div className="pt-2 space-y-3">
              <UsageBar
                label="Pages extracted"
                used={usage?.pages_used ?? 0}
                limit={usage?.pages_limit ?? FREE_PAGES_PER_MONTH}
              />
              <UsageBar
                label="Emails sent"
                used={usage?.emails_used ?? 0}
                limit={usage?.emails_limit ?? FREE_EMAILS_PER_MONTH}
              />
              <UsageBar
                label="Sheets pushes"
                used={usage?.sheets_used ?? 0}
                limit={usage?.sheets_limit ?? FREE_SHEETS_PER_MONTH}
              />
              <UsageBar
                label="Ask-docs tokens"
                used={usage?.rag_tokens_used ?? 0}
                limit={usage?.rag_tokens_limit ?? FREE_RAG_TOKENS_PER_MONTH}
              />
            </div>
            {usage && usage.pages_used >= usage.pages_limit && (
              <p className="text-xs text-amber-600 font-medium">
                You&apos;ve hit your free limit.{" "}
                <Link href={pricingHref(WAITLIST_SOURCES.pagesExhausted)} className="underline">
                  Join the Pro waitlist
                </Link>{" "}
                for unlimited access.
              </p>
            )}
          </AccountCard>

          <AccountCard title="Profile">
            <div className="flex items-center gap-4">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary text-lg font-bold text-primary-foreground">
                {initials(displayName || user.name)}
              </span>
              <div className="text-sm space-y-0.5 min-w-0">
                <p className="font-semibold truncate">{user.name}</p>
                <p className="text-muted-foreground truncate">
                  {user.email || "—"}
                </p>
                <p className="text-xs text-muted-foreground">
                  {authProvider === "google"
                    ? "Signed in with Google · email can’t be changed here"
                    : authProvider === "email" || allowEmailAuth
                      ? "Signed in with email"
                      : "Signed in · email can’t be changed here"}
                </p>
              </div>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="display-name" className="text-xs text-muted-foreground">
                Display name
              </Label>
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                <Input
                  id="display-name"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  maxLength={120}
                  disabled={savingName}
                />
                <Button
                  size="sm"
                  onClick={handleSaveName}
                  disabled={
                    savingName ||
                    !displayName.trim() ||
                    displayName.trim() === user.name
                  }
                  className="sm:shrink-0"
                >
                  {savingName ? (
                    <>
                      <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                      Saving
                    </>
                  ) : (
                    "Save"
                  )}
                </Button>
              </div>
            </div>
            <div>
              <Button variant="outline" size="sm" onClick={handleSignOut}>
                Sign out
              </Button>
            </div>
          </AccountCard>

          <AccountCard id="integrations" title="Integrations">
            <p className="text-xs text-muted-foreground">
              Managed by Nexora. Push results from a run when available — nothing
              to configure here.
            </p>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2.5 text-sm">
                <div className="min-w-0">
                  <p>Email delivery</p>
                  <p className="text-xs text-muted-foreground">
                    Send extraction results to your inbox
                  </p>
                </div>
                <span
                  className={
                    integrations?.email_configured
                      ? "v2-badge-success"
                      : "v2-badge-muted"
                  }
                >
                  {integrations == null
                    ? "…"
                    : integrations.email_configured
                      ? "Available"
                      : "Unavailable"}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2.5 text-sm">
                <div className="min-w-0">
                  <p>Google Sheets</p>
                  <p className="text-xs text-muted-foreground">
                    {integrations?.sheets_share_email
                      ? `Share sheets with ${integrations.sheets_share_email}`
                      : "Append rows to a spreadsheet you share"}
                  </p>
                </div>
                <span
                  className={
                    integrations?.sheets_configured
                      ? "v2-badge-success"
                      : "v2-badge-muted"
                  }
                >
                  {integrations == null
                    ? "…"
                    : integrations.sheets_configured
                      ? "Available"
                      : "Unavailable"}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-md border border-dashed px-3 py-2.5 text-sm opacity-70">
                <span>Webhook</span>
                <span className="v2-badge-muted">Coming soon</span>
              </div>
            </div>
          </AccountCard>

          <AccountCard title="API Access" dimmed>
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                Programmatic access to runs and workflows.
              </p>
              <span className="v2-badge-muted">Coming soon</span>
            </div>
          </AccountCard>

          <AccountCard title="Danger Zone" danger>
            <p className="text-sm text-muted-foreground">
              Permanently delete your account and all workflows.
            </p>
            <Button variant="destructive" size="sm" disabled>
              Delete Account
            </Button>
          </AccountCard>
        </div>
      </main>
    </div>
  );
}
