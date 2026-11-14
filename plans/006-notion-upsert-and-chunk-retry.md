# Plan 006: Make `archive_to_notion` idempotent (upsert), retry HTTP 429, and fail loudly on `>90` block append errors

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md` — unless a reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `git -C /Users/jialiwu/.gemini/bots/shared diff --stat 7c2707a..HEAD -- notion_archive.py tests/test_notion_archive.py`
> Confirm Plans `002`–`005` are complete (or at minimum Plan `002` is `DONE`) and check `notion_archive.py` lines `602-808` before editing.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM
- **Depends on**: `plans/002-notion-archive-unit-test-baseline.md`, `plans/003-notion-block-parser-fixes.md`, `plans/004-notion-summary-decision-signals.md`, `plans/005-report-type-and-date-alignment.md`
- **Category**: bug
- **Planned at**: commit `7c2707a` (`bot-ops` / `shared`), `2026-11-15`

## Why this matters

Three reliability bugs currently corrupt or duplicate live Notion database entries in `/Users/jialiwu/.gemini/bots/shared/notion_archive.py`:
1. **No upsert / duplicate creation**: `archive_to_notion` unconditionally calls `POST https://api.notion.com/v1/pages` (`L766-768`). Re-running a bot (`FORCE_RUN=1`), retrying after an error, or re-syncing after fixing formatting creates duplicate cards with the same `(日期, 信源, 类型)`.
2. **HTTP 429 not retried & curl fallback skips bodyless methods**: The retry loop (`L764-777`) executes `if resp.status_code < 500: break` (`L773`), failing immediately on Notion `429 Too Many Requests` without waiting `Retry-After`. Meanwhile `_CurlResp` (`L682-689`) lacks `.headers`, and `_curl_request` (`L690-738`) + `_req_with_fallback` (`L746, 757`) require `body_dict is not None`, breaking `GET` and `DELETE` calls under curl TLS fallback.
3. **Silent partial-page truncation (`>90` blocks)**: When `len(blocks) > 90`, chunks after index 90 are appended via `PATCH /v1/blocks/{page_id}/children` (`L790-802`) **without retries**. If an append fails (`status_code >= 400`), the code prints `[WARN]` to `stderr` (`L801`) and **still returns `(True, page_url)`** (`L804`), falsely reporting full archive success on truncated pages.

## Current state

Excerpts from `/Users/jialiwu/.gemini/bots/shared/notion_archive.py` (`7c2707a`):

- Lines `682-760` (`_CurlResp`, `_curl_request`, `_req_with_fallback`):
  ```python
        class _CurlResp:
            def __init__(self, status_code: int, text: str):
                self.status_code = status_code
                self.text = text

            def json(self):
                return json.loads(self.text)

        def _curl_request(method: str, url: str, body_dict: dict, timeout: int = 35):
            ...
                    cmd += [
                        "-X", method, url,
                        "-H", f"Notion-Version: {NOTION_VERSION}",
                        "-H", "Content-Type: application/json",
                        "-K", "-",
                        "--data-binary", f"@{tmp_path}",
                        "-w", "\n%{http_code}",
                    ]
            ...
        def _req_with_fallback(method: str, url: str, **kwargs):
            nonlocal session, prefer_curl
            body_dict = kwargs.get("json")
            if prefer_curl and body_dict is not None:
                return _curl_request(method, url, body_dict, timeout=int(kwargs.get("timeout", 30)))
            ...
                except requests.RequestException:
                    if body_dict is not None and os.path.exists("/usr/bin/curl"):
                        prefer_curl = True
                        return _curl_request(method, url, body_dict, timeout=int(kwargs.get("timeout", 30)))
                    raise
  ```
- Lines `762-805` (create + chunked append):
  ```python
        for attempt in range(3):
            try:
                resp = _req_with_fallback(
                    "POST",
                    "https://api.notion.com/v1/pages",
                    json=payload,
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code < 500:
                    break
            except Exception as e:
                last_err = e
                time.sleep(1)
        ...
        # 追加剩余 blocks
        if len(blocks) > 90 and page_id:
            for j in range(90, len(blocks), 90):
                chunk = blocks[j : j + 90]
                append_resp = _req_with_fallback(
                    "PATCH",
                    f"https://api.notion.com/v1/blocks/{page_id}/children",
                    json={"children": chunk},
                    headers=headers,
                    timeout=30,
                )
                if append_resp.status_code >= 400:
                    print(f"  [WARN] 追加 blocks 失败: {append_resp.text}", file=sys.stderr)
                time.sleep(0.3)

        return True, page_url
  ```
