"use client";

import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#060a12] text-foreground p-4 text-center">
      <div className="max-w-md space-y-4">
        <h1 className="text-4xl font-semibold tracking-tight text-[#EAF2FB]">Error</h1>
        <h2 className="text-xl font-medium text-[#6BB4F0]">An unexpected error occurred</h2>
        <p className="text-sm text-muted leading-relaxed">
          The application encountered an error. You can try refreshing the page or reloading.
        </p>
        <div className="pt-2 flex justify-center gap-3">
          <button
            onClick={() => reset()}
            className="inline-flex items-center justify-center rounded-full bg-white px-5 py-2.5 text-xs font-semibold text-[#13233d] transition-colors hover:bg-white/90"
          >
            Try again
          </button>
          <a
            href="/app"
            className="inline-flex items-center justify-center rounded-full border border-white/10 px-5 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-white/[0.05]"
          >
            Go to console
          </a>
        </div>
      </div>
    </div>
  );
}
