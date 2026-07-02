import { Play } from 'lucide-react';
import BoomerangVideoBg from './BoomerangVideoBg';
import { AritiqNav } from '@/components/ui/navigation-menu';
import LandingSections from './LandingSections';

const BG_VIDEO = '/hero.mp4';

function App() {
  return (
    <main className="bg-[#060a12]">
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
            fontFamily:
              '"Neue Haas Grotesk Display Pro 55 Roman", "Neue Haas Grotesk Text Pro", "Helvetica Neue", Helvetica, Arial, sans-serif',
            letterSpacing: '-0.035em',
          }}
        >
          LLMs parse.{' '}
          <span className="text-[#6BB4F0]">
            Code
            <br className="hidden sm:block" /> verifies.
          </span>
        </h1>
        <p className="mt-6 sm:mt-8 text-white/80 text-sm sm:text-base md:text-lg leading-relaxed max-w-md px-2">
          Aritiq extracts financial claims from SEC filings with AI, then re-checks every number
          with deterministic code &mdash; no model in the verifier, ever.
        </p>
        <div className="mt-6 sm:mt-8 flex items-center gap-4 flex-wrap justify-center">
          <a
            href="#audit"
            className="bg-white hover:bg-white/90 text-[#13233d] text-sm font-semibold px-6 py-3 rounded-full transition-colors shadow-sm"
          >
            Audit a 10-K
          </a>
          <a
            href="#benchmark"
            className="text-white text-sm font-semibold hover:opacity-80 transition-opacity"
          >
            See the benchmark
          </a>
        </div>
        <p className="mt-4 text-white/60 text-xs">
          No model SDK imports in the verification core. Firewall-tested.
        </p>
      </div>

      {/* Bottom-right video link */}
      <div className="hidden sm:flex absolute right-6 md:right-10 bottom-8 md:bottom-10 z-10 items-center gap-2 text-white/90 text-sm">
        <button className="flex items-center justify-center w-6 h-6 rounded-full bg-white/20 backdrop-blur-sm hover:bg-white/30 transition-colors">
          <Play className="w-3 h-3 fill-white text-white ml-0.5" />
        </button>
        <span className="font-medium">How verification works</span>
        <span className="text-white/60">1:35</span>
      </div>
    </section>

    <LandingSections />
    </main>
  );
}

export default App;