- Notion REST API version in file (`L34`): `NOTION_VERSION = "2022-06-28"` (database query endpoint is `POST https://api.notion.com/v1/databases/{database_id}/query`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Syntax check | `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/notion_archive.py` | exit 0 |
| Unit tests | `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` | exit 0, all pass offline |
| Check git status | `git -C /Users/jialiwu/.gemini/bots/shared status --short` | shows only `notion_archive.py` & `tests/` |

## Scope

**In scope**:
- `/Users/jialiwu/.gemini/bots/shared/notion_archive.py` (`archive_to_notion`, `_CurlResp`, `_curl_request`, `_req_with_fallback`, HTTP retry & upsert helpers)
- `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`

**Out of scope**:
- Do NOT change `NOTION_VERSION` from `"2022-06-28"` (`L34`) without checking all API payloads.
- Do NOT make live mutating writes to production Notion pages during unit tests.
- Do NOT alter `extract_summary` or `convert_to_blocks` rules (`Plans 003`–`004`).

## Git workflow

- Working repo: `/Users/jialiwu/.gemini/bots/shared`
- Commit style: `fix(notion_archive): 支持同日同信源幂等覆盖更新、429 重试与超90块失败报错`
- Do NOT push without operator confirmation.

## Steps

### Step 1: Make curl fallback support `body_dict=None` and capture HTTP headers (for `Retry-After`)

In `/Users/jialiwu/.gemini/bots/shared/notion_archive.py`:
1. Update `_CurlResp` (`L682-689`) to accept `headers: dict[str, str] | None = None` (storing lowercase keys `{k.lower(): v for k, v in (headers or {}).items()}` or a tiny case-insensitive dict/lookup helper) so `resp.headers.get("Retry-After")` works uniformly with `requests.Response`.
2. Update `_curl_request(method: str, url: str, body_dict: dict | None = None, timeout: int = 35)` (`L690-738`):
   - Dump response headers to a temporary file via `-D <hdr_tmp_path>` (unlinking both temp files in `finally:`), parse final HTTP response header block into `headers_dict` (handling HTTP proxy `CONNECT ... 200 Connection established` header blocks before the actual `HTTP/1.1 429` or `HTTP/2 200` status block by resetting `headers_dict` whenever an `HTTP/` status line appears!).
   - Only create JSON payload temp file and pass `-H "Content-Type: application/json"` + `--data-binary @{tmp_path}` when `body_dict is not None`.
3. Update `_req_with_fallback(method: str, url: str, **kwargs)` (`L743-760`):
   - Remove `and body_dict is not None` from both `if prefer_curl:` and `if os.path.exists("/usr/bin/curl"):` so `GET` and `DELETE` requests seamlessly use curl fallback if LibreSSL raises TLS EOF.

**Verify**: Run `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/notion_archive.py` -> exit 0.

### Step 2: Add centralized retry helper handling `429`, `5xx`, and network exceptions

Inside `archive_to_notion` (right after `_req_with_fallback`, around `L761`), add `_request_with_retry(method: str, url: str, *, json_body=None, timeout: int = 30, max_attempts: int = 4)`:
1. Loop `attempt in range(max_attempts)`:
   - Call `_req_with_fallback(method, url, headers=headers, timeout=timeout, **({"json": json_body} if json_body is not None else {}))`.
   - If `resp.status_code == 429`: parse `Retry-After` from `getattr(resp, "headers", {})` (case-insensitive check for `"Retry-After"` / `"retry-after"`), compute `delay = min(max(float(ra), 1.0), 30.0)` with fallback `min(2 ** attempt, 16)` if non-numeric/absent; sleep and retry if `attempt + 1 < max_attempts`.
   - If `resp.status_code >= 500`: sleep `min(2 ** attempt, 8)` and retry if `attempt + 1 < max_attempts`.
   - Otherwise return `resp`.
   - Catch `Exception as e`: store `last_err = e`, sleep `min(2 ** attempt, 8)`, retry if `attempt + 1 < max_attempts`, then return `(None, last_err)`.

**Verify**: Confirm no remaining unretried `_req_with_fallback` calls bypass `_request_with_retry`.

### Step 3: Implement idempotent upsert (`query -> create OR patch + safe block replacement`) and strict chunk validation

Replace the unconditional `POST /v1/pages` (`L762-804`) with upsert flow (all requests throttled `0.35s` between write calls and using `_request_with_retry`):
1. **Query existing active matches**:
   - `POST https://api.notion.com/v1/databases/{database_id}/query` with:
     ```python
     query_body = {
         "filter": {
             "and": [
                 {"property": "日期", "date": {"equals": date_str}},
                 {"property": "信源", "select": {"equals": source}},
                 {"property": "类型", "select": {"equals": report_type}},
             ]
         },
         "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
     }
     ```
   - Notice: Notion database `/query` already excludes archived/trashed pages by default (`Notion API 2022-06-28`). If the query itself fails (`None` or `status_code >= 400`), return `(False, ...)` immediately rather than creating blind duplicates.
2. **Helper `_append_chunks(page_id: str, chunk_blocks: list[dict]) -> tuple[bool, list[str], str]`**:
   - Iterates `range(0, len(chunk_blocks), 90)`.
   - Sends `PATCH https://api.notion.com/v1/blocks/{page_id}/children` with `{"children": chunk}` via `_request_with_retry`.
   - Collects returned `id`s from `resp.json().get("results", [])` into `created_ids`.
   - If ANY chunk fails (`resp is None` or `resp.status_code >= 400`), returns `(False, created_ids, error_msg)` — **never silently continues and never returns `(True, ...)`**.
   - Sleeps `0.35` between chunks to respect Notion's ~3 req/s rate limit.
3. **Branch A — Zero matching pages (`len(matches) == 0`)**:
   - Send `POST https://api.notion.com/v1/pages` with `payload` (`first_chunk = blocks[:90]`).
   - Extract `page_id`, `page_url`.
   - If `len(blocks) > 90`: call `_append_chunks(page_id, blocks[90:])`; if it returns `ok=False`, return `(False, f"Notion 后续区块追加失败 ({page_url}): {err}")`.
   - Return `(True, page_url)`.
4. **Branch B — One or more matching pages (`len(matches) >= 1`)**:
   - Pick `target = matches[0]`, `page_id = target["id"]`, `page_url = target.get("url") or f"https://notion.so/{page_id.replace('-', '')}"`.
   - Fetch all existing top-level child block IDs via paginated `GET https://api.notion.com/v1/blocks/{page_id}/children?page_size=100` (`start_cursor` loop while `has_more` & `next_cursor`). If listing fails (`None` or `>= 400`), return `(False, ...)`.
   - Update `icon` and `properties` on `page_id` via `PATCH https://api.notion.com/v1/pages/{page_id}` with `{"icon": payload["icon"], "properties": payload["properties"]}`. If that fails, return `(False, ...)`.
   - **Append-before-delete safety**: Call `_append_chunks(page_id, blocks)` to append ALL new blocks after `old_ids`:
     - If `_append_chunks` fails midway, attempt best-effort rollback by deleting only `created_ids` that were partially appended (leaving `old_ids` untouched so existing Notion content is NOT lost!), and return `(False, f"Notion 页面更新追加区块失败 ({page_url}): {err}")`.
   - Once ALL new chunks succeed, delete each `old_id` in `old_ids` via `DELETE https://api.notion.com/v1/blocks/{old_id}` (sleeping `0.35` between deletes; treat `status_code == 404` or `"object_not_found"` / `"already archived"` harmlessly; fail `(False, ...)` if an un-ignorable HTTP >= 400 persists after retries).
   - Finally, archive any duplicate rows `dup in matches[1:]` via `PATCH https://api.notion.com/v1/pages/{dup['id']}` with `{"archived": True}` (log warning if archiving a stray duplicate fails, or fail cleanly).
   - Return `(True, page_url)`.

**Verify**: Run `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/notion_archive.py` -> exit 0.

### Step 4: Add comprehensive offline HTTP unit tests for upsert, 429 retry, and chunk failure

In `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`, update `TestArchiveToNotionHttp` (patching `time.sleep` to no-op for sub-second speed!):
1. `test_upsert_creates_new_page_when_query_empty`: query returns `{"results": []}` -> `POST /v1/pages` runs once and returns `(True, page_url)`.
2. `test_upsert_updates_in_place_preserving_page_id_and_archiving_dups`: query returns 2 matching pages (`page-new`, `page-old-dup`) -> verifies `PATCH /v1/pages/page-new`, `GET /v1/blocks/page-new/children`, `PATCH /v1/blocks/page-new/children`, `DELETE /v1/blocks/{old_id}` in safe order (appends BEFORE deletes), `PATCH /v1/pages/page-old-dup {"archived": True}`, and NEVER calls `POST /v1/pages`!
3. `test_retries_http_429_respecting_retry_after`: `POST /v1/pages` returns `429` with `headers={"Retry-After": "2"}` then `200` -> verifies `time.sleep` was called with `>= 2.0` and overall result is `(True, page_url)`.
4. `test_append_chunk_failure_returns_false_and_preserves_old_blocks_on_update`: with `>90` blocks on update path where chunk 2 returns `400` permanently -> verifies returns `(False, ...)`, rolls back `created_ids` from chunk 1, and NEVER deletes `old_ids`! Also test create path with `120` blocks where chunk 2 returns `500` x4 -> returns `(False, ...)`.
5. `test_curl_fallback_parses_headers_for_bodyless_get_and_delete`: mock `subprocess.run` simulating `/usr/bin/curl -D <hdr_file>` proxy CONNECT header + `HTTP/2 429` with `Retry-After: 1` followed by `200`, verifying `_CurlResp.headers` and `body_dict=None` execution.

**Verify**: `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` -> exit 0, all pass in `<2s`.

## Test plan

- File: `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`
- Run: `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v`
- Expectation: Exit 0, zero failures, all HTTP retry/upsert edge cases pass offline with `time.sleep` mocked.

## Done criteria

- [ ] `archive_to_notion` queries active pages by `(日期, 信源, 类型)` and updates in-place instead of creating duplicates.
- [ ] Extra duplicate pages (if >1 matched) are automatically archived (`{"archived": True}`).
- [ ] HTTP `429` honors `Retry-After` and `5xx`/network faults retry with backoff in both `requests` and `/usr/bin/curl` fallback (`body_dict=None` supported).
- [ ] Any chunk failure beyond block 90 retries and returns `(False, ...)` without falsely returning `(True, page_url)` or deleting existing blocks on update failure.
- [ ] `py_compile` and full `unittest` suite pass cleanly offline.

## STOP conditions

Stop and report back (do not improvise) if:
- Any test from Plan `002` `TestArchiveToNotionHttp` was asserting old unconditional `POST` mock expectations without supplying a `databases/.../query` response — update the Plan `002` HTTP mock fixture cleanly in `test_notion_archive.py` once Plans `002`–`005` are complete, or stop if live Notion API rejects `last_edited_time` sort in `/v1/databases/{id}/query`.
- Running `/usr/bin/curl` header parsing fails Proxy `CONNECT` split edge cases in unit tests.

## Maintenance notes

- Notion API enforces ~3 requests/second average rate limit per integration token; keep `0.35s` inter-request sleep between block delete/append batches so long `>150`-block updates complete cleanly without hitting `429`.
- Because `canonical_page` updates via `PATCH /v1/pages/{id}` rather than archive+recreate, page URLs shared externally and Notion page-level `Comments` remain intact across updates!
- Note for Notion property name matching: `filter` relies on exact property names `日期` (`date`), `信源` (`select`), and `类型` (`select`) in database `e072f4c04bbf467793879e7dce4e4373`. If a property is ever renamed in Notion UI, update both `payload["properties"]` (`L650-655`) and `query_body["filter"]`.
