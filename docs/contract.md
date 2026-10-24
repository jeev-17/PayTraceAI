# API contract

This document is the planned API contract for Milestone 0. Only
`GET /api/health` is implemented in this milestone; all other routes below are
planned and make no PayPal calls yet. Examples use JSON and illustrative IDs;
they are contract examples, not PayPal responses.

## Shared behavior

- API routes use the `/api` prefix and JSON request/response bodies.
- Errors use `{"error":{"code":"...","message":"..."}}`.
- Common errors: `400` invalid state or request, `404` resource not found,
  `409` uniqueness/state conflict, `422` schema validation, and `500`
  unexpected server error. An endpoint may have fewer applicable errors, as
  listed below.
- Configuration status reports booleans only; no configured value or secret is
  returned.
- Simulated records use `source: "simulated"` and never call PayPal payment
  endpoints.

## Endpoints

### `GET /api/health`

Request body: none.

Response `200`:

```json
{
  "status": "ok",
  "config_present": {
    "paypal_client_id": false,
    "paypal_client_secret": false,
    "paypal_base_url": true,
    "paypal_webhook_id": false,
    "database_url": true,
    "llm_provider": false,
    "llm_api_key": false,
    "llm_model": false,
    "frontend_origin": true,
    "pending_threshold_minutes": true
  }
}
```

Errors: `500` unexpected server error. A missing integration credential does
not prevent application startup; its presence is reported as `false`.

### `POST /api/orders`

Request:

```json
{"amount":"24.99","currency":"USD"}
```

Response `201`:

```json
{
  "id": 1,
  "paypal_order_id": "sandbox-order-id",
  "amount": "24.99",
  "currency": "USD",
  "status": "created",
  "source": "paypal_sandbox",
  "created_at": "2026-01-01T12:00:00Z",
  "updated_at": "2026-01-01T12:00:00Z",
  "last_verified_at": null,
  "last_verified_status": null
}
```

Errors: `422` invalid amount/currency, `502` PayPal API failure, `500`
unexpected server error. Order creation will require Sandbox configuration.

### `POST /api/orders/{id}/capture`

Request body: `{"confirm":true}`.

Response `200`:

```json
{"order_id":1,"status":"pending","message":"Capture result recorded for verification."}
```

Errors: `404` order not found, `409` capture is not valid for the current
state, `422` invalid request, `502` PayPal API failure, `500` unexpected
server error. A timeout is not a failure signal, and capture is never retried
automatically.

### `GET /api/orders`

Request body: none. Query parameters: `limit` (default 50, maximum 100),
`offset` (default 0), optional `status`, and optional `source`.

Response `200`:

```json
{"items":[{"id":1,"paypal_order_id":"sandbox-order-id","status":"created","source":"paypal_sandbox"}],"limit":50,"offset":0,"total":1}
```

Errors: `422` invalid pagination or filter, `500` unexpected server error.

### `GET /api/orders/{id}`

Request body: none.

Response `200`:

```json
{"id":1,"paypal_order_id":"sandbox-order-id","amount":"24.99","currency":"USD","status":"created","source":"paypal_sandbox","created_at":"2026-01-01T12:00:00Z","updated_at":"2026-01-01T12:00:00Z","last_verified_at":null,"last_verified_status":null}
```

Errors: `404` order not found, `500` unexpected server error.

### `POST /api/orders/{id}/verify`

Request body: `{}`.

Response `200`:

```json
{"order_id":1,"verified":true,"paypal_status":"COMPLETED","verified_at":"2026-01-01T12:01:00Z"}
```

Errors: `404` order not found, `502` PayPal verification unavailable, `500`
unexpected server error. The response status must be based on a PayPal API
verification, never a redirect, timeout, or webhook authenticity result.

### `POST /api/webhooks/paypal`

Request body: PayPal webhook JSON payload, passed as an untrusted payload.
PayPal signature-verification headers are required by the future handler.

Response `200`:

```json
{"received":true,"event_id":"event-id","verification_status":"verified","duplicate_delivery":false}
```

Errors: `400` malformed payload, `401` webhook authenticity verification
failed, `422` missing/invalid event data, `500` unexpected server error.
Webhook authenticity and payment status are validated separately; duplicate
delivery does not imply duplicate charge.

### `GET /api/orders/{id}/events`

Request body: none. Query parameters: `limit` (default 50, maximum 100),
`offset` (default 0).

Response `200`:

```json
{"items":[{"id":1,"paypal_event_id":"event-id","event_type":"PAYMENT.CAPTURE.COMPLETED","source":"paypal_sandbox","verification_status":"verified","is_duplicate_delivery":false}],"limit":50,"offset":0,"total":1}
```

Errors: `404` order not found, `422` invalid pagination, `500` unexpected
server error.

### `GET /api/events`

Request body: none. Query parameters: `limit` (default 50, maximum 100),
`offset` (default 0), optional `event_type`, optional `source`.

Response `200`:

