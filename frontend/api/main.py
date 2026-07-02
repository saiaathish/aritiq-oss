"""Vercel Python entrypoint for the Aritiq API.

Vercel's Python builder only picks up files inside api/, so this module just
re-exports the real, fully-featured FastAPI app defined in backend/app.py
(health, audit, audit-multi, audit-ticker, dashboard, timeline, analyst,
enterprise, Supabase auth + rate limiting). The old standalone app that used
to live in this file only implemented /health, /audit, /audit/export and
/examples — it was missing /audit-multi, /audit-ticker, /dashboard/{ticker}
and /timeline/{ticker}, which the frontend also calls. Keeping the actual app
code in backend/app.py lets `uvicorn backend.app:app --reload` keep working
for local dev exactly as documented there.

frontend/vercel.json rewrites the bare API paths (/audit, /examples, etc.)
that the frontend calls onto /api/main so this function actually receives
those requests.
"""

from backend.app import app  # noqa: F401
