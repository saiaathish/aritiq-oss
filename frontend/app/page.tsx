"use client";

import { Play } from 'lucide-react';
import BoomerangVideoBg from '@/components/BoomerangVideoBg';
import { AritiqNav } from '@/components/ui/navigation-menu';
import LandingSections from '@/components/LandingSections';

const BG_VIDEO = '/hero.mp4';

export default function App() {
  return (
    <main className="bg-[#060a12] text-foreground">
      <section className="relative w-full min-h-screen sm:h-screen overflow-hidden">
        <BoomerangVideoBg src={BG_VIDEO} className="absolute inset-0 w-full h-full" />
        {/* Darkening + top-to-middle fade for text legibility */}
        <div className="absolute inset-0 z-[1] bg-black/25 pointer-events-none" />
        <div
          className="absolute inset-0 z-[1] pointer-events-none"
          style={{
            background:
              'linear-gradient(to bottom, rgba(4,10,18,0.92) 0%, rgba(4,10,18,0.55) 28%, rgba(4,10,18,0) 52%)',
          }}
        />
        {/* Bottom fade so the hero video blends into the problem section */}
        <div
          className="absolute inset-x-0 bottom-0 z-[2] h-48 sm:h-56 pointer-events-none"
          style={{ background: 'linear-gradient(to top, #060a12 0%, rgba(6,10,18,0.6) 45%, transparent 100%)' }}
        />
        <AritiqNav />

        {/* Hero copy */}
        <div className="relative z-10 flex flex-col items-center text-center pt-24 sm:pt-28 md:pt-32 px-4 sm:px-6">
          <h1
            className="font-normal leading-[0.95] text-[#EAF2FB] text-[2rem] sm:text-4xl md:text-5xl lg:text-[4.75rem] xl:text-[5.25rem] max-w-5xl"
            style={{
              letterSpacing: '-0.035em',
            }}
          >
            Verify financial claims.{' '}
            <span className="text-[#6BB4F0]">
              Deterministically.
            </span>
          </h1>
          <p className="mt-6 sm:mt-8 text-white/80 text-sm sm:text-base md:text-lg leading-relaxed max-w-md px-2">
            Aritiq parses numeric assertions from SEC filings using language models, then re-derives and checks every value using deterministic calculation code.
          </p>
          <div className="mt-6 sm:mt-8 flex items-center gap-4 flex-wrap justify-center">
            <a
              href="/app"
              className="bg-white hover:bg-white/90 text-[#13233d] text-sm font-semibold px-6 py-3 rounded-full transition-colors shadow-sm"
            >
              Run an audit
            </a>
            <a
              href="#benchmark"
              className="text-white text-sm font-semibold hover:opacity-80 transition-opacity"
            >
              View benchmark
            </a>
          </div>
          <p className="mt-4 text-white/60 text-xs">
            No models are used in the verification engine.
          </p>
        </div>
      </section>

      <LandingSections />
    </main>
  );
}