```json
{"items":[{"id":1,"paypal_event_id":"event-id","event_type":"PAYMENT.CAPTURE.COMPLETED","source":"paypal_sandbox","verification_status":"verified","is_duplicate_delivery":false}],"limit":50,"offset":0,"total":1}
```

Errors: `422` invalid pagination or filter, `500` unexpected server error.

### `GET /api/incidents`

Request body: none. Query parameters: `limit` (default 50, maximum 100),
`offset` (default 0), optional `status`, and optional `severity`.

Response `200`:

```json
{"items":[{"id":1,"rule_id":"STATE_MISMATCH","severity":"medium","status":"open","order_id":1,"evidence_event_ids":[1],"description":"Observed state needs verification.","created_at":"2026-01-01T12:00:00Z"}],"limit":50,"offset":0,"total":1}
```

Errors: `422` invalid pagination or filter, `500` unexpected server error.

### `GET /api/incidents/{id}`

Request body: none.

Response `200`:

```json
{"id":1,"rule_id":"STATE_MISMATCH","severity":"medium","status":"open","order_id":1,"evidence_event_ids":[1],"description":"Observed state needs verification.","created_at":"2026-01-01T12:00:00Z","resolved_at":null,"resolution_reason":null}
```

Errors: `404` incident not found, `500` unexpected server error.

### `POST /api/incidents/{id}/resolve`

Request:

```json
{"resolution_reason":"Verified the order state through PayPal."}
```

Response `200`:

```json
{"id":1,"status":"resolved","resolved_at":"2026-01-01T12:05:00Z","resolution_reason":"Verified the order state through PayPal."}
```

Errors: `404` incident not found, `409` incident already resolved, `422`
missing/invalid resolution reason, `500` unexpected server error. Resolution
does not trigger payment operations.

### `POST /api/incidents/{id}/investigate`

Request:

```json
{"question":"What evidence is available for this incident?"}
```

Response `200`:

```json
{"incident_id":1,"summary":"Investigation summary.","confirmed_facts":[],"hypotheses":[],"missing_evidence":[]}
```

Errors: `404` incident not found, `422` invalid question, `503` LLM
configuration/provider unavailable, `500` unexpected server error. Treat
payloads and logs as untrusted input; AI output cannot change incident status
or trigger payment operations.

### `GET /api/simulation/scenarios`

Request body: none.

Response `200`:

```json
{"items":[{"id":"delayed-webhook","name":"Delayed webhook","description":"Simulated delayed event delivery."}]}
```

Errors: `500` unexpected server error.

### `POST /api/simulation/run`

Request:

```json
{"scenario_id":"delayed-webhook"}
```

Response `201`:

```json
{"run_id":"simulation-run-id","status":"completed","source":"simulated","created_record_ids":[1]}
```

Errors: `404` scenario not found, `422` invalid request, `500` unexpected
server error. Simulation never calls real PayPal payment endpoints, and every
created record is marked `source: "simulated"`.

### `GET /api/simulation/results`

Request body: none. Query parameters: `limit` (default 50, maximum 100),
`offset` (default 0), optional `run_id`.

Response `200`:

```json
{"items":[{"run_id":"simulation-run-id","scenario_id":"delayed-webhook","status":"completed","source":"simulated","created_at":"2026-01-01T12:00:00Z"}],"limit":50,"offset":0,"total":1}
```

Errors: `422` invalid pagination or filter, `500` unexpected server error.

### `GET /api/dashboard/summary`

Request body: none.

Response `200`:

```json
{"orders":{"total":0,"pending":0},"events":{"total":0},"incidents":{"open":0,"resolved":0},"generated_at":"2026-01-01T12:00:00Z"}
```

Errors: `500` unexpected server error.

## Incident rule IDs

- `DUPLICATE_DELIVERY`
- `OUT_OF_ORDER_EVENT`
- `STATE_MISMATCH`
- `STALE_PENDING_ORDER`
- `UNKNOWN_ORDER_EVENT`
- `UNCERTAIN_CAPTURE`
- `REPEATED_CAPTURE_ATTEMPT`

An incident is based on evidence and is not proof of a duplicate charge.
Repeated capture attempts are recorded as evidence; capture is never
automatically retried.

## Order lifecycle states and transitions

Application lifecycle states: `created`, `approved`, `pending`, `completed`,
`declined`, `voided`, and `unknown`.

Allowed observed transitions:

- `created` -> `approved`, `pending`, `completed`, `declined`, `voided`, or
  `unknown`
- `approved` -> `pending`, `completed`, `declined`, `voided`, or `unknown`
- `pending` -> `completed`, `declined`, `voided`, or `unknown`
- `completed`, `declined`, and `voided` are terminal for automatic state
  updates; a conflicting observation is recorded for investigation, not
  silently applied.
- `unknown` -> any state only after a verified observation; unverified input
  cannot establish a transition.

These application states summarize observations and do not claim to enumerate
every PayPal API status. Verification records the actual verified status
separately. A redirect, timeout, duplicate delivery, or successful webhook
signature alone does not prove payment outcome.
