# API notes: Seedance video generation on BytePlus ModelArk

This is an independent sample. It is not affiliated with BytePlus.

# Findings

Read on 2026-11-23 from the official BytePlus ModelArk documentation. Check the live pages before relying on these facts.

## 1. Sources

| # | Page | URL | Page "Last updated" |
|---|------|-----|---------------------|
| S1 | Create a video generation task | https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api | 2026-11-20 05:11 |
| S2 | Retrieve a video generation task | https://docs.byteplus.com/en/docs/modelark/get-video-generation-task-api | 2026-11-19 17:17 |
| S3 | List video generation tasks | https://docs.byteplus.com/en/docs/modelark/list-video-generation-tasks-api | 2026-11-19 17:17 |
| S4 | Cancel or delete a task | https://docs.byteplus.com/en/docs/modelark/cancel-or-delete-video-generation-tasks-api | 2026-11-19 17:17 |
| S5 | Base URL and authentication | https://docs.byteplus.com/en/docs/modelark/base-url-and-authentication | 2026-11-20 16:39 |
| S6 | Error codes | https://docs.byteplus.com/en/docs/modelark/error-codes | 2026-11-16 19:01 |
| S7 | Pricing | https://docs.byteplus.com/en/docs/modelark/model-pricing | 2026-11-19 17:19 |
| S8 | Model list | https://docs.byteplus.com/en/docs/modelark/model-list | 2026-11-23 14:18 |
| S9 | Video generation tutorial | https://docs.byteplus.com/en/docs/modelark/video-generation-tutorial | 2026-11-20 05:11 |
| S10 | Dreamina Seedance 2.5 tutorial | https://docs.byteplus.com/en/docs/modelark/seedance-2-5 | 2026-11-20 05:11 |
| S11 | Activate Seedance 2.5 / 2.0 models | https://docs.byteplus.com/en/docs/modelark/seedance-model-activation-usage-and-refund | 2026-11-19 17:18 |
| S12 | Region availability | https://docs.byteplus.com/en/docs/modelark/region-availability | 2026-11-19 11:28 |
| S13 | Obtain and configure an API key | https://docs.byteplus.com/en/docs/modelark/api-key | 2026-11-18 20:12 |
| S14 | Quick start | https://docs.byteplus.com/en/docs/modelark/quick-start | 2026-11-19 11:28 |
| S15 | Enable model inference limits | https://docs.byteplus.com/en/docs/modelark/enable-model-inference-limit-api | 2026-10-22 19:36 |
| S16 | Free trial page (marketing, not docs) | https://www.byteplus.com/en/activity/free | no stamp |
| P1 | Live probe with a dummy key, no account, no cost | GET and POST on the S1/S2 endpoints | run 2026-11-23 18:00 GMT |

## 2. Base URL, regions, authentication

- Base URL (S5, S8, S12): `https://ark.ap-southeast.bytepluses.com/api/v3` (region `ap-southeast-1`).
- A second region exists: `eu-west-1`, `https://ark.eu-west.bytepluses.com/api/v3`. S8 says only `seed-2-0` and `seedream-5-0-lite` run there. So Seedance runs in `ap-southeast-1` only.
- API keys and model activation are isolated by region (S12).
- Auth header: `Authorization: Bearer $ARK_API_KEY`. S1 and S2 say these endpoints accept API key authentication only.
- A key belongs to one project. It can be restricted to chosen model IDs and to chosen IP addresses (S13). An account can hold up to 50 keys.
- The docs name the variable `ARK_API_KEY` in every example.

## 3. Endpoints

| Action | Call | Returns |
|--------|------|---------|
| Create | `POST /contents/generations/tasks` | `{"id": "cgt-..."}` |
| Get | `GET /contents/generations/tasks/{id}` | task object |
| List | `GET /contents/generations/tasks?page_num=&page_size=&filter.status=&filter.task_ids=&filter.model=&filter.service_tier=` | task list |
| Cancel / delete | `DELETE /contents/generations/tasks/{id}` | `{}` |

List defaults (S3): `filter.service_tier` defaults to `default` (online), so offline (`flex`) tasks need `filter.service_tier=flex`. `page_num` defaults to 1. `page_size` defaults to 20, range 1–500.

Cancel works only on `queued` tasks. `running` tasks cannot be cancelled (S4). The create parameter list (S1) has no idempotency key.

## 4. Models (S7, S8)

