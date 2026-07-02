"use client";

import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#060a12] text-foreground p-4 text-center">
      <div className="max-w-md space-y-4">
        <h1 className="text-4xl font-semibold tracking-tight text-[#EAF2FB]">404</h1>
        <h2 className="text-xl font-medium text-[#6BB4F0]">Page not found</h2>
        <p className="text-sm text-muted leading-relaxed">
          The requested URL could not be found. Check the address or return to the console.
        </p>
        <div className="pt-2">
          <Link
            href="/app"
            className="inline-flex items-center justify-center rounded-full bg-white px-5 py-2.5 text-xs font-semibold text-[#13233d] transition-colors hover:bg-white/90"
          >
            Go to console
          </Link>
        </div>
      </div>
    </div>
  );
}
