import { useState } from 'react';
import {
  FileSearch,
  Calculator,
  ClipboardCheck,
  ShieldCheck,
  ChevronDown,
  ArrowRight,
  Bot,
  BookOpen,
  Wrench,
} from 'lucide-react';
import { BeamsBackground } from '@/components/ui/beams-background';
import { StarsBackground } from '@/components/ui/stars-background';
import { ShootingStars } from '@/components/ui/shooting-stars';
import { DottedSurface } from '@/components/ui/dotted-surface';
import { ProceduralGroundBackground } from '@/components/ui/procedural-ground-background';
import { FallingPattern } from '@/components/ui/falling-pattern';

const TICKERS = ['AAPL', 'MSFT', 'NVDA', 'TSLA'];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#6BB4F0] mb-4">
      {children}
    </p>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2
      className="text-2xl sm:text-3xl md:text-4xl font-normal text-[#EAF2FB] leading-tight"
      style={{ letterSpacing: '-0.02em' }}
    >
      {children}
    </h2>
  );
}

/* ---------- 2. The problem ---------- */
function ProblemSection() {
  return (
    <section className="px-4 sm:px-6 md:px-10 py-20 sm:py-28">
      <div className="max-w-3xl mx-auto text-center">
        <SectionLabel>The problem</SectionLabel>
        <SectionHeading>
          LLMs are good at reading filings.
          <br />
          <span className="text-[#6BB4F0]">They&rsquo;re bad at arithmetic.</span>
        </SectionHeading>
        <p className="mt-6 text-white/70 text-sm sm:text-base leading-relaxed">
          AI systems increasingly generate financial summaries, analyst notes, and investment
          content. LLMs are good at reading filings but bad at arithmetic and prone to confidently
          stating wrong numbers. Most &ldquo;AI fact-checking&rdquo; tools use another LLM to check
          the first one &mdash; which doesn&rsquo;t fix the underlying problem.
        </p>
      </div>
    </section>
  );
}

