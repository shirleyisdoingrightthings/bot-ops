# Plan 002: Establish zero-dependency offline `unittest` baseline for `notion_archive.py`

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md` — unless a reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `git -C /Users/jialiwu/.gemini/bots/shared diff --stat 7c2707a..HEAD -- notion_archive.py requirements.txt`
> If `notion_archive.py` changed since `7c2707a`, inspect the diff before generating baseline fixtures.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `7c2707a` (`bot-ops` / `shared`), `2026-11-15`

## Why this matters

`/Users/jialiwu/.gemini/bots/shared/notion_archive.py` (844 lines) governs summary extraction, heading/TOC hierarchy, link parsing, and Notion REST submission for all 6 daily bots (`🐙 GitHub & HN`, `🗽 美股与加密`, `📈 A股与港股`, `🤖 AI 产业日报`, `🐦 X 热点播报`, `🛠️ AI Builder`). Currently the repository has zero automated tests. Every formatting rule tweak requires manual live Notion re-uploads and visual inspection across `11-11`..`11-14` pages. Adding a standard-library `unittest` suite locks down all 6 source formats offline in `<1s` and is a mandatory prerequisite before refactoring parser, summary, date, or upsert logic in Plans `003`–`006`.

## Current state

- `/Users/jialiwu/.gemini/bots/shared/notion_archive.py`:
  - `rich_text(text, *, default_bold=False)` (`L95-152`)
  - `extract_summary(text, source="")` (`L272-334`) & `_extract_cn_hk_market_brief(section_text, market_label, is_premarket)` (`L193-269`)
  - `_is_star_line(line)` (`L337-339`), `_is_news_headline_line(line)` (`L342-359`), `_is_x_builder_topic_heading(line, plain_no_b)` (`L362-372`), `_format_cn_hk_heading(plain_title)` (`L375-379`)
  - `convert_to_blocks(content, source="")` (`L382-599`)
  - `archive_to_notion(report_text, source, date_str=None, report_type="日报", title_override=None, database_id=DEFAULT_DATABASE_ID)` (`L602-806`)
- `/Users/jialiwu/.gemini/bots/shared/requirements.txt` (`L12-15`):
  - Runtime is `/usr/bin/python3` (`3.9.6`) with `requests>=2.31.0`, `feedparser>=6.0.10`.
  - No `pytest` dependency is declared; Python built-in `unittest` + `unittest.mock` keeps zero new dependencies.
- `/Users/jialiwu/.gemini/bots/shared/.gitignore`: ignores `*.log`, `.env`, `__pycache__/`, etc.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Syntax check | `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/notion_archive.py` | exit 0 |
| Run unit tests | `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` | exit 0, all tests pass |
| Check git status | `git -C /Users/jialiwu/.gemini/bots/shared status --short` | shows only expected test files |

*(Note: during the advisor audit session, Antigravity's local shell sandbox errored on `globs not supported`; run the commands above in a working shell or unsandboxed executor environment.)*

## Scope

**In scope** (create only):
- `/Users/jialiwu/.gemini/bots/shared/tests/__init__.py` (optional empty file for discovery compatibility)
- `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`

**Out of scope**:
- Do NOT modify `/Users/jialiwu/.gemini/bots/shared/notion_archive.py` or `requirements.txt` in this plan (keep tests characterizing *current* baseline behavior so later bugfix plans flip explicit bug-repro assertions).
- Do NOT make live Notion API HTTP calls or read `.env` secrets; mock `requests.Session` / `resolve_proxy` / `get_notion_api_key` cleanly.

## Git workflow

- Working repo: `/Users/jialiwu/.gemini/bots/shared`
- Commit style: conventional commits in Chinese matching `.git/logs/HEAD`, e.g., `test(notion_archive): 新增 6 大信源解析与归档离线单测基线`
- Do NOT push to remote unless explicitly instructed by the operator.

## Steps

### Step 1: Create `tests/` package and characterization tests for `rich_text` and helpers

Create `/Users/jialiwu/.gemini/bots/shared/tests/__init__.py` (empty) and `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py` adding `Path(__file__).resolve().parent.parent` to `sys.path`.
Write `unittest.TestCase` classes covering:
1. `TestRichText`:
   - Plain text, `**bold**`, `<b>bold</b>`, `[label](https://a.com)`, `**[label](https://a.com)**`, `<a href="https://a.com"><b>label</b></a>`.
   - Nested `<b>1. <a href="https://a.com">repo</a></b>` normalization (`notion_archive.py:98-110`).
   - Non-http links (`javascript:alert(1)`) stripped to plain text (`L147`).
   - Long text `> 2000` chars split cleanly into chunks `<= TEXT_LIMIT` (`L79-91`).
2. `TestHeadingHelpers`:
   - `_format_cn_hk_heading("🌅 🇨🇳 A股开盘前瞻 · 2026年11月13日")` -> `"🌅 🇨🇳 A股开盘前瞻 · 2026-11-13"`.
   - `_is_star_line("⭐⭐⭐⭐⭐ #AI模型 #AI产品")` -> `True`; `"⭐⭐⭐ 推荐"` -> `False` if non-tag prose.
   - `_is_x_builder_topic_heading("<b>1. 硅谷多位 CEO 联署声援黄仁勋</b>", "1. 硅谷多位 CEO 联署声援黄仁勋")` -> `True`.

**Verify**: `/usr/bin/python3 -m unittest /Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py -v` -> exits 0, all initial cases pass.

### Step 2: Add per-source `convert_to_blocks` & `extract_summary` golden characterization tests

In `tests/test_notion_archive.py`, add compact realistic inline fixtures (sanitized HTML/Markdown resembling real outputs of all 6 sources) verifying the **current intentional hierarchy**:
1. `🤖 AI 产业日报`:
   - Removes top `📋 AI 产业日报 · ...` title and `⚡ 30秒速览` block from body blocks (`L429`, `L464`).
   - Reorders legacy `⭐...` + headline into `heading_2` followed by `⭐...` paragraph (`L495-518`).
   - Preserves standard order headline (`heading_2`) -> `⭐...` -> `📄 The Details：` -> detail body.
2. `🐦 X 热点播报` & `🛠️ AI Builder`:
   - Removes top H1/title and opening intro paragraph (`L434-443`).
   - Converts `1. ...` topic headings into `heading_2` (`L444-452`), `## 📎 主流媒体同期在报` into `heading_2`, and `- ...` links into `bulleted_list_item`.
3. `🐙 GitHub & HN`:
   - Removes leading `🐙 GitHub Trending...` title (`L424`), converts `🚀 一、...` / `🔥 二、...` into `heading_2` (`L475-482`), and converts `<b>1. <a href="...">repo</a></b>` + `### 1. [title](url)` items into `heading_3` (`L484-491`).
4. `📈 A股与港股`:
   - Strips redundant `## 📈 A股市场（...）` / `## 🇭🇰 港股市场（...）` (`L419`), normalizes `2026年11月13日` in H1 (`L543-558`), splits on `---` into `divider`, and keeps `extract_summary` free of mid-sentence truncation.
5. `🗽 美股与加密`:
   - Preserves H1 `# 📊 美股收盘 & 加密行情` + H1 `# 📋 美股要闻`, strips repeated `⚡ 30秒速览` inside `美股要闻`, promotes news items inside `美股要闻` to `heading_2` (`L415-416`, `L494-518`).

**Verify**: `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` -> exits 0, all source characterization tests pass offline with zero network calls.

### Step 3: Add mocked `archive_to_notion` HTTP payload & error-handling tests

Using `unittest.mock.patch` on `notion_archive.get_notion_api_key`, `bot_utils.resolve_proxy`, and `requests.Session.request` (plus `subprocess.run` guarded against accidentally running `/usr/bin/curl`):
- Verify `archive_to_notion` sets exact Notion `properties`: `标题`, `日期.date.start`, `周次` (ISO week e.g. `2026-W46`), `信源`, `类型`, `30秒速览`.
- Verify missing API key returns `(False, ...)` without network calls (`L614-616`).
- Verify `>90` blocks sends first `90` in `POST /v1/pages` and remaining chunks to `PATCH /v1/blocks/{page_id}/children` (`L645`, `L790-802`).
- Verify HTTP 400 on `POST` returns `(False, "Notion API HTTP 400: ...")`.

**Verify**: `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` -> exits 0 with 0 skipped/network calls.

## Test plan

- File: `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`
- Cases: `TestRichText`, `TestHeadingHelpers`, `TestConvertToBlocksBySource`, `TestExtractSummaryBySource`, `TestArchiveToNotionHttp`.
- Pattern: Standard library `unittest.TestCase` + `unittest.mock` (no third-party test packages).

## Done criteria

- [ ] `/Users/jialiwu/.gemini/bots/shared/tests/__init__.py` and `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py` exist.
- [ ] `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` exits 0 with zero network access and all tests passing.
- [ ] Zero modifications to `/Users/jialiwu/.gemini/bots/shared/notion_archive.py` or any `.env` / production file (`git -C /Users/jialiwu/.gemini/bots/shared status` shows only `tests/`).

## STOP conditions

Stop and report back (do not improvise) if:
- Importing `notion_archive` fails due to missing runtime dependency in `/usr/bin/python3`.
- A characterization test reveals `notion_archive.py` already drifted from `7c2707a` behavior before writing tests.
- Any test triggers a real HTTP request to `api.notion.com` or `gstatic.com` during offline test execution.

## Maintenance notes

- Keep fixtures representative of actual sanitized bot drafts (including Chinese punctuation, `· ` lines, and HTML `<b>`/`<a>` tags).
- When Plans `003`–`006` land, update or add regression tests directly in `tests/test_notion_archive.py` so the suite grows monotonically with every bugfix.
