"""Deterministic Phase 4 enterprise-feature measurement.

No model calls, no SEC network calls. This probes the persistence/identity layer
that Phase 4 adds around already-measured verifier outputs.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import aritiq.enterprise as enterprise


SAMPLE_AUDIT = {
    "score": {"overall": 100.0, "weighted": 100.0, "unweighted": 100.0},
    "results": [
        {
            "status": "VERIFIED",
            "claim": {"claim_text": "Assets equal liabilities plus equity."},
        },
        {
            "status": "INSUFFICIENT_EVIDENCE",
            "claim": {"claim_text": "Cash ties out without restricted cash context."},
        },
    ],
    "issues": [],
    "conflicts": [],
}


def run() -> dict:
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "enterprise.sqlite")
        created = enterprise.create_workspace(
            "Measured Org",
            "analyst@example.com",
            key_label="measurement",
            limit_per_minute=7,
            path=path,
        )
        org_id = created["org"]["id"]
        raw_key = created["api_key"]["key"]
        auth = enterprise.authenticate(raw_key, path=path)
        assert auth is not None
        enterprise.record_usage(auth, "GET", "/enterprise/team", path=path)

        extra_key = enterprise.create_api_key(
            org_id,
            user_id=auth.user_id,
            label="secondary",
            limit_per_minute=11,
            path=path,
        )
        rotated = enterprise.rotate_api_key(created["api_key"]["id"], org_id, path=path)
        assert enterprise.authenticate(raw_key, path=path) is None
        assert enterprise.authenticate(rotated["key"], path=path) is not None

        audit_id = enterprise.store_audit(
            auth,
            SAMPLE_AUDIT,
            ticker="FAKE",
            source_label="synthetic verified audit",
            path=path,
        )
        audit_list = enterprise.list_audits(org_id, path=path)
        audit_detail = enterprise.get_audit(org_id, audit_id, path=path)
        assert audit_detail is not None

        watch = enterprise.add_watchlist(org_id, "FAKE", path=path)
        enterprise.update_watchlist_seen(org_id, watch["id"], "0001", path=path)
        hook = enterprise.add_webhook(org_id, "https://example.com/hook", path=path)
        queued = enterprise.enqueue_webhook_deliveries(
            org_id,
            watchlist_id=watch["id"],
            ticker="FAKE",
            accession="0002",
            filing={"form": "10-K", "accession": "0002"},
            path=path,
        )

        def fail(_url, _payload):
            raise RuntimeError("temporary failure")

        first_dispatch = enterprise.dispatch_due_webhooks(org_id, deliver=fail, path=path)
        with enterprise.connect(path) as conn:
            conn.execute("UPDATE webhook_deliveries SET next_attempt_at = 0")
            conn.commit()
        delivered = []
        second_dispatch = enterprise.dispatch_due_webhooks(
            org_id,
            deliver=lambda url, payload: delivered.append((url, payload)),
            path=path,
        )

        dashboard = enterprise.api_key_dashboard(org_id, path=path)
        return {
            "workspace_created": created["org"]["name"] == "Measured Org",
            "users": 1,
            "api_keys_total": len(dashboard["api_keys"]),
            "rotated_old_key_rejected": enterprise.authenticate(raw_key, path=path) is None,
            "new_rotated_key_accepted": enterprise.authenticate(rotated["key"], path=path) is not None,
            "usage_calls_recorded": sum(k["usage"]["calls"] for k in dashboard["api_keys"]),
            "audit_history_count": len(audit_list),
            "audit_detail_reopens": audit_detail["result"] == SAMPLE_AUDIT,
            "watchlist_count": len(enterprise.list_watchlists(org_id, path=path)),
            "webhook_count": len(enterprise.list_webhooks(org_id, path=path)),
            "webhooks_queued": queued,
            "first_dispatch": first_dispatch,
            "second_dispatch": second_dispatch,
            "delivered_payloads": len(delivered),
            "delivery_url": hook["url"],
            "extra_key_prefix": extra_key["key_prefix"],
        }


def write_report(metrics: dict, path: Path) -> None:
    lines = [
        "# Phase 4 enterprise measurement",
        "",
        "Deterministic local SQLite run. No model, no SEC network.",
        "",
        "## Result",
        "",
    ]
    for key, value in metrics.items():
        lines.append(f"- `{key}`: `{json.dumps(value, sort_keys=True)}`")
    lines.extend(
        [
            "",
            "## Gates",
            "",
            "- Workspace/user/key model exists and authenticates per key.",
            "- Rotation disables old key and accepts new key.",
            "- Completed audit can be listed and reopened.",
            "- Watchlist filing event can enqueue webhook delivery.",
            "- Webhook retry/backoff path records failure then succeeds.",
            "",
        ]
    )
    path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--md", type=Path)
    args = parser.parse_args()
    metrics = run()
    failed = [
        k
        for k, v in metrics.items()
        if k
        in {
            "workspace_created",
            "rotated_old_key_rejected",
            "new_rotated_key_accepted",
            "audit_detail_reopens",
        }
        and not v
    ]
    if metrics["api_keys_total"] < 2:
        failed.append("api_keys_total")
    if metrics["audit_history_count"] != 1:
        failed.append("audit_history_count")
    if metrics["webhooks_queued"] != 1 or metrics["delivered_payloads"] != 1:
        failed.append("webhook_delivery")
    if metrics["first_dispatch"] != {"delivered": 0, "failed_or_retrying": 1}:
        failed.append("webhook_retry")
    if metrics["second_dispatch"] != {"delivered": 1, "failed_or_retrying": 0}:
        failed.append("webhook_success")
    if args.md:
        write_report(metrics, args.md)
    print(json.dumps({"metrics": metrics, "failed": failed}, indent=2, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

