import { useState, useEffect, useRef } from 'react';

const CONTACT_EMAIL = process.env.NEXT_PUBLIC_CONTACT_EMAIL;

interface CounterProps {
  value: number;
  decimals?: number;
  duration?: number;
  suffix?: string;
}

function Counter({ value, decimals = 0, duration = 1500, suffix = "" }: CounterProps) {
  const [count, setCount] = useState(0);
  const elementRef = useRef<HTMLSpanElement>(null);
  const hasAnimated = useRef(false);

  useEffect(() => {
    if (!('IntersectionObserver' in window)) {
      setCount(value);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        const [entry] = entries;
        if (entry.isIntersecting && !hasAnimated.current) {
          hasAnimated.current = true;
          let startTime: number | null = null;
          
          const animate = (timestamp: number) => {
            if (!startTime) startTime = timestamp;
            const progress = Math.min((timestamp - startTime) / duration, 1);
            // Ease out quad
            const easeProgress = progress * (2 - progress);
            const currentVal = easeProgress * value;
            setCount(currentVal);
            
            if (progress < 1) {
              requestAnimationFrame(animate);
            } else {
              setCount(value);
            }
          };
          
          requestAnimationFrame(animate);
        }
      },
      { threshold: 0.1 }
    );

    if (elementRef.current) {
      observer.observe(elementRef.current);
    }

    return () => {
      if (elementRef.current) {
        observer.unobserve(elementRef.current);
      }
    };
  }, [value, duration]);

  return (
    <span ref={elementRef} className="tabular-nums">
      {count.toFixed(decimals)}
      {suffix}
    </span>
  );
}

import {
  FileSearch,
  Calculator,
  ClipboardCheck,
  ShieldCheck,
  ChevronDown,
  ArrowRight,
  Bot,
  BookOpen,
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
          Language models extract information well.
          <br />
          <span className="text-[#6BB4F0]">Arithmetic requires deterministic execution.</span>
        </SectionHeading>
        <p className="mt-6 text-white/70 text-sm sm:text-base leading-relaxed">
          Language models are effective for unstructured text extraction, but struggle with complex multi-step math and accounting rules. To verify financial metrics, extraction must be separated from mathematical validation using a deterministic computing layer.
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
      body: 'A language model parses claims, numbers, and formulas from filings into structured JSON.',
    },
    {
      icon: Calculator,
      title: 'Verify',
      body: 'Deterministic code re-derives every claim using primary XBRL data and accounting rules.',
    },
    {
      icon: ClipboardCheck,
      title: 'Trace',
      body: 'Claims are assigned verification states (Verified, Wrong Math, Insufficient Evidence) with complete audit paths.',
    },
  ];

  return (
    <section
      id="how"
      className="relative overflow-hidden bg-[#060a12] px-4 sm:px-6 md:px-10 py-20 sm:py-28 scroll-mt-24"
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
          <SectionLabel>Architecture</SectionLabel>
          <SectionHeading>
            Isolated parser and <span className="text-[#6BB4F0]">calculation layers.</span>
          </SectionHeading>
        </div>

        <div className="flex flex-col lg:flex-row items-stretch gap-6 lg:gap-0">
          {/* Step 1 — the AI side */}
          <div className="flex-1 rounded-2xl border border-white/10 bg-white/[0.04] p-6 sm:p-8">
            <div className="flex items-center justify-between mb-5">
              <FileSearch className="w-6 h-6 text-[#6BB4F0]" />
              <span className="text-[10px] font-semibold uppercase tracking-widest rounded-full border border-[#6BB4F0]/40 text-[#6BB4F0] px-2.5 py-1">
                Parser
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
              Boundary
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
                    Calculation
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
          The calculation layer is deterministic and has zero model dependencies.
        </p>
      </div>
    </section>
  );
}

