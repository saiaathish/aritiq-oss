# Phase 4 enterprise measurement

Deterministic local SQLite run. No model, no SEC network.

## Result

- `workspace_created`: `true`
- `users`: `1`
- `api_keys_total`: `3`
- `rotated_old_key_rejected`: `true`
- `new_rotated_key_accepted`: `true`
- `usage_calls_recorded`: `1`
- `audit_history_count`: `1`
- `audit_detail_reopens`: `true`
- `watchlist_count`: `1`
- `webhook_count`: `1`
- `webhooks_queued`: `1`
- `first_dispatch`: `{"delivered": 0, "failed_or_retrying": 1}`
- `second_dispatch`: `{"delivered": 1, "failed_or_retrying": 0}`
- `delivered_payloads`: `1`
- `delivery_url`: `"https://example.com/hook"`
- `extra_key_prefix`: `"ariq_QHk4lHx"`

## Gates

- Workspace/user/key model exists and authenticates per key.
- Rotation disables old key and accepts new key.
- Completed audit can be listed and reopened.
- Watchlist filing event can enqueue webhook delivery.
- Webhook retry/backoff path records failure then succeeds.
