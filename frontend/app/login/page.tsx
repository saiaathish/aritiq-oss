"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import { RiGoogleFill } from "@remixicon/react";
import { Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { createClient } from "@/lib/supabase/client";

function LoginCard() {
  const searchParams = useSearchParams();
  const [loading, setLoading] = React.useState(false);
  const authError = searchParams.get("error") === "auth";
  const next = searchParams.get("next") ?? "/app";

  const signInWithGoogle = async () => {
    setLoading(true);
    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });
    if (error) setLoading(false); // on success the browser navigates away
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <Card className="p-7 sm:p-8">
          <div className="flex flex-col items-center text-center">
            <a href="/" className="transition-opacity hover:opacity-90">
              <img
                src="/logo-text-light.png"
                alt="Aritiq"
                className="h-12 w-auto object-contain"
                style={{ filter: "drop-shadow(0 0 25px rgba(107, 180, 240, 0.45))" }}
              />
            </a>
            <h1 className="mt-5 text-lg font-display text-foreground">
              Sign in to run an audit
            </h1>
            <p className="mt-1.5 text-[13px] leading-relaxed text-muted">
            </p>

            {authError && (
              <p className="mt-4 w-full rounded-lg border border-wrong/30 bg-wrong/[0.08] px-3 py-2 text-xs text-wrong">
                Sign-in didn&apos;t complete — please try again.
              </p>
            )}

            <Button
              variant="outline"
              className="mt-6 w-full"
              onClick={signInWithGoogle}
              disabled={loading}
            >
              {loading ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <RiGoogleFill className="h-4 w-4 text-primary" aria-hidden="true" />
              )}
              {loading ? "Redirecting to Google…" : "Continue with Google"}
            </Button>

            <div className="mt-5 flex items-center gap-1.5 text-[11px] text-muted">
              <ShieldCheck className="h-3.5 w-3.5 text-primary" />
              We only read your name, email, and avatar.
            </div>
          </div>
        </Card>

        <p className="mt-4 text-center text-xs text-muted">
          <a href="/" className="transition-colors hover:text-foreground">
            ← Back to aritiq.com
          </a>
        </p>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <React.Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
        </main>
      }
    >
      <LoginCard />
    </React.Suspense>
  );
}