| Model ID | Text to video | First-frame image to video | Resolutions (default) | Duration, seconds (default) | Offline tier |
|----------|---------------|----------------------------|-----------------------|-----------------------------|--------------|
| `dreamina-seedance-2-5-260628` | yes | yes | 480p 720p 1080p 4k (720p) | 4–30 or -1 (-1) | no |
| `dreamina-seedance-2-5-flash-261115` | yes | yes | 480p 720p (720p) | 4–30 or -1 (-1) | no |
| `dreamina-seedance-2-0-260128` | yes | yes | 480p 720p 1080p 4k (720p) | 4–15 or -1 (5) | no |
| `dreamina-seedance-2-0-fast-260128` | yes | yes | 480p 720p (720p) | 4–15 or -1 (5) | no |
| `dreamina-seedance-2-0-mini-260615` | yes | yes | 480p 720p (720p) | 4–15 or -1 (5) | no |
| `seedance-1-0-pro-250528` | yes | yes | 480p 720p 1080p (1080p) | 2–12 (5) | yes |
| `seedance-1-0-pro-fast-251015` | yes | yes | 480p 720p 1080p (1080p) | 2–12 (5) | yes |

All output is 24 fps. Output is `.mp4` (2.5 series can also return `.mov`).

## 5. Create parameters this project uses (S1)

- `model` (required), `content` (required list).
- Text item: `{"type":"text","text":"..."}`. Prompt length is a recommendation only: at most 1,000 English words.
- Image item: `{"type":"image_url","image_url":{"url":"https://..."},"role":"first_frame"}`. A public image URL is supported. One image for first-frame mode.
- Image limits: jpeg, png, webp, bmp, tiff, gif (2.x also heic, heif); width/height ratio 0.4–2.5; each side 300–6000 px; under 30 MB.
- 2.x models reject uploaded images with real human faces.
- `resolution`: see the models table.
- `ratio`: `16:9 4:3 1:1 3:4 9:16 21:9 adaptive`.
  - 1.0 series, text to video: fixed ratios only. `adaptive` is not supported.
  - 1.0 series, image to video: fixed or `adaptive`.
  - 2.0 series: fixed or `adaptive` for both modes.
  - 2.5 series, text to video: fixed or `adaptive`.
  - 2.5 series, first-frame image to video: `adaptive` only. The model "automatically preserves the aspect ratio of the first-frame image" (S1). So the output size may match none of the six fixed ratios in section 10.
- `duration`: whole seconds, ranges in the models table.
- `service_tier`: `default` (online) or `flex` (offline, 50% price, hours of delay). `flex` is not supported on 2.5 and 2.0 series.
- `callback_url`: BytePlus POSTs the task object on each status change. For `succeeded` and `failed` it retries 3 times if not confirmed in 5 s.
- `execution_expires_after`: default 172800 s (48 h), range 3600–259200. After it, the task status becomes `expired`.
- Not used by this project: `frames`, `seed`, `camera_fixed`, `watermark`, `generate_audio`, `return_last_frame`, `draft`, `priority`, `safety_identifier`, `output_format`, video, audio and reference inputs.

## 6. Task object and states (S2)

- States: `queued`, `running`, `succeeded`, `failed`, `expired`, `cancelled`.
- On success: `content.video_url`, `usage.completion_tokens`, `usage.total_tokens` (equal for video), `created_at`, `updated_at` (Unix seconds), `resolution`, `ratio`, `duration`, `framespersecond`, `service_tier`.
- On failure: `error.code`, `error.message`.
- Seedance 2.5 can fail after creation for parameter reasons (`InvalidParameter.TaskTypeConstraint`, `InvalidParameter.TaskTypeMismatch`). These arrive as a `failed` task, not as a create error (S10).
- Example success body from S2: `{"id":"cgt-2025******-****","model":"dreamina-seedance-2-0-260128","status":"succeeded","content":{"video_url":"https://ark-content-generation-ap-southeast-1.tos-ap-southeast-1.volces.com/xxx"},"usage":{"completion_tokens":108900,"total_tokens":108900},"created_at":1743414619,"updated_at":1743414673,"seed":10,"resolution":"720p","ratio":"16:9","duration":5,"framespersecond":24,"service_tier":"default","execution_expires_after":172800,"generate_audio":true,"draft":false,"priority":0}`

## 7. Expiry and retention (S2, S9)

- The video URL is valid for 24 hours.
- A URL from a 2.5 series model can be downloaded at most 100 times.
- A task ID is valid for 7 days from `created_at`.
- Cancelled task records are deleted after 24 hours.

## 8. Rate limits (S8, S9)

| Limit | Value |
|-------|-------|
| Create, 2.x models | RPM 600 enterprise / 180 individual; concurrency 10 / 3 |
| Create, 2.0 at 4K | RPM 15; concurrency 1 |
| Create, 1.0 models | RPM 600; concurrency 10; flex 500B tokens per day |
| Get task | 20 requests per second per account |
| List tasks | 1 request per second per account |
| Cancel / delete | 20 requests per second per account |

