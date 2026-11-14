# Plan 005: Fix `github_hn_report.py --since weekly` type detection and pass explicit business `date_str` from AI bots

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md` — unless a reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: Check every affected repository's HEAD before editing:
> - `git -C /Users/jialiwu/.gemini/bots/shared diff --stat 7c2707a..HEAD`
> - `git -C /Users/jialiwu/.gemini/bots/github-hn-bot diff --stat 36c65e6..HEAD`
> - `git -C "/Users/jialiwu/.gemini/bots/AI Daily News Bot" diff --stat 8eb5260..HEAD`
> - `git -C /Users/jialiwu/.gemini/bots/x-hotspot-bot diff --stat ed136f7..HEAD`
> - `git -C /Users/jialiwu/.gemini/bots/ai-builder-bot diff --stat 5f73fab..HEAD`
> Stop if any target script changed since those commits.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/002-notion-archive-unit-test-baseline.md`
- **Category**: bug
- **Planned at**: `shared` `7c2707a`, `github-hn-bot` `36c65e6`, `AI Daily News Bot` `8eb5260`, `x-hotspot-bot` `ed136f7`, `ai-builder-bot` `5f73fab`, `2026-11-15`

## Why this matters

Two subtle metadata bugs affect how Notion rows get tagged with `日期` and `类型`:
1. `github_hn_report.py` parses `--since` in `main()` (`L315`), passes `args.since` only to `run_fetch(since_override=args.since)` (`L319`), and drops it in `run_send()` (`L320`). Instead, `run_send` checks `"--since weekly" in sys.argv or (datetime.now().weekday() == 6)` (`L284`). Passing `--since=weekly`, setting `GH_TRENDING_SINCE=weekly`, or running `--mode fetch --since weekly` followed by standalone `--mode send` misfiles a weekly digest as `日报`. Conversely, running `--mode send --since daily` on Sunday cannot force `日报` because `datetime.now().weekday() == 6` always overrides it.
2. Unlike `cn_hk_report.py:782`, `stock_report.py:1154`, and `github_hn_report.py:285`, the three AI bots (`AI Daily News Bot/daily_report.py:505` and `shared/bot_utils.py:1045` for `x-hotspot-bot` and `ai-builder-bot`) invoke `archive_to_notion(report, source)` without `date_str`. In `notion_archive.py:618-619`, omitting `date_str` defaults to `datetime.now().strftime("%Y-%m-%d")`, causing late after-midnight catchup runs, historical `[AINews]` issues, or manual re-runs to store the wrong Notion `日期` and default `[...] YYYY-MM-DD` title. Moreover, `bot_utils.py:1045` calls `archive_to_notion` *before* loading `fetch_meta` (`L1054`).

## Current state

1. `/Users/jialiwu/.gemini/bots/github-hn-bot/github_hn_report.py` (`36c65e6`):
   ```python
   234:     meta = {
   235:         "log_summary": f"GitHub({since}) {len(repos)}个(含重{repeat_repos}) + HN {len(hn_items)}条(含重{repeat_hn})",
   236:         "metrics": {
   237:             "since": since,
   ...
   250: def run_send() -> int:
   ...
   278:     today_iso = datetime.now().strftime("%Y-%m-%d")
   279:     (ARCHIVE_DIR / f"{today_iso}.txt").write_text(report, encoding="utf-8")
   ...
   283:         from notion_archive import archive_to_notion
   284:         is_weekly = "--since weekly" in sys.argv or (datetime.now().weekday() == 6)
   285:         ok, res = archive_to_notion(report, "🐙 GitHub & HN", date_str=today_iso, report_type="周盘点" if is_weekly else "日报")
   ...
   318:     if args.mode == "fetch":
   319:         return run_fetch(since_override=args.since)
   320:     return run_send()
   ```
