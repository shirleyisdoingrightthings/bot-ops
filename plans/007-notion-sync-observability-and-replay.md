# Plan 007: Record `notion_ok`/`notion_url` in `run.jsonl`, surface failures in `health_check_base.sh`, and add replay CLI

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md` — unless a reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: Check every target repository's HEAD before editing:
> - `git -C /Users/jialiwu/.gemini/bots/shared diff --stat 7c2707a..HEAD`
> - `git -C /Users/jialiwu/.gemini/bots/github-hn-bot diff --stat 36c65e6..HEAD`
> - `git -C "/Users/jialiwu/.gemini/bots/AI Daily News Bot" diff --stat 8eb5260..HEAD`
> - `git -C /Users/jialiwu/.gemini/bots/cn-hk-stock-bot diff --stat 38b61ec..HEAD`
> - `git -C "/Users/jialiwu/.gemini/bots/us stock bot" diff --stat a36662b..HEAD`
> - `git -C /Users/jialiwu/.gemini/bots/x-hotspot-bot diff --stat ed136f7..HEAD`
> - `git -C /Users/jialiwu/.gemini/bots/ai-builder-bot diff --stat 5f73fab..HEAD`
> Confirm Plan `006` (`upsert` + chunk error propagation) is `DONE` before introducing `notion_reconcile.py` replay.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: `plans/002-notion-archive-unit-test-baseline.md`, `plans/006-notion-upsert-and-chunk-retry.md`
- **Category**: reliability (observability / replay)
- **Planned at**: `shared` `7c2707a`, `github-hn-bot` `36c65e6`, `AI Daily News Bot` `8eb5260`, `cn-hk-stock-bot` `38b61ec`, `us stock bot` `a36662b`, `x-hotspot-bot` `ed136f7`, `ai-builder-bot` `5f73fab`, `2026-11-15`

## Why this matters

Currently, all 5 send entrypoints catch/log Notion sync failures only to ephemeral `stderr` (`[WARN] Notion 归档未完成`), while writing `write_log("OK", ...)` to `run.log` and `run.jsonl` with **zero** Notion status fields:
- `bots/shared/health_check_base.sh` only checks `OK`/`FAIL`/`WARN` + content metrics (`rss_kept`, `spx`, `tweets`, etc.) and declares `[health_check] OK (streak=N)` even if Notion archiving silently fails or returns HTTP 401/403/500 for weeks.
- Additionally, only `github-hn-bot` retains dated local draft archives in `logs/archive/{date}.txt` (`github_hn_report.py:279`). All other 5 bots overwrite `logs/report_draft.txt` (or `report_cn.txt`/`report_hk.txt`, `report_market.txt`/`report_news.txt`) on the next day's run, making post-outage Notion backfill impossible once overwritten.

## Current state

1. All 5 Notion archive call sites currently ignore `(ok, res)` after printing to `stderr`:
   - `/Users/jialiwu/.gemini/bots/shared/bot_utils.py:1042-1072` (`send_x_linked_report`, covers `🐦 X 热点播报` & `🛠️ AI Builder`, `write_log` at `L1066-1071`)
   - `/Users/jialiwu/.gemini/bots/AI Daily News Bot/daily_report.py:503-524` (`write_log` at `L519-524`)
   - `/Users/jialiwu/.gemini/bots/github-hn-bot/github_hn_report.py:278-308` (already saves `ARCHIVE_DIR / f"{today_iso}.txt"`, `write_log` at `L304-308`)
   - `/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/cn_hk_report.py:776-823` (`write_log` at `L819-823`)
   - `/Users/jialiwu/.gemini/bots/us stock bot/stock_report.py:1151-1198` (`write_log` at `L1193-1198`)
2. `/Users/jialiwu/.gemini/bots/shared/health_check_base.sh`:
   - `L66-78`: `jsonl_field` reads today's last JSONL line via `/usr/bin/python3` (prints Python `"True"`/`"False"` verbatim when JSON holds booleans!).
   - `L185-188`: Section 4 calls `content_check` if defined, then Section 6 (`L222-242`) increments `.ok_streak` and logs `OK`.
3. `bots/*/logs/` holds transient `report_draft.txt` / `report_cn.txt` / `report_hk.txt` / `report_market.txt` / `report_news.txt`. Only `github-hn-bot` has `logs/archive/`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Bash syntax check | `/bin/bash -n /Users/jialiwu/.gemini/bots/shared/health_check_base.sh` | exit 0 |
| Python syntax check | `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/notion_reconcile.py /Users/jialiwu/.gemini/bots/shared/bot_utils.py ...` | exit 0 |
| Offline unit tests | `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` | exit 0, all pass |
| Dry-run reconcile | `/usr/bin/python3 /Users/jialiwu/.gemini/bots/shared/notion_reconcile.py --dry-run` | exit 0, prints archive mapping without writing Notion |

## Scope

**In scope**:
- `/Users/jialiwu/.gemini/bots/shared/bot_utils.py` (log Notion result + dated archive for `x-hotspot-bot` / `ai-builder-bot` OR shared helper `sync_notion_and_archive(...)`)
- `/Users/jialiwu/.gemini/bots/shared/health_check_base.sh`
- `/Users/jialiwu/.gemini/bots/shared/notion_reconcile.py` (new CLI)
- `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_reconcile.py`
- `/Users/jialiwu/.gemini/bots/github-hn-bot/github_hn_report.py`
- `/Users/jialiwu/.gemini/bots/AI Daily News Bot/daily_report.py`
- `/Users/jialiwu/.gemini/bots/cn-hk-stock-bot/cn_hk_report.py`
- `/Users/jialiwu/.gemini/bots/us stock bot/stock_report.py`

**Out of scope**:
- Do NOT make `notion_ok=False` trigger a full `FAIL` / Feishu re-send catchup (Feishu delivery already succeeded; failed Notion sync triggers health log `WARN` + replay via `notion_reconcile.py`!).
- Do NOT alter individual `*/health_check.sh` wrapper contracts unless passing explicit variables is needed — put the shared Notion check directly in `shared/health_check_base.sh` so all 6 bots inherit it automatically!

## Git workflow

This task touches **5 git repositories** (`shared`, `github-hn-bot`, `AI Daily News Bot`, `cn-hk-stock-bot`, `us stock bot`; note `x-hotspot-bot` and `ai-builder-bot` call `bot_utils.send_x_linked_report` directly and do not need script edits unless you add a README note):
1. `/Users/jialiwu/.gemini/bots/shared`: `feat(observability): 记录 notion_ok/notion_url 指标、体检告警及归档补同步 CLI`
2. `/Users/jialiwu/.gemini/bots/github-hn-bot`: `feat(notion): 记录 notion_ok/notion_url 到 run.jsonl`
3. `/Users/jialiwu/.gemini/bots/AI Daily News Bot`: `feat(notion): 落盘每日历史文稿归档并记录 Notion 同步状态`
4. `/Users/jialiwu/.gemini/bots/cn-hk-stock-bot`: `feat(notion): 按场次落盘归档并记录 Notion 同步状态`
5. `/Users/jialiwu/.gemini/bots/us stock bot`: `feat(notion): 落盘合并文稿归档并记录 Notion 同步状态`

## Steps

### Step 1: Extract a shared `archive_and_sync_notion(...)` helper in `shared/bot_utils.py` and adopt across all 5 callers

To eliminate copy-pasted `try ... archive_to_notion(...) except ...` boilerplate across 5 files and guarantee uniform behavior:
1. Add `archive_and_sync_notion(...) -> dict` in `/Users/jialiwu/.gemini/bots/shared/bot_utils.py`:
   - Parameters: `report_text: str, source: str, *, date_str: str, archive_dir: Path | None = None, archive_filename: str | None = None, report_type: str = "日报", title_override: str | None = None`.
   - If `archive_dir` is provided: `archive_dir.mkdir(parents=True, exist_ok=True)` and write `(archive_dir / (archive_filename or f"{date_str}.txt")).write_text(report_text, encoding="utf-8")`.
   - Call `notion_archive.archive_to_notion(report_text, source, date_str=date_str, report_type=report_type, title_override=title_override)` inside `try/except`:
     - Print `  ✓ 已同步归档至 Notion: {res}` on success, or `  [WARN] Notion 归档未完成/调用失败: ...` on failure (to `sys.stderr`).
     - Return `{"notion_ok": bool(ok), "notion_url": res if ok else "", **({} if ok else {"notion_err": str(res)[:200]})}`.
2. Update all 5 callers to use `archive_and_sync_notion` and merge its returned dict into `write_log("OK", ..., metrics={..., **notion_meta})` (also append `" | Notion ✓"` or `" | Notion ⚠️"` to the `OK` log message):
   - `shared/bot_utils.py:send_x_linked_report`: `archive_dir = draft_path.parent / "archive"`, `archive_filename = f"{doc_date}.txt"`, `source = "🐦 X 热点播报"` or `"🛠️ AI Builder"`.
   - `AI Daily News Bot/daily_report.py`: `archive_dir = DRAFT_FILE.parent / "archive"`, `archive_filename = f"{report_date}.txt"`.
   - `github-hn-bot/github_hn_report.py`: pass `archive_dir = ARCHIVE_DIR`, `archive_filename = f"{doc_date}.txt"` (replacing lines `278-291`).
   - `cn-hk-stock-bot/cn_hk_report.py`: pass `archive_dir = DRAFT_CN.parent / "archive"`, `archive_filename = f"{doc_date}_{sess_mode}.txt"`, `report_type = rtype`, `title_override = f"[A股与港股] {doc_date} {rtype}"` (notice `{doc_date}_premarket.txt` vs `{doc_date}_close.txt` avoids overwriting same-day morning & afternoon drafts!).
   - `us stock bot/stock_report.py`: pass `archive_dir = DRAFT_MARKET.parent / "archive"`, `archive_filename = f"{sess_date}.txt"`.

**Verify**: Run `py_compile` across `shared/bot_utils.py` and the 4 bot scripts -> exit 0.

### Step 2: Check `notion_ok` in `shared/health_check_base.sh`

In `/Users/jialiwu/.gemini/bots/shared/health_check_base.sh` (right around Section 4 `L185-189`, before Section 6 streak increment):
1. Add a shared check inspecting all JSONL records matching today (`$TODAY`) where `"status" == "OK"` and `"notion_ok"` key is explicitly present and `False`:
   ```bash
   # ── 4.5 Notion 同步状态核查（只在存在 notion_ok=false 时告警，不触发补跑）──
   if [ -f "$JSONL" ]; then
       NOTION_ERR=$(grep "$TODAY" "$JSONL" | /usr/bin/python3 -c "
   import sys, json
   errs = []
   for line in sys.stdin:
       line = line.strip()
       if not line: continue
       try:
           d = json.loads(line)
           if d.get('status') == 'OK' and ('notion_ok' in d) and d.get('notion_ok') is False:
               errs.append(str(d.get('notion_err') or 'unknown')[:120])
       except Exception:
           pass
   if errs:
       print(errs[-1])
   " 2>/dev/null)
       if [ -n "$NOTION_ERR" ]; then
           notify WARN "Notion 归档失败（Feishu 已推送）：$NOTION_ERR — 请运行 python3 shared/notion_reconcile.py 补同步"
           echo "[health_check] WARN: notion_ok=False ($NOTION_ERR)"
       fi
   fi
   ```
   (Notice: inspecting ALL `status == "OK"` lines for `$TODAY` ensures `cn-hk-stock-bot` still surfaces a morning `premarket` Notion failure even after `close` runs later in the day, and ignoring records lacking `"notion_ok"` prevents false positives on legacy log entries before rollout!)

**Verify**: Run `/bin/bash -n /Users/jialiwu/.gemini/bots/shared/health_check_base.sh` -> exit 0.

### Step 3: Create `/Users/jialiwu/.gemini/bots/shared/notion_reconcile.py` replay & audit CLI

Create `/Users/jialiwu/.gemini/bots/shared/notion_reconcile.py` using `bot_utils.extract_report_date` and `notion_archive.archive_to_notion` (depends on Plan `006` idempotency):
1. Define a clean bot mapping table relative to `Path(__file__).resolve().parent.parent`:
   - `github-hn-bot` -> source `"🐙 GitHub & HN"`
   - `us stock bot` -> source `"🗽 美股与加密"`
   - `cn-hk-stock-bot` -> source `"📈 A股与港股"` (expects `{date}_premarket.txt` or `{date}_close.txt`, mapping suffix -> `report_type` `"开盘前瞻"`/`"收盘复盘"` and `title_override=f"[A股与港股] {date_str} {rtype}"`)
   - `AI Daily News Bot` -> source `"🤖 AI 产业日报"`
   - `x-hotspot-bot` -> source `"🐦 X 热点播报"`
   - `ai-builder-bot` -> source `"🛠️ AI Builder"`
2. Support flags:
   - `--date YYYY-MM-DD` (default: check `--since-days`, e.g. `1` or today)
   - `--since-days N` (scan last `N` days of `logs/run.jsonl` & `logs/archive/`)
   - `--bot <dir_name>` (optional filter to single bot)
   - `--only-failed` (default when scanning JSONL without `--force`: replay only `(date, source, session)` where `notion_ok is False`, or force-upsert all found archives when `--force` is set)
   - `--dry-run` (print planned `(source, date_str, report_type, title_override, archive_path)` without calling Notion API)
3. Report-type resolution for `github-hn-bot/logs/archive/{date}.txt`: check matching date in `logs/run.jsonl` (`metrics.since == "weekly"`), or fallback `"周趋势榜"`/`"每周"`/`Weekly` markers in text or Sunday date -> `"周盘点"` else `"日报"`.
4. Print summary table at exit and exit `1` if any attempted replay returned `ok=False`.

**Verify**: Run `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/notion_reconcile.py` and `/usr/bin/python3 /Users/jialiwu/.gemini/bots/shared/notion_reconcile.py --help` -> exit 0.

### Step 4: Add offline tests for `archive_and_sync_notion`, `notion_reconcile.py`, and `health_check_base.sh`

Create `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_reconcile.py`:
1. Test `bot_utils.archive_and_sync_notion` using `tempfile.TemporaryDirectory`: verifies file written to `archive_dir/{date}.txt` and returns `{"notion_ok": True, "notion_url": ...}` on mocked `(True, url)` or `{"notion_ok": False, "notion_url": "", "notion_err": ...}` on mocked `(False, err)` or raised exception (without crashing).
2. Test `notion_reconcile`:
   - Parses `cn-hk-stock-bot` `{date}_premarket.txt` & `{date}_close.txt` into exact `report_type` and `title_override`.
   - Identifies `notion_ok: false` entries in mocked `run.jsonl` and locates corresponding `logs/archive/` files under `--only-failed`.
   - Respects `--dry-run` (zero calls to mocked `archive_to_notion`).
3. Optional bash check test invoking `/bin/bash /Users/jialiwu/.gemini/bots/shared/health_check_base.sh` against a temp bot dir containing a mocked `run.log` (`OK`) and `run.jsonl` (`"notion_ok": false`) -> asserts stdout contains `[health_check] WARN: notion_ok=False` and exits `0` (does NOT trigger catchup/fail!).

**Verify**: `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` -> exit 0, zero failures.

## Test plan

- Files: `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`, `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_reconcile.py`
- Commands:
  - `/bin/bash -n /Users/jialiwu/.gemini/bots/shared/health_check_base.sh`
  - `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v`
- Expectation: All offline Python and health-check verification checks pass with zero network calls and exit 0.

## Done criteria

- [ ] All 5 send paths call `bot_utils.archive_and_sync_notion`, save dated copies to `logs/archive/`, and record `notion_ok` & `notion_url` inside `run.jsonl`.
- [ ] `bots/shared/health_check_base.sh` detects `notion_ok=False` on any `$TODAY` `OK` run and emits `[health_check] WARN` without triggering Feishu re-send catchup.
- [ ] `bots/shared/notion_reconcile.py` supports `--date`, `--since-days`, `--bot`, `--only-failed`, `--force`, and `--dry-run` with clean exit codes.
- [ ] Bash syntax check and full `unittest` suite pass offline.

## STOP conditions

Stop and report back (do not improvise) if:
- Plan `006` (idempotent upsert) has NOT yet landed (replaying without Plan `006` would create duplicate Notion rows).
- Any bot directory `logs/` is symlinked or read-only.
- Existing `health_check.sh` wrapper expectations conflict with the `notion_ok=False` `WARN` line (check each wrapper's `content_check` and confirm exit `0` behavior).

## Maintenance notes

- Periodic cleanup: `logs/archive/` text files are tiny (~5–15 KB/day, <10 MB/year across all 6 bots); if retention limits are desired later, prune files older than 90 days in `notion_reconcile.py` or a monthly cron.
- Notice legacy `run.jsonl` entries created before Plan `007` omit `"notion_ok"`: `health_check_base.sh` checks `'notion_ok' in d and d.get('notion_ok') is False` specifically so legacy rows never trigger spurious warnings.