Over the concurrency limit, new tasks wait in the queue. Over a rate limit, the API returns HTTP 429. S8 calls these "theoretical maximum values".

## 9. Error codes (S6) and the error body (P1)

Observed body (P1): `{"error":{"code":"AuthenticationError","message":"The API key format is incorrect. Request id: 0217...","param":"","type":"Unauthorized"}}` with HTTP 401. Observed headers: `x-request-id`, and `x-error-code: AuthN_AuthenticationError` (not the same value as the body code).

| HTTP | Codes | Meaning |
|------|-------|---------|
| 400 | `MissingParameter*`, `InvalidParameter*`, `InvalidImageURL.*` | bad request |
| 400 | `*SensitiveContentDetected*` (incl. `.PolicyViolation`, `.PrivacyInformation`) | content refused |
| 401 | `AuthenticationError` | key missing or invalid |
| 401 | `InvalidAccountStatus` | account problem |
| 403 | `AccountOverdueError`, `OperationDenied.ServiceOverdue` | balance overdue |
| 403 | `AccessDenied`, `OperationDenied.ServiceNotOpen` | no access / model not activated |
| 404 | `ModelNotOpen`, `InvalidEndpointOrModel.NotFound`, `InvalidEndpointOrModel.ModelIDAccessDisabled` | model not activated or not allowed |
| 404 | `NotFound.*` | resource not found |
| 429 | `RateLimitExceeded.*`, `ModelAccountRpmRateLimitExceeded`, `ModelAccountTpmRateLimitExceeded`, `APIAccountRpmRateLimitExceeded`, `AccountRateLimitExceeded`, `ServerOverloaded`, `RequestBurstTooFast` | slow down, retry later |
| 429 | `QuotaExceeded`, `SetLimitExceeded`, `InflightBatchsizeExceeded` | a quota or set limit is reached |
| 500 | `InternalServiceError` | server error |

## 10. Pricing (S7), USD per million tokens, input without video

| Model | 480p and 720p | 1080p | 4K | Offline |
|-------|---------------|-------|----|---------|
| `dreamina-seedance-2-5-260628` | 10.70 | 11.7 | 4.7 | not supported |
| `dreamina-seedance-2-5-flash-261115` | 7.0 | not supported | not supported | not supported |
| `dreamina-seedance-2-0-260128` | 7.0 | 7.7 | 4.0 | not supported |
| `dreamina-seedance-2-0-fast-260128` | 5.6 | not supported | not supported | not supported |
| `dreamina-seedance-2-0-mini-260615` | 3.5 | not supported | not supported | not supported |
| `seedance-1-0-pro-250528` | 2.5 (all resolutions) | | | 1.25 |
| `seedance-1-0-pro-fast-251015` | 1 (all resolutions) | | | 0.5 |

- Formula (S7): tokens = (input video seconds + output seconds) × width × height × frame rate ÷ 1024. Cost = tokens × unit price. This project sends no input video.
- S7: "Token consumption values are estimates. Actual consumption is determined by usage.completion_tokens in the API response."
- S7: "You are only charged for successfully generated videos."
- Arrears: services stop after 2 hours with a balance below zero.
- The formula was checked against the docs' own examples (16:9, 5 s). All match: 1.0 pro 480p = 48,600 tokens = $0.12; 2.5 at 480p = $0.514; at 720p = $1.156; at 1080p = $2.843; at 4K = $4.568.
- More docs examples, 16:9, 5 s: 2.5 flash $0.34 (480p), $0.76 (720p); 2.0 $0.35, $0.76, $1.87 (1080p), $3.89 (4K); 2.0 fast $0.28, $0.60; 2.0 mini $0.18, $0.38; 1.0 pro 102,960 tokens = $0.26 (720p), 244,800 tokens = $0.61 (1080p); 1.0 pro fast $0.05, $0.10, $0.24.

Output pixel sizes, width × height (S1). They differ by series, and the formula needs them.

