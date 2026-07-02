"use client";

import { useEffect } from "react";

export default function GlobalError({
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
    <html lang="en">
      <body className="bg-[#060a12] text-[#EAF2FB] min-h-screen flex flex-col items-center justify-center p-4 text-center">
        <div className="max-w-md space-y-4">
          <h1 className="text-4xl font-semibold tracking-tight">System Error</h1>
          <h2 className="text-xl font-medium text-[#6BB4F0]">Critical error occurred</h2>
          <p className="text-sm text-white/60 leading-relaxed">
            A system-level error occurred. Try reloading the application.
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
      </body>
    </html>
  );
}