2. `/Users/jialiwu/.gemini/bots/shared/bot_utils.py` (`7c2707a`):
   ```python
   1001: def send_x_linked_report(draft_path, *, log_file, cache_file, fetch_meta, sent_urls,
   1002:                          webhook, write_log, save_pending,
   1003:                          link_label: str = "原帖") -> int:
   ...
   1042:     try:
   1043:         from notion_archive import archive_to_notion
   1044:         source_name = "🐦 X 热点播报" if link_label == "原帖" else "🛠️ AI Builder"
   1045:         ok, res = archive_to_notion(report, source_name)
   ...
   1053:     try:
   1054:         meta = json.loads(Path(fetch_meta).read_text(encoding="utf-8"))
   ```
3. `/Users/jialiwu/.gemini/bots/AI Daily News Bot/daily_report.py` (`8eb5260`):
   ```python
   432:     FETCH_META.write_text(
   433:         json.dumps(
   434:             {"log_summary": log_summary,
   435:              "kind": "daily",
   436:              "metrics": {...}},
   ...
   505:         ok, res = archive_to_notion(report, "🤖 AI 产业日报")
   ...
   514:     try:
   515:         meta = json.loads(FETCH_META.read_text(encoding="utf-8"))
   ```
4. Heading conventions already defined in prompts (`AI Daily News Bot/prompt.md:81`, `x-hotspot-bot/prompt.md:36`, `ai-builder-bot/prompt.md:43`):
   - `<b>📋 AI 产业日报 · YYYY-MM-DD</b>`
   - `<b>🔥 X 热点 · YYYY-MM-DD</b>`
   - `<b>🛠 AI Builder 日报 · YYYY-MM-DD</b>`

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Compile modified Python files | `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/bot_utils.py /Users/jialiwu/.gemini/bots/github-hn-bot/github_hn_report.py "/Users/jialiwu/.gemini/bots/AI Daily News Bot/daily_report.py" /Users/jialiwu/.gemini/bots/x-hotspot-bot/x_report.py /Users/jialiwu/.gemini/bots/ai-builder-bot/builder_report.py` | exit 0 |
| Run unit tests | `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` | exit 0, all pass |
| CLI `--help` sanity check | `/usr/bin/python3 /Users/jialiwu/.gemini/bots/github-hn-bot/github_hn_report.py --help` | exit 0 |

## Scope

**In scope**:
- `/Users/jialiwu/.gemini/bots/shared/bot_utils.py`
- `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`
- `/Users/jialiwu/.gemini/bots/github-hn-bot/github_hn_report.py`
- `/Users/jialiwu/.gemini/bots/AI Daily News Bot/daily_report.py`
- `/Users/jialiwu/.gemini/bots/x-hotspot-bot/x_report.py`
- `/Users/jialiwu/.gemini/bots/ai-builder-bot/builder_report.py`

**Out of scope**:
- Do NOT edit `notion_archive.py` parser or HTTP logic in this plan (`Plan 003`/`004`/`006`).
- Do NOT modify `cn-hk-stock-bot/cn_hk_report.py` or `us stock bot/stock_report.py` (`date_str` is already passed cleanly in both).
- Do NOT modify `prompt*.md` files or run live Feishu pushes during tests.

## Git workflow

This task touches **5 separate git repositories** (note `/Users/jialiwu/.gemini/bots` itself is NOT a git repo). Check `git status` and commit inside each modified repo individually (do NOT push without operator confirmation):
1. `/Users/jialiwu/.gemini/bots/shared`: `feat(bot_utils): 提取稿件标题业务日期并透传至 Notion 归档`
2. `/Users/jialiwu/.gemini/bots/github-hn-bot`: `fix(send): 使用 args.since 与 fetch_meta 修复周盘点类型及业务日期判定`
3. `/Users/jialiwu/.gemini/bots/AI Daily News Bot`: `fix(send): 记录 fetch_date 并向 Notion 归档显式传入业务日期`
4. `/Users/jialiwu/.gemini/bots/x-hotspot-bot`: `feat(fetch): 在 fetch_meta 记录 issue_dates 与 fetch_date`
5. `/Users/jialiwu/.gemini/bots/ai-builder-bot`: `feat(fetch): 在 fetch_meta 记录 fetch_date`

## Steps

### Step 1: Add `extract_report_date` helper and load `fetch_meta` early in `shared/bot_utils.py`

