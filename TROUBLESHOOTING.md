# Troubleshooting

"Likely side" says where to look first: the customer, our integration (this
tool), or BytePlus.

| Symptom | Likely side | How to check | What to send when escalating |
|---------|-------------|--------------|------------------------------|
| `ARK_API_KEY` is not set | Customer | Check the variable name in `.env`: it must be `ARK_API_KEY`. Run with `uv run --env-file .env` | Nothing. Fix locally |
| `AuthenticationError`, HTTP 401 | Customer | Is the key active, from `ap-southeast-1`, with no extra characters? Does it limit IP addresses? | Request ID, UTC time |
| `AccountOverdueError`, `InvalidAccountStatus`, `OperationDenied.ServiceOverdue` | Customer | Balance and account status in the console | Request ID, UTC time, code |
| `ModelNotOpen`, `AccessDenied`, `InvalidEndpointOrModel.*` | Customer | Is the model active in `ap-southeast-1`? Observed 2026-11-24: 404 `ModelNotOpen` before activation, create accepted after. Does the key allow it? For 2.x: the USD 30 rule | Request ID, model ID, code and message |
| "The request is not valid" with no request ID | Customer | Read the listed problems. Nothing was sent | Nothing. Fix locally |
| `InvalidParameter*`, `MissingParameter*` from the API | Our integration | Our check passed but the API refused. Compare `models.toml` with the live docs | Request ID, model ID, code and message, journal lines |
| `InvalidImageURL.*` | Customer | Open the URL in a private window. Check format, size and dimensions | Request ID, code and message |
| `...SensitiveContentDetected...` | Customer | Read the prompt and look at the image. 2.x models reject real human faces | Request ID, model ID, code |
| HTTP 429 rate code, `ServerOverloaded` | Customer or BytePlus | Compare the number of requests with the limits in `docs/API_NOTES.md`, section 8 | Request ID, UTC time, model ID, code |
| `SetLimitExceeded`, `QuotaExceeded`, `InflightBatchsizeExceeded` | Customer | The cumulative usage limit of the model (S15) and the quota. `SetLimitExceeded` means the limit is reached | Request ID, model ID, code |
| HTTP 5xx on a read | BytePlus | Run `seedance status` again later | Request ID, task ID, UTC time |
| "Could not connect. Nothing was sent" | Customer | Network, proxy, firewall | Only if other networks fail too: UTC time |
| "result is not known" after create | Our integration and BytePlus | List your tasks (below) before any new create | UTC time, model ID, request ID if shown, journal lines |
| "An earlier create has no known outcome" | Customer | List your tasks (below). Then answer the question or use `--resolved` | Journal lines |
| "still running" after the wait limit | BytePlus | Run `seedance wait` again. `flex` can take hours | Task ID, model ID, UTC time |
| Task `failed` | Depends on the code | `seedance status TASK_ID`. `InvalidParameter.TaskType*` on 2.5 points to the request | Task ID, model ID, code and message |
| Task `expired` | BytePlus | The default limit is 48 hours | Task ID, model ID, UTC time |
| Task not found | Customer | Is the ID right and under 7 days old? Same account and region? | Task ID, request ID |
| "The storage host refused the link" | Customer (assumed) | We assume that 403 and 404 mean expired. The docs do not say. Over 24 hours old, or over 100 downloads on 2.5? Run `download` again | Task ID, UTC time |
| Cost differs from the estimate | Our integration | A small excess can be one extra frame (observed once, +2.1%). Compare the token count and `read_on` in `pricing.toml` with the live price page. The tool cannot show the billed amount. In the console, Billing overview shows the account balance and Usage statistics shows token usage (S11). Adaptive ratio: the range is an indication, not a bound | Task ID, token count, billed amount |
| "price unknown" | Our integration | The model or tier is missing from `pricing.toml` | Model ID, resolution, tier |
| Journal line is damaged | Our integration | List your tasks (below), then remove the named line of `~/.seedance/journal.jsonl` (or the file in `SEEDANCE_HOME`) | Journal lines |

## List your tasks

Use this after a create with an unclear result (List tasks API, S3). Set
`ARK_API_KEY` in the shell first (`export`): `uv run --env-file` does not set it
there.

Online tasks:

```bash
curl -H "Authorization: Bearer $ARK_API_KEY" "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks?page_num=1&filter.service_tier=default"
```

Offline (`flex`) tasks:

```bash
curl -H "Authorization: Bearer $ARK_API_KEY" "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks?page_num=1&filter.service_tier=flex"
```

Each tier has its own list. The API shows online tasks only, unless you ask for
`flex`. The tool names the tier of the open attempt. If you are not sure, check
both. A page holds 20 tasks by default. More pages may exist: raise `page_num`
until a page is empty.

If your console shows a task list, you can check there too.

**Never send the API key, the `.env` file or the video link.** Journal lines hold
prompts. Remove them if they are private.