/* ---------- 3. How it works ---------- */
function HowItWorksSection() {
  const steps = [
    {
      icon: FileSearch,
      title: 'Extract',
      model: true,
      body: 'AI reads the filing and pulls out claims — numbers, formulas, comparisons — as structured data. This is the only step where a model is involved.',
    },
    {
      icon: Calculator,
      title: 'Verify',
      model: false,
      body: 'Deterministic code re-derives each number from source data (XBRL, cross-statement figures) and checks the arithmetic, formulas, and consistency. No model touches this step.',
    },
    {
      icon: ClipboardCheck,
      title: 'Score & trace',
      model: false,
      body: 'Every claim gets a verdict — VERIFIED / WRONG_MATH / INSUFFICIENT_EVIDENCE / PROPAGATED_ERROR — with full provenance. Click any number and see exactly what it was checked against.',
    },
  ];

  return (
    <section
      id="how"
      className="relative overflow-hidden px-4 sm:px-6 md:px-10 py-20 sm:py-28 scroll-mt-24"
    >
      <BeamsBackground className="absolute inset-0 z-0" intensity="medium" />
      {/* Fade the beams into the flat page background above and below */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to bottom, #060a12, transparent)' }}
      />
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to top, #060a12, transparent)' }}
      />
      <div className="relative z-10 max-w-5xl mx-auto">
        <div className="text-center mb-12 sm:mb-16">
          <SectionLabel>How it works</SectionLabel>
          <SectionHeading>
            One model, two firewalled steps of <span className="text-[#6BB4F0]">pure code.</span>
          </SectionHeading>
        </div>

        <div className="flex flex-col lg:flex-row items-stretch gap-6 lg:gap-0">
          {/* Step 1 — the AI side */}
          <div className="flex-1 rounded-2xl border border-white/10 bg-white/[0.04] p-6 sm:p-8">
            <div className="flex items-center justify-between mb-5">
              <FileSearch className="w-6 h-6 text-[#6BB4F0]" />
              <span className="text-[10px] font-semibold uppercase tracking-widest rounded-full border border-[#6BB4F0]/40 text-[#6BB4F0] px-2.5 py-1">
                AI step
              </span>
            </div>
            <h3 className="text-lg font-semibold text-[#EAF2FB] mb-2">1 · {steps[0].title}</h3>
            <p className="text-white/65 text-sm leading-relaxed">{steps[0].body}</p>
          </div>

          {/* Model firewall divider */}
          <div className="relative flex lg:flex-col items-center justify-center lg:px-6 py-2 lg:py-0">
            <div className="hidden lg:block h-full border-l-2 border-dashed border-[#6BB4F0]/50" />
            <div className="lg:hidden w-full border-t-2 border-dashed border-[#6BB4F0]/50" />
            <span className="absolute bg-[#060a12] px-2 py-1 text-[10px] font-semibold uppercase tracking-widest text-[#6BB4F0] whitespace-nowrap lg:rotate-90">
              Model firewall
            </span>
          </div>

          {/* Steps 2 & 3 — deterministic side */}
          <div className="flex-[2] grid sm:grid-cols-2 gap-6">
            {steps.slice(1).map((step, i) => (
              <div
                key={step.title}
                className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 sm:p-8"
              >
                <div className="flex items-center justify-between mb-5">
                  <step.icon className="w-6 h-6 text-[#EAF2FB]" />
                  <span className="text-[10px] font-semibold uppercase tracking-widest rounded-full border border-white/20 text-white/60 px-2.5 py-1">
                    No model
                  </span>
                </div>
                <h3 className="text-lg font-semibold text-[#EAF2FB] mb-2">
                  {i + 2} · {step.title}
                </h3>
                <p className="text-white/65 text-sm leading-relaxed">{step.body}</p>
              </div>
            ))}
          </div>
        </div>

        <p className="mt-8 text-center text-white/50 text-xs">
          The dotted line is real: nothing to the right of it imports a model SDK.
        </p>
      </div>
    </section>
  );
}

/* ---------- 4. Proof / benchmark ---------- */
function BenchmarkSection() {
  const stats = [
    {
      value: '96.6%',
      label: 'precision',
      detail:
        'Of claims Aritiq is willing to call VERIFIED or WRONG_MATH, this is how often it’s actually right.',
    },
    { value: '3.4%', label: 'false-positive rate', detail: 'Measured, not estimated.' },
    {
      value: '79.4%',
      label: 'coverage',
      detail: 'Share of claims with enough evidence to rule on at all.',
    },
    {
      value: '115',
      label: 'SEC filers benchmarked',
      detail: '354 grounded claims measured across sectors.',
    },
    {
      value: '500+',
      label: 'tests passing',
      detail: 'Deterministic reliability harness with fault injection.',
    },
  ];

  return (
    <section
      id="benchmark"
      className="relative overflow-hidden px-4 sm:px-6 md:px-10 py-20 sm:py-28 scroll-mt-24"
    >
      {/* Starfield background */}
      <StarsBackground className="z-0" starDensity={0.00022} />
      <ShootingStars
        className="z-0"
        starColor="#8CC7FF"
        trailColor="#2EB9DF"
        minDelay={1500}
        maxDelay={4000}
      />
      {/* Fade the starfield into the flat page background above and below */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to bottom, #060a12, transparent)' }}
      />
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to top, #060a12, transparent)' }}
      />
      <div className="relative z-10 max-w-5xl mx-auto">
        <div className="text-center mb-12 sm:mb-16">
          <SectionLabel>Proof</SectionLabel>
          <SectionHeading>
            Every number here is <span className="text-[#6BB4F0]">measured, not marketed.</span>
          </SectionHeading>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 sm:p-8"
            >
              <p className="text-3xl sm:text-4xl font-semibold text-[#EAF2FB] tracking-tight">
                {stat.value}
              </p>
              <p className="mt-1 text-sm font-medium text-[#6BB4F0]">{stat.label}</p>
              <p className="mt-3 text-white/60 text-xs leading-relaxed">{stat.detail}</p>
            </div>
          ))}
          <div className="rounded-2xl border border-[#6BB4F0]/30 bg-[#6BB4F0]/[0.07] p-6 sm:p-8 flex flex-col justify-center">
            <ShieldCheck className="w-6 h-6 text-[#6BB4F0] mb-3" />
            <p className="text-sm text-[#EAF2FB] font-medium leading-relaxed">
              No model SDK imports in the verification core. Firewall-tested.
            </p>
          </div>
        </div>

        <p className="mt-8 text-center text-white/50 text-xs max-w-xl mx-auto">
          Aritiq declines to rule (INSUFFICIENT_EVIDENCE) rather than guess &mdash; this is by
          design. See our evidence philosophy below.
        </p>
      </div>
    </section>
  );
}