In `/Users/jialiwu/.gemini/bots/shared/bot_utils.py`:
1. Add helper `extract_report_date(report_text: str, default: str | None = None) -> str | None`:
   - Scan ONLY the first 3 non-empty stripped lines of `report_text` (strip HTML tags with `TAG_RE` or `re.sub(r"<[^>]+>", "", line)`), so body UTC timestamp spans in `AI Builder` (line 2+) are never mistaken for the publication date if a heading carries a date. Wait — restrict further: check lines matching report titles or first non-empty line, and validate matched `YYYY-MM-DD` / `YYYY年M月D日` with `datetime(y, m, d).strftime("%Y-%m-%d")` so invalid dates like `2026-13-45` are ignored! Notice in `AI Builder`, line 1 is `🛠 AI Builder 日报 · {推送日期}` (`2026-11-14`) while line 2 says `这批推文来自 2026-11-13 ~ 11-14 UTC`; scanning line 1 first returns immediately on the heading date (`2026-11-14`).
2. Update `send_x_linked_report` (`L1001-1060`):
   - Add optional keyword parameter `date_str: str | None = None`.
   - Load `meta` from `fetch_meta` (`L1053-1056`) BEFORE the Notion archive `try:` block (`L1042`).
   - Compute `doc_date = date_str or extract_report_date(report) or meta.get("fetch_date") or datetime.now().strftime("%Y-%m-%d")`.
   - Pass explicit `date_str=doc_date` into `archive_to_notion(report, source_name, date_str=doc_date)`.

**Verify**: Run `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/bot_utils.py` -> exit 0.

### Step 2: Record `fetch_date` / `issue_dates` in `x_report.py`, `builder_report.py`, and `daily_report.py`, and pass `date_str` in `daily_report.py`

1. `/Users/jialiwu/.gemini/bots/x-hotspot-bot/x_report.py`:
   - Near `L109`: add `metrics["issue_dates"] = [iss["date"] for iss in r["issues"] if iss.get("date")]`.
   - Near `L172-177`: include `"fetch_date": datetime.now().strftime("%Y-%m-%d")` at top level of `FETCH_META` JSON.
2. `/Users/jialiwu/.gemini/bots/ai-builder-bot/builder_report.py`:
   - Near `L483-486`: include `"fetch_date": datetime.now().strftime("%Y-%m-%d")` at top level of `FETCH_META` JSON.
3. `/Users/jialiwu/.gemini/bots/AI Daily News Bot/daily_report.py`:
   - Import `extract_report_date` from `bot_utils` (`L31-36`).
   - Near `L432-444`: include `"fetch_date": datetime.now().strftime("%Y-%m-%d")` in `FETCH_META` JSON (note `today` is computed at `L446` right below — move `today = datetime.now().strftime("%Y-%m-%d")` above `FETCH_META.write_text` so it is shared cleanly).
   - Move `meta = json.loads(FETCH_META.read_text(...))` (`L514-517`) BEFORE `archive_to_notion` (`L503`), compute `report_date = extract_report_date(report) or meta.get("fetch_date") or datetime.now().strftime("%Y-%m-%d")`, and pass `archive_to_notion(report, "🤖 AI 产业日报", date_str=report_date)`.

**Verify**: Run `py_compile` on all 4 modified files -> exit 0.

### Step 3: Fix `--since` & `doc_date` forwarding in `github-hn-bot/github_hn_report.py`