| Resolution | Ratio | 2.5 series | 2.0 series | 1.0 series |
|------------|-------|------------|------------|------------|
| 480p | 16:9 | 854×480 | 864×496 | 864×480 |
| 480p | 4:3 | 752×560 | 752×560 | 736×544 |
| 480p | 1:1 | 640×640 | 640×640 | 640×640 |
| 480p | 3:4 | 560×752 | 560×752 | 544×736 |
| 480p | 9:16 | 480×854 | 496×864 | 480×864 |
| 480p | 21:9 | 992×432 | 992×432 | 960×416 |
| 720p | 16:9 | 1280×720 | 1280×720 | 1248×704 |
| 720p | 4:3 | 1112×834 | 1112×834 | 1120×832 |
| 720p | 1:1 | 960×960 | 960×960 | 960×960 |
| 720p | 3:4 | 834×1112 | 834×1112 | 832×1120 |
| 720p | 9:16 | 720×1280 | 720×1280 | 704×1248 |
| 720p | 21:9 | 1470×630 | 1470×630 | 1504×640 |
| 1080p | 16:9 | 1920×1080 | 1920×1080 | 1920×1088 |
| 1080p | 4:3 | 1664×1248 | 1664×1248 | 1664×1248 |
| 1080p | 1:1 | 1440×1440 | 1440×1440 | 1440×1440 |
| 1080p | 3:4 | 1248×1664 | 1248×1664 | 1248×1664 |
| 1080p | 9:16 | 1080×1920 | 1080×1920 | 1088×1920 |
| 1080p | 21:9 | 2206×946 | 2206×946 | 2176×928 |
| 4k | 16:9 | 3840×2160 | 3840×2160 | – |
| 4k | 4:3 | 3326×2494 | 3326×2494 | – |
| 4k | 1:1 | 2880×2880 | 2880×2880 | – |
| 4k | 3:4 | 2494×3326 | 2494×3326 | – |
| 4k | 9:16 | 2160×3840 | 2160×3840 | – |
| 4k | 21:9 | 4398×1886 | 4398×1886 | – |

1080p and 4k are not supported on 2.5 flash, 2.0 fast and 2.0 mini.

## 11. Account requirements (S11, S15, S16)

- 2.5 and 2.0 series need one of: USD 30 available balance, an AI Savings Plan of USD 30 or more, or a resource pack of USD 30 or more (S11).
- In the console, Billing overview shows the account balance, and Usage statistics shows token usage (S11). S11 does not say where the billed amount of one task is shown.
- A cumulative usage limit per model can be set (S15). When reached, calls return 429 `SetLimitExceeded`.
- The marketing page (S16) lists a free quota of 2M tokens for "ByteDance-Seedance-1.0-pro" for "eligible customers".

## 12. Not confirmed

1. Balance rules for the 1.0 models. The USD 30 rule was read for 2.x only. Confirmed on 2026-11-24: a 1.0 model must be activated first.
2. Whether a given account gets the free quota (S16 is a marketing page).
3. The "Model service billing" page. Its old URL redirects to the pricing page.
4. Whether 429 responses carry a `Retry-After` header.
5. What the storage host returns for an expired video URL, and whether a new get-task call returns a fresh URL.
6. Whether callbacks are signed. The webhook-endpoint pages were not read.
7. Typical generation time. The docs give no number. Their samples poll every 10 s or 30 s. One run took 12 s (2026-11-24).
8. The error body is observed (P1), not documented on S6.
9. Doc inconsistencies: S7 lists 97,000 tokens for 1.0 pro 480p 16:9 10 s, the formula gives 97,200. S1 gives closed image ranges `[0.4, 2.5]` and `[300, 6000]`, S9 gives open ones. S7 mentions "Seedance 1.5 Pro" in the draft rule, but no such model is in the model list or price table.

## Observed on the live API (2026-11-24)

- `GET` of a made-up task ID returned HTTP 404 with code `ResourceNotFound` and a message that holds the request ID. Section 9 lists `NotFound.*` for a missing resource, so the code differs from the docs. The tool maps it to `TaskNotFoundError` by the HTTP status.
- The key was accepted: the answer was 404, not 401.
- A create for `seedance-1-0-pro-fast-251015` before activation returned HTTP 404 with code `ModelNotOpen` and a message that the account (number masked) has not activated the model. The request ID is masked too. After activation in the console, the same request was accepted.
- The request body was accepted as built: `model`, `content` (one text item), `resolution`, `ratio`, `duration`, no `service_tier`.
- Fields of the succeeded task object: `id`, `model`, `status`, `content.video_url`, `usage.completion_tokens`, `usage.total_tokens`, `created_at`, `updated_at`, `seed`, `resolution`, `ratio`, `duration`, `framespersecond`, `service_tier`, `execution_expires_after`, `draft`, `priority`, `output_format` (`mp4`). Against the S2 example, `output_format` is extra and `generate_audio` is absent.
- `service_tier` was `default` and `completion_tokens` equalled `total_tokens`, as documented.
- 2 s at 480p 16:9: the formula gives 19,440 tokens, the API reported 19,845. The file has 49 frames (2.04 s) at 864×480. 49 × 864 × 480 ÷ 1024 = 19,845, so the count equals the real frames. One run only.
- `updated_at` minus `created_at` was 12 s. One run only: section 12 item 7 stays open.
- The time inside the task ID is 8 hours ahead of `created_at` (UTC).
- The storage host served the file without the key.