/* ---------- 4. Proof / benchmark ---------- */
function BenchmarkSection() {
  const stats = [
    {
      numericValue: 96.6,
      decimals: 1,
      suffix: '%',
      label: 'Precision',
      detail: 'The ratio of correctly verified or rejected assertions to total verified or rejected outputs.',
    },
    {
      numericValue: 3.4,
      decimals: 1,
      suffix: '%',
      label: 'False-Positive Rate',
      detail: 'The proportion of incorrect assertions accepted as valid.',
    },
    {
      numericValue: 79.4,
      decimals: 1,
      suffix: '%',
      label: 'Coverage',
      detail: 'The percentage of parsed assertions with sufficient primary source data to perform calculations.',
    },
    {
      numericValue: 115,
      decimals: 0,
      suffix: '',
      label: 'SEC Filers evaluated',
      detail: 'A representative set of filings across technology, industrial, and consumer sectors.',
    },
    {
      numericValue: 500,
      decimals: 0,
      suffix: '+',
      label: 'Integration Tests',
      detail: 'Automated test suite asserting calculation correctness and edge case validation.',
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
          <SectionLabel>Evaluation</SectionLabel>
          <SectionHeading>
            Measured <span className="text-[#6BB4F0]">benchmark results.</span>
          </SectionHeading>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
          {stats.map((stat) => (
            <div
              key={stat.label}
              className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 sm:p-8"
            >
              <p className="text-3xl sm:text-4xl font-semibold text-[#EAF2FB] tracking-tight">
                <Counter value={stat.numericValue} decimals={stat.decimals} suffix={stat.suffix} />
              </p>
              <p className="mt-1 text-sm font-medium text-[#6BB4F0]">{stat.label}</p>
              <p className="mt-3 text-white/60 text-xs leading-relaxed">{stat.detail}</p>
            </div>
          ))}
          <div className="rounded-2xl border border-[#6BB4F0]/30 bg-[#6BB4F0]/[0.07] p-6 sm:p-8 flex flex-col justify-center">
            <ShieldCheck className="w-6 h-6 text-[#6BB4F0] mb-3" />
            <p className="text-sm text-[#EAF2FB] font-medium leading-relaxed">
              Calculations are performed by local python libraries using verified financial schemas.
            </p>
          </div>
        </div>

        <p className="mt-8 text-center text-white/50 text-xs max-w-xl mx-auto">
          The pipeline fails safe: assertions are flagged as having insufficient evidence if source data is missing or ambiguous.
        </p>
      </div>
    </section>
  );
}

/* ---------- 5. Case study ---------- */
function CaseStudySection() {
  return (
    <section className="relative overflow-hidden bg-[#060a12] px-4 py-24 sm:px-6 sm:py-32 md:px-10">
      {/* Toned dark-blue falling-pattern background (Aritiq blue over the page bg) */}
      <FallingPattern
        className="absolute inset-0 z-0 opacity-95 [mask-image:radial-gradient(ellipse_at_center,black,transparent_88%)]"
        color="#6BB4F0"
        backgroundColor="#060a12"
        duration={80}
      />
      <div className="case-study-falling-lines pointer-events-none absolute inset-0 z-[1] opacity-70 [mask-image:radial-gradient(ellipse_at_center,black,transparent_82%)]" />
      {/* Fade the pattern into the flat page background above and below */}
      <div
        className="pointer-events-none absolute inset-0 z-[2] opacity-70"
        style={{
          backgroundImage:
            "radial-gradient(circle at 50% 35%, rgba(107,180,240,0.18), transparent 34%), linear-gradient(180deg, #060a12 0%, rgba(6,10,18,0.2) 42%, #060a12 100%)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-[3] h-28"
        style={{ background: 'linear-gradient(to bottom, #060a12, transparent)' }}
      />
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 z-[3] h-28"
        style={{ background: 'linear-gradient(to top, #060a12, transparent)' }}
      />
      <div className="relative z-10 max-w-3xl mx-auto">
        <div className="text-center mb-10">
          <SectionLabel>Analysis</SectionLabel>
          <SectionHeading>
            Case study: <span className="text-[#6BB4F0]">AMD 10-K discrepancy.</span>
          </SectionHeading>
        </div>

        <div className="rounded-2xl border border-[#6BB4F0]/25 bg-[#08111f]/80 p-6 shadow-[0_0_70px_rgba(107,180,240,0.16)] backdrop-blur-md sm:p-10 space-y-4 text-xs sm:text-sm text-white/75">
          <div>
            <span className="font-semibold text-[#EAF2FB] uppercase tracking-wider block mb-1">Issue:</span>
            An EPS reconciliation assertion was flagged as incorrect during automated evaluation of AMD&rsquo;s FY2024 filing.
          </div>
          <div>
            <span className="font-semibold text-[#EAF2FB] uppercase tracking-wider block mb-1">Root Cause:</span>
            The extraction model parsed an incorrect net income figure from a nearby table block, causing the re-calculation formula to mismatch.
          </div>
          <div>
            <span className="font-semibold text-[#EAF2FB] uppercase tracking-wider block mb-1">Resolution:</span>
            Improved table boundary definitions in the parser step. The verification calculation rules remained unmodified.
          </div>
          <div>
            <span className="font-semibold text-[#EAF2FB] uppercase tracking-wider block mb-1">Outcome:</span>
            Re-evaluation succeeded without further discrepancy. The verification logic continues to reject invalid inputs rather than modifying rules to fit extraction anomalies.
          </div>
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
          <span className="text-sm font-medium text-[#EAF2FB]">System limitations</span>
          <ChevronDown
            className={`w-4 h-4 text-white/60 transition-transform duration-300 ${
              open ? 'rotate-180' : ''
            }`}
          />
        </button>
        <div
          className={`overflow-hidden transition-all duration-300 ${
            open ? 'max-h-[500px] opacity-100' : 'max-h-0 opacity-0'
          }`}
        >
          <div className="px-6 pt-5 pb-2 text-white/60 text-xs sm:text-sm leading-relaxed space-y-3">
            <p>
              While the verification layer is completely deterministic, Aritiq has the following operational boundaries:
            </p>
            <ul className="list-disc list-inside space-y-2">
              <li>
                <span className="text-[#EAF2FB] font-medium">Model-dependent parsing:</span> Parsing narrative disclosures and unstructured tables relies on LLM-based layout analysis and token extraction.
              </li>
              <li>
                <span className="text-[#EAF2FB] font-medium">Evidence constraints:</span> The system fails safe. If assertions lack matching source disclosures or explicit values, they are classified as <span className="font-mono text-xs">INSUFFICIENT_EVIDENCE</span> rather than guessed.
              </li>
              <li>
                <span className="text-[#EAF2FB] font-medium">SEC filing focus:</span> The present verification ruleset and XBRL schema compiler are optimized for US SEC EDGAR filings (10-K, 10-Q, 8-K) and do not support international standards (IFRS) or private company reports.
              </li>
            </ul>
          </div>
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
      title: 'AI Analyst Tools & Copilots',
      body: 'Pre-output calculations and truth checks to verify parsed metrics before rendering to end users.',
    },
    {
      icon: FileSearch,
      title: 'Research & Extraction Pipelines',
      body: 'High-throughput parsing systems checking machine-extracted values against primary SEC database sources.',
    },
    {
      icon: BookOpen,
      title: 'Compliance & Audit Systems',
      body: 'Automated verification checkpoints ensuring internal alignment between different tables and narrative disclosures.',
    },
  ];

  return (
    <section
      id="who"
      className="relative overflow-hidden px-4 sm:px-6 md:px-10 py-20 sm:py-28 scroll-mt-24"
    >
      {/* Animated topographic WebGL background (Aritiq blue) */}
      <ProceduralGroundBackground className="z-0 opacity-[0.16] brightness-75" />
      {/* Scrim + fades keep card text readable and blend into the page */}
      <div className="pointer-events-none absolute inset-0 z-[1] bg-[radial-gradient(circle_at_50%_40%,rgba(107,180,240,0.08),rgba(6,10,18,0.92)_48%,#060a12_100%)]" />
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
          <SectionLabel>Applications</SectionLabel>
          <SectionHeading>
            Designed for automated <span className="text-[#6BB4F0]">financial pipelines.</span>
          </SectionHeading>
        </div>
        <div className="grid sm:grid-cols-3 gap-4 sm:gap-6">
          {audiences.map((a) => (
            <div
              key={a.title}
              className="rounded-2xl border border-[#6BB4F0]/15 bg-[#0b1424]/72 p-6 shadow-[0_18px_60px_rgba(0,0,0,0.28)] backdrop-blur-sm sm:p-8"
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
        <SectionLabel>Console</SectionLabel>
        <SectionHeading>
          Evaluate a <span className="text-[#6BB4F0]">filing.</span>
        </SectionHeading>
        <p className="mt-4 text-white/60 text-sm">
          Select a ticker to load the latest SEC filing and review re-calculated metrics.
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
              Run audit
              <ArrowRight className="w-4 h-4" />
            </a>
          </div>
          <p className="mt-5 text-white/40 text-xs">
            Loads target filing from SEC EDGAR database.
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
        <div className="text-center sm:text-left flex flex-col items-center sm:items-start gap-1">
          <img 
            src="/logo-text-light.png" 
            alt="Aritiq Logo" 
            className="h-12 w-auto object-contain" 
            style={{ filter: "drop-shadow(0 0 25px rgba(107, 180, 240, 0.35))" }}
          />
          <p className="mt-1 text-white/50 text-xs">Automated financial verification engine.</p>
        </div>

        <div className="flex items-center gap-6 text-xs text-white/60">
          <a href="#" className="hover:text-white transition-colors">
            GitHub
          </a>
          {CONTACT_EMAIL ? (
            <a
              href={`mailto:${CONTACT_EMAIL}`}
              className="hover:text-white transition-colors"
            >
              Contact
            </a>
          ) : null}
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