In `/Users/jialiwu/.gemini/bots/github-hn-bot/github_hn_report.py`:
1. Import `extract_report_date` from `bot_utils` (`L28-37`).
2. In `run_fetch` (`L234-245`), include `"date_str": now.strftime("%Y-%m-%d")` inside `meta`.
3. Change `def run_send(since_override: str | None = None) -> int:` (`L250`) and update `main()` (`L320`) to `return run_send(since_override=args.since)`.
4. Inside `run_send`, read `meta` from `FETCH_META` (`L293-296`) BEFORE archiving locally and before calling `archive_to_notion`:
   - Resolve `since`:
     ```python
     since = (
         since_override
         or os.getenv("GH_TRENDING_SINCE", "").strip().lower()
         or str(meta.get("metrics", {}).get("since", "")).strip().lower()
     )
     if since not in ("daily", "weekly"):
         since = "weekly" if datetime.now().weekday() == 6 else "daily"
     is_weekly = (since == "weekly")
     ```
   - Resolve `doc_date = extract_report_date(report) or meta.get("date_str") or datetime.now().strftime("%Y-%m-%d")`.
   - Archive local draft as `(ARCHIVE_DIR / f"{doc_date}.txt").write_text(report, encoding="utf-8")`.
   - Call `archive_to_notion(report, "🐙 GitHub & HN", date_str=doc_date, report_type="周盘点" if is_weekly else "日报")`.

**Verify**: Run `py_compile` on `/Users/jialiwu/.gemini/bots/github-hn-bot/github_hn_report.py` and `/Users/jialiwu/.gemini/bots/github-hn-bot/github_hn_report.py --help` -> exit 0.

### Step 4: Add offline regression tests

In `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py` (or a sibling `test_date_and_type_alignment.py` under `shared/tests/`):
1. `extract_report_date` extracts `2026-11-13` from `<b>🔥 X 热点 · 2026年11月13日</b>` and `2026-11-14` from `<b>🛠 AI Builder 日报 · 2026-11-14</b>\n\n这批推文来自 2026-11-13 UTC`, while returning `default` if absent.
2. Mock `already_ran_today`, `send_feishu`, `archive_to_notion`, `write_log`, and temp files:
   - Calling `bot_utils.send_x_linked_report` with a draft titled `2026-11-13` forwards `date_str="2026-11-13"` to `archive_to_notion` (even when mocked `datetime.now()` is `2026-11-14`).
   - Importing `github_hn_report` and invoking `run_send(since_override="weekly")` forwards `report_type="周盘点"`, and invoking `run_send(since_override="daily")` on a mocked Sunday forwards `report_type="日报"`, and invoking `run_send()` with `fetch_meta={"metrics": {"since": "weekly"}, "date_str": "2026-11-09"}` forwards `date_str="2026-11-09", report_type="周盘点"`.

**Verify**: `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` -> exit 0, zero failures, zero network calls.

## Test plan

- Suite: `/Users/jialiwu/.gemini/bots/shared/tests/`
- Command: `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v`
- Expectation: Exit 0, zero failures, all existing + new alignment tests pass completely offline.

## Done criteria

- [ ] `bot_utils.extract_report_date` exists and handles `YYYY-MM-DD` / `YYYY年M月D日` headings without matching body UTC date spans.
- [ ] `bot_utils.send_x_linked_report`, `AI Daily News Bot/daily_report.py`, and `github-hn-bot/github_hn_report.py` all load `fetch_meta` before archiving and pass explicit `date_str` to `archive_to_notion`.
- [ ] `github_hn_report.run_send` takes `since_override` from `args.since` (`main()`), respects `GH_TRENDING_SINCE` and `FETCH_META`, and respects `--since daily` on Sunday.
- [ ] `py_compile` and full `unittest` suite pass offline with zero modifications outside listed files.

## STOP conditions

Stop and report back (do not improvise) if:
- Importing `github_hn_report` or `daily_report` during unit tests executes module-level side effects that require network/proxy or touch production `logs/run.log` (load via temp `LOG_FILE`/`DRAFT_FILE` patching instead of running against real `logs/`).
- Any existing call site passes unexpected positional arguments to `run_send` or `send_x_linked_report`.

## Maintenance notes

- Keep heading date formatting in `AI Daily News Bot/prompt.md`, `x-hotspot-bot/prompt.md`, and `ai-builder-bot/prompt.md` aligned so line 1 always holds the business publication date (`YYYY-MM-DD` or `YYYY年M月D日`).
- Note `sys.path` setup in `shared/tests/` if importing sibling bot modules cleanly using `importlib.util.spec_from_file_location` (remember directories with spaces like `"AI Daily News Bot"` require `importlib` rather than package names).
