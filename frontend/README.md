# Aritiq — Demo UI

The frontend for Aritiq: paste a source document and an AI-generated summary, run
an audit, and get the Aritiq Score plus a fully inspectable, per-claim trace of
every numeric verdict.

Built with **Next.js 14 (App Router) · TypeScript · Tailwind CSS · Framer Motion ·
shadcn-style components**. Dark, glassmorphic, B2B-fintech.

> The UX thesis: *every verdict is inspectable.* Click any claim to see the
> operands, where each was found in the source, the recomputed value, and the
> verdict. The math is the product, so the UI never hides it.

---

## Quick start

Aritiq is two processes: the FastAPI backend (the auditing engine) and this
Next.js frontend.

### 1. Backend (from the repo root, one level up)

```bash
pip install -r backend/requirements.txt
uvicorn backend.app:app --reload --port 8000
```

The backend serves the bundled example documents **without an API key** (it
replays the saved Day 2 extractions). To audit your own documents, set a model
key first:

```bash
export ANTHROPIC_API_KEY=sk-...        # default provider
# or: export OPENAI_API_KEY=...  ARITIQ_PROVIDER=openai
```

### 2. Frontend (this directory)

```bash
npm install
npm run dev
```

Open http://localhost:3000. Click **Load example → Northwind…**, then **Audit**
to see the full experience with no key required.

If your backend runs somewhere other than `http://localhost:8000`, set
`NEXT_PUBLIC_API_URL` (see `.env.local.example`).

---

## What you'll see

- **Input panel** — two resizable textareas (Source / Summary), an Audit button
  with a live loading state, and a "Load example" menu. `⌘/Ctrl + Enter` submits.
- **Score ring** — an animated circular gauge that counts up to the Aritiq Score,
  colored green (≥80) / amber (50–79) / red (<50), with raw status counts as pills.
- **Per-claim trace** — one row per claim (status · operation · stated ·
  recomputed · Δ). Click a row to expand it: full claim text, every operand with
  its source text and a grounded / inferred / missing badge, and the verdict
  explanation.
- **Error handling** — if the API is unreachable or returns an error, an inline
  banner appears with a Retry button. Nothing crashes.

### Status colors

| Status | Color |
|---|---|
| `VERIFIED` | green |
| `WRONG_MATH` | red (bold — the headline catch) |
| `UNSUPPORTED_NUMBER` | amber |
| `AMBIGUOUS` | blue |
| `UNCHECKED` | gray, italic |

---

## Structure

```
frontend/
  app/
    layout.tsx        # fonts, dark theme, ambient background
    page.tsx          # single-page orchestration (state, fetch, transitions)
    globals.css       # theme tokens, glass utilities, reduced-motion
  components/
    InputPanel.tsx    # textareas + Audit + Load example
    ScoreRing.tsx     # animated ring + count-up + count pills
    ClaimsTable.tsx   # column header + animated rows
    ClaimRow.tsx      # expandable inspectable trace (AnimatePresence + layout)
    StatusBadge.tsx
    ErrorBanner.tsx
    ui/               # shadcn-style button, textarea, card
  lib/
    api.ts            # fetch wrapper (audit, examples) + typed errors
    types.ts          # AuditResult mirror of the backend
    utils.ts          # cn, status config, formatting
```

Single page, no routing, no auth — exactly as specified.

## Notes

- Every animation is purposeful (entrance, count-up, row expansion, state
  transitions) and uses the design system's expo-out easing. `prefers-reduced-motion`
  is respected throughout.
- Numbers render with tabular figures (`.tnum`) so columns never jitter.
- The app degrades gracefully: examples load if the backend is up; the UI still
  renders and shows a clear banner if it isn't.
```