/* ---------- 5. Case study ---------- */
function CaseStudySection() {
  return (
    <section className="relative overflow-hidden px-4 sm:px-6 md:px-10 py-20 sm:py-28">
      {/* Toned dark-blue falling-pattern background (Aritiq blue over the page bg) */}
      <FallingPattern
        className="absolute inset-0 z-0 opacity-60 [mask-image:radial-gradient(ellipse_at_center,black,transparent_75%)]"
        color="#2f5a8a"
        backgroundColor="#060a12"
      />
      {/* Fade the pattern into the flat page background above and below */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to bottom, #060a12, transparent)' }}
      />
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to top, #060a12, transparent)' }}
      />
      <div className="relative z-10 max-w-3xl mx-auto">
        <div className="text-center mb-10">
          <SectionLabel>Real example</SectionLabel>
          <SectionHeading>
            When the verifier and the extractor <span className="text-[#6BB4F0]">disagree.</span>
          </SectionHeading>
        </div>

        <div className="rounded-2xl border border-white/10 bg-[#0b1424]/70 backdrop-blur-md p-6 sm:p-10">
          <p className="text-white/75 text-sm sm:text-base leading-relaxed">
            When we tested Aritiq against AMD&rsquo;s 10-K, it initially flagged an EPS calculation
            as wrong. Investigation showed the actual issue was upstream &mdash; the extraction
            step had used the wrong income basis. We fixed the extraction, not the verifier, and
            the check now passes correctly.
          </p>
          <p className="mt-5 text-white/75 text-sm sm:text-base leading-relaxed">
            This is the discipline behind every number on this page:{' '}
            <span className="text-[#EAF2FB] font-medium">
              verify, diagnose, document, fix
            </span>{' '}
            &mdash; never adjust a rule to make a demo look better.
          </p>
        </div>
      </div>
    </section>
  );
}

/* ---------- 6. Known limitations ---------- */
function LimitationsSection() {
  const [open, setOpen] = useState(false);

  return (
    <section className="px-4 sm:px-6 md:px-10 pb-20 sm:pb-28">
      <div className="max-w-3xl mx-auto">
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="w-full flex items-center justify-between rounded-2xl border border-white/10 bg-white/[0.03] px-6 py-4 text-left transition-colors hover:bg-white/[0.06]"
        >
          <span className="text-sm font-medium text-[#EAF2FB]">Known limitations</span>
          <ChevronDown
            className={`w-4 h-4 text-white/60 transition-transform duration-300 ${
              open ? 'rotate-180' : ''
            }`}
          />
        </button>
        <div
          className={`overflow-hidden transition-all duration-300 ${
            open ? 'max-h-64 opacity-100' : 'max-h-0 opacity-0'
          }`}
        >
          <p className="px-6 pt-4 text-white/60 text-sm leading-relaxed">
            Aritiq currently declines to verify certain filing types cleanly &mdash; very large
            conglomerate filings with non-standard statement structure, and REITs/banks/insurers
            for peer-comparison metrics where margin comparison isn&rsquo;t meaningful. We&rsquo;d
            rather say &ldquo;insufficient evidence&rdquo; than guess. Extraction robustness for
            these cases is active work.
          </p>
        </div>
      </div>
    </section>
  );
}

/* ---------- 7. Who it's for ---------- */
function WhoSection() {
  const audiences = [
    {
      icon: Bot,
      title: 'Teams building AI that cites financial numbers',
      body: 'Research assistants, analyst copilots, robo-advisors — anything that needs a pre-output check before a number reaches a user.',
    },
    {
      icon: FileSearch,
      title: 'Anyone using AI to read 10-Ks and 10-Qs',
      body: 'If a model summarizes or explains a filing for you, Aritiq double-checks the numbers it produced.',
    },
    {
      icon: BookOpen,
      title: 'Finance educators and students',
      body: 'A way to sanity-check AI-generated explanations of real filings against the actual source data.',
    },
  ];

  return (
    <section
      id="who"
      className="relative overflow-hidden px-4 sm:px-6 md:px-10 py-20 sm:py-28 scroll-mt-24"
    >
      {/* Animated topographic WebGL background (Aritiq blue) */}
      <ProceduralGroundBackground className="z-0 opacity-[0.5]" />
      {/* Scrim + fades keep card text readable and blend into the page */}
      <div className="pointer-events-none absolute inset-0 z-[1] bg-[#060a12]/55" />
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to bottom, #060a12, transparent)' }}
      />
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to top, #060a12, transparent)' }}
      />
      <div className="relative z-10 max-w-5xl mx-auto">
        <div className="text-center mb-12">
          <SectionLabel>Who it&rsquo;s for</SectionLabel>
          <SectionHeading>
            Built for people who <span className="text-[#6BB4F0]">ship numbers.</span>
          </SectionHeading>
        </div>
        <div className="grid sm:grid-cols-3 gap-4 sm:gap-6">
          {audiences.map((a) => (
            <div
              key={a.title}
              className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 sm:p-8"
            >
              <a.icon className="w-6 h-6 text-[#6BB4F0] mb-4" />
              <h3 className="text-sm font-semibold text-[#EAF2FB] mb-2 leading-snug">{a.title}</h3>
              <p className="text-white/60 text-xs leading-relaxed">{a.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/* ---------- 8. Try it now ---------- */
function TryItSection() {
  const [ticker, setTicker] = useState('AAPL');

  return (
    <section
      id="audit"
      className="relative overflow-hidden px-4 sm:px-6 md:px-10 py-20 sm:py-28 scroll-mt-24"
    >
      {/* Animated light-blue dotted-surface background */}
      <DottedSurface className="z-0 opacity-60" />
      {/* Fade the surface into the flat page background above and below */}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to bottom, #060a12, transparent)' }}
      />
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-[1] h-32"
        style={{ background: 'linear-gradient(to top, #060a12, transparent)' }}
      />
      <div className="relative z-10 max-w-3xl mx-auto text-center">
        <SectionLabel>Try it now</SectionLabel>
        <SectionHeading>
          Audit a 10-K <span className="text-[#6BB4F0]">in one click.</span>
        </SectionHeading>
        <p className="mt-4 text-white/60 text-sm">
          Pick a ticker and Aritiq extracts, verifies, and traces every claim in the latest filing.
        </p>

        <div className="mt-10 rounded-2xl border border-white/10 bg-white/[0.04] p-6 sm:p-10">
          <div className="flex flex-wrap items-center justify-center gap-2 mb-6">
            {TICKERS.map((t) => (
              <button
                key={t}
                onClick={() => setTicker(t)}
                className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${
                  ticker === t
                    ? 'bg-[#EAF2FB] text-[#0b1520]'
                    : 'border border-white/15 text-white/70 hover:text-white hover:border-white/30'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <input
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase().slice(0, 5))}
              placeholder="Ticker, e.g. AAPL"
              className="w-full sm:w-56 rounded-full border border-white/15 bg-transparent px-5 py-3 text-center text-sm font-medium text-[#EAF2FB] placeholder:text-white/40 focus:outline-none focus:border-[#6BB4F0]/60"
              aria-label="Ticker symbol"
            />
            <a
              href={`/app?ticker=${encodeURIComponent(ticker)}`}
              className="w-full sm:w-auto inline-flex items-center justify-center gap-2 rounded-full bg-white px-6 py-3 text-sm font-semibold text-[#13233d] transition-colors hover:bg-white/90"
            >
              Run the audit
              <ArrowRight className="w-4 h-4" />
            </a>
          </div>
          <p className="mt-5 text-white/40 text-xs">
            Opens the live Aritiq audit tool with the latest filing for {ticker || 'your ticker'}.
          </p>
        </div>
      </div>
    </section>
  );
}

/* ---------- 9. Footer ---------- */
function Footer() {
  return (
    <footer className="border-t border-white/10 px-4 sm:px-6 md:px-10 py-12 sm:py-16">
      <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-8">
        <div className="text-center sm:text-left">
          <p className="text-lg font-semibold tracking-tight text-[#EAF2FB]">Aritiq</p>
          <p className="mt-1 text-white/50 text-xs">LLMs parse. Code verifies.</p>
        </div>

        <div className="flex items-center gap-2 rounded-full border border-[#6BB4F0]/30 bg-[#6BB4F0]/[0.07] px-4 py-2">
          <Wrench className="w-3.5 h-3.5 text-[#6BB4F0]" />
          <span className="text-xs text-[#EAF2FB]/90">
            No model SDK imports in <code className="text-[#6BB4F0]">aritiq/core</code>
          </span>
        </div>

        <div className="flex items-center gap-6 text-xs text-white/60">
          <a href="#waitlist" className="hover:text-white transition-colors" id="waitlist">
            Join the waitlist
          </a>
          <a
            href="mailto:saiaathishk@gmail.com"
            className="hover:text-white transition-colors"
          >
            Contact
          </a>
        </div>
      </div>
    </footer>
  );
}

export default function LandingSections() {
  return (
    <div className="bg-[#060a12]">
      <ProblemSection />
      <HowItWorksSection />
      <BenchmarkSection />
      <CaseStudySection />
      <LimitationsSection />
      <WhoSection />
      <TryItSection />
      <Footer />
    </div>
  );
}
