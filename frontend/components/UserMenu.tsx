"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { LogOut, Gauge, ChevronDown } from "lucide-react";
import type { User } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";

/** Emails shown as "Unlimited" (must mirror the backend's
 *  ARITIQ_UNLIMITED_EMAILS). Env-driven so no personal email ships in source. */
const UNLIMITED_EMAILS = (process.env.NEXT_PUBLIC_UNLIMITED_EMAILS ?? "")
  .split(",")
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

/** Profile widget for the app header: Google avatar, account details on open,
 *  the daily audit allowance, and sign-out. Renders nothing until the session
 *  loads (the middleware guarantees one exists inside /app). */
export function UserMenu() {
  const router = useRouter();
  const [user, setUser] = React.useState<User | null>(null);
  const [open, setOpen] = React.useState(false);
  const [signingOut, setSigningOut] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => setUser(data.user));
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });
    return () => subscription.unsubscribe();
  }, []);

  React.useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;

  const meta = (user.user_metadata ?? {}) as Record<string, string | undefined>;
  const name = meta.full_name || meta.name || user.email || "Account";
  const avatarUrl = meta.avatar_url || meta.picture;
  const initial = (name[0] || "?").toUpperCase();

  const signOut = async () => {
    setSigningOut(true);
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push("/login");
    router.refresh();
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn(
          "flex items-center gap-2 rounded-full glass-subtle py-1 pl-1 pr-2.5 transition-colors hover:bg-white/[0.06]",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60"
        )}
      >
        <Avatar avatarUrl={avatarUrl} initial={initial} size="h-7 w-7" />
        <span className="hidden max-w-[120px] truncate text-xs font-medium text-foreground sm:block">
          {name.split(" ")[0]}
        </span>
        <ChevronDown
          className={cn(
            "h-3.5 w-3.5 text-muted transition-transform duration-200",
            open && "rotate-180"
          )}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: 6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.98 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="absolute right-0 z-50 mt-2 w-64 origin-top-right rounded-xl border border-border bg-surface p-1.5 shadow-[0_16px_48px_-12px_rgba(0,0,0,0.6)]"
          >
            <div className="flex items-center gap-3 rounded-lg px-2.5 py-2.5">
              <Avatar avatarUrl={avatarUrl} initial={initial} size="h-9 w-9" />
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-foreground">{name}</div>
                <div className="truncate text-xs text-muted">{user.email}</div>
              </div>
            </div>

            <div className="mx-2.5 my-1 border-t border-border/60" />

            <div className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-xs text-muted">
              <Gauge className="h-4 w-4 shrink-0 text-primary" />
              <span>
                <span className="font-medium text-foreground">
                  {UNLIMITED_EMAILS.includes((user.email ?? "").toLowerCase())
                    ? "Unlimited"
                    : "10 audits / day"}
                </span>
              </span>
            </div>

            <div className="mx-2.5 my-1 border-t border-border/60" />

            <button
              role="menuitem"
              onClick={signOut}
              disabled={signingOut}
              className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] font-medium text-muted transition-colors hover:bg-white/[0.05] hover:text-foreground disabled:opacity-60"
            >
              <LogOut className="h-4 w-4" />
              {signingOut ? "Signing out…" : "Sign out"}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Avatar({
  avatarUrl,
  initial,
  size,
}: {
  avatarUrl?: string;
  initial: string;
  size: string;
}) {
  const [broken, setBroken] = React.useState(false);
  if (avatarUrl && !broken) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={avatarUrl}
        alt=""
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
        className={cn(size, "rounded-full object-cover ring-1 ring-white/15")}
      />
    );
  }
  return (
    <span
      className={cn(
        size,
        "flex items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-primary ring-1 ring-inset ring-primary/30"
      )}
    >
      {initial}
    </span>
  );
}
