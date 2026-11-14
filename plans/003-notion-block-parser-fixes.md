# Plan 003: Fix `· ` bullet conversion, `heading_2` misdetection in details, parenthesized URLs, and italics

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md` — unless a reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `git -C /Users/jialiwu/.gemini/bots/shared diff --stat 7c2707a..HEAD -- notion_archive.py tests/test_notion_archive.py`
> Confirm Plan `002` is `DONE` and compare the "Current state" excerpts below against live `notion_archive.py` before editing.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/002-notion-archive-unit-test-baseline.md`
- **Category**: bug
- **Planned at**: commit `7c2707a` (`bot-ops` / `shared`), `2026-11-15`

## Why this matters

Three confirmed parsing bugs in `notion_archive.py` degrade Notion page hierarchy and link fidelity:
1. Lines beginning with `· ` (`U+00B7`, used across `GitHub & HN`, `A股与港股`, and `美股收盘` details/dashboards) are normalized to `- ` for Feishu (`bot_utils.py:502`), yet `notion_archive.py:579` ignores `· `, turning all list items into flat unindented `paragraph` blocks in Notion.
2. `_is_news_headline_line` (`L342-359`) promotes any non-blacklisted line `<= 120` chars containing `<a href=...>` (or short bold line `<= 45` chars) to `heading_2`, without tracking whether the parser is currently inside a `📄 The Details：` body section; any short detail sentence or reference link inside `AI 产业日报` / `美股要闻` corrupts the right-hand Content TOC.
3. `INLINE_RE` (`L57-65`) rejects Markdown URLs containing balanced parentheses (such as Wikipedia entries), `_RESIDUAL_TAG_RE` (`L67`) strips `<i>`/`<em>` tags instead of setting Notion `italic: True`, and GitHub top-title stripping (`L424`) breaks if `>= 5` blank lines precede the title.

## Current state

Excerpts from `/Users/jialiwu/.gemini/bots/shared/notion_archive.py` (`7c2707a`):

- Lines `57-92` (`INLINE_RE`, `_RESIDUAL_TAG_RE`, `_text_items`):
  ```python
  INLINE_RE = re.compile(
      r"(?P<code>`[^`\n]+`)"
      r"|(?P<bold_link>\*\*\[[^\]\n]+\]\([^()\s]+\)\*\*)"
      r"|(?P<html_link><a\s+[^>]*?href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<anchor>.*?)</a>)"
      r"|(?P<link>\[[^\]\n]+\]\([^()\s]+\))"
      r"|(?P<bold>\*\*.+?\*\*)"
      r"|(?P<html_bold><b>.*?</b>)",
      re.IGNORECASE,
  )

  _RESIDUAL_TAG_RE = re.compile(r"</?(?:b|strong|i|em|code|a)(?:\s+[^<>]*)?>", re.I)
  ```
- Lines `342-359` (`_is_news_headline_line`):
  ```python
  def _is_news_headline_line(line: str) -> bool:
      """判断在 AI 产业日报 / 美股要闻 中该行是否为单条新闻标题行"""
      s = line.strip()
      if not s:
          return False
      s_no_hash = re.sub(r"^#{1,3}\s*", "", s).strip()
      plain = re.sub(r"^#{1,3}\s*", "", _strip_tags_plain(s)).strip()
      if not plain or len(plain) > 120:
          return False
      if plain.startswith(("⭐", "📄", "⚡", "📋", "📊", "🌅", "🇨🇳", "🇭🇰", "🐙", "🔥", "❄️", "🔭", "🎯", "📎", "🚀", "📰", "🧭", "📐", "📈", "💰", "🌡", "🪙", "🇺🇸", "🌍", "·", "•", "-", "30秒速览")):
          return False
      if s.startswith("## "):
          return True
      if re.search(r"<a\s+[^>]*href=", s_no_hash, re.I) or re.match(r"^(?:\*\*)?\[[^\]]+\]\([^)]+\)(?:\*\*)?$", s_no_hash):
          return True
      if s_no_hash.startswith(("<b>", "**")) and ("。" not in plain or len(plain) <= 45):
          return True
      return False
  ```
- Line `424` (`convert_to_blocks` GitHub title removal):
  ```python
  if is_gh and i <= 4 and re.match(r"^🐙\s*GitHub\s+(?:Trending|Weekly)", plain_clean, re.I):
  ```
- Lines `493-523` (`AI 产业日报` & `美股要闻` inside `convert_to_blocks`):
  No `in_details` state tracks `📄 The Details：`.
- Lines `578-586` (`convert_to_blocks` list conversion):
  ```python
        # 列表条目
        if line.startswith("- ") or line.startswith("• "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": rich_text(line[2:].strip())}
            })
            i += 1
            continue
  ```
- Repo exemplar for bullet normalization: `/Users/jialiwu/.gemini/bots/shared/bot_utils.py:502`:
  `res_line = re.sub(r"^[·•●▪]\s*", "- ", res_line)`

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Syntax check | `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/notion_archive.py` | exit 0 |
| Test suite | `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` | exit 0, all pass |

## Scope

**In scope**:
- `/Users/jialiwu/.gemini/bots/shared/notion_archive.py`
- `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`

**Out of scope**:
- Do NOT touch `extract_summary` / `_extract_cn_hk_market_brief` (handled in Plan `004`).
- Do NOT alter HTTP retry / upsert logic in `archive_to_notion` (handled in Plan `006`).
- Do NOT change any `bot_utils.py` Feishu formatting (`html_to_lark_md`).

## Git workflow

- Working repo: `/Users/jialiwu/.gemini/bots/shared`
- Commit style: `fix(notion_archive): 修复 · 列表转换、正文短句误判 H2 及括号 URL/斜体解析`
- Do NOT push without operator confirmation.

## Steps

### Step 1: Convert `· ` (and `•`/`●`/`▪`) lines to Notion `bulleted_list_item` and fix GitHub top-title removal

In `/Users/jialiwu/.gemini/bots/shared/notion_archive.py`:
1. Near line `579`, match standard bullets consistently with `bot_utils.py:502`:
   `if re.match(r"^(?:-\s+|[·•●▪]\s*)", line):`
   Strip the leading bullet + whitespace via `re.sub(r"^(?:-\s+|[·•●▪]\s*)", "", line).strip()` and emit `bulleted_list_item`.
   (Confirm lines starting with `·` that also appear in `AI 产业日报` / `美股要闻` are already excluded from `_is_news_headline_line` on line `351`.)
2. Near line `424`, replace `i <= 4` with a `seen_gh_content` boolean (false before the first non-title block is emitted) so leading blank lines never break removal of `🐙 GitHub Trending...` / `🐙 GitHub Weekly...`, while never stripping anything mid-body.

**Verify**: Run `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/notion_archive.py` -> exit 0.

### Step 2: Guard `_is_news_headline_line` against detail-body false positives

In `convert_to_blocks` (`notion_archive.py:391-523`), track `in_details = False` for `is_ai_daily or (is_us and in_us_news)`:
1. When emitting a `heading_2` news headline (or encountering `---`), set `in_details = False`.
2. When encountering a line whose stripped text begins with `📄` (e.g., `📄 The Details：`), set `in_details = True`.
3. Only call `_is_news_headline_line(line)` when `not in_details` OR when the line is an explicit Markdown heading (`line.startswith("## ")`) OR is an entire standalone link/bold-link line (matching `^(?:<a\b[^>]*>.*?</a>|\*\*\[[^\]]+\]\([^)]+\)\*\*|\[[^\]]+\]\([^)]+\))$`, i.e., NOT a prose sentence merely containing an inline `<a href>` mid-sentence).
4. In `_is_news_headline_line` (`L355`), narrow the link check from `re.search(r"<a\s+[^>]*href=", s_no_hash, re.I)` to full-line headline links (`^#{0,3}\s*(?:<b\b[^>]*>\s*)?<a\s+[^>]*href=.*?</a>(?:\s*</b>)?$` or standalone Markdown link), while still keeping `s.startswith("## ")` -> `True` so `##` headings from exported Notion content always work regardless of link count.

**Verify**: Verify with a quick unit test asserting that `"相关详见 <a href=\"https://x.com/a/status/1\">原帖</a>。"` after `"📄 The Details："` becomes a `paragraph`, whereas `"<a href=\"https://example.com\"><b>某条新闻标题</b></a>"` becomes `heading_2`, and the next headline after a multi-paragraph detail block STILL becomes `heading_2`.

### Step 3: Support balanced parentheses in URLs and preserve `<i>`/`<em>` italics

In `/Users/jialiwu/.gemini/bots/shared/notion_archive.py`:
1. In `_text_items` (`L75-92`), add `*, italic: bool = False` keyword parameter; if `italic`, include `annotations["italic"] = True`.
2. Update `INLINE_RE` (`L57-65`):
   - Allow one level of balanced parentheses in Markdown URLs using `(?:\([^()\s]*\)|[^()\s])+` instead of `[^()\s]+` (in `bold_link`, `link`, and `rich_text` inner checks at lines `121, 127, 133, 138`).
   - Add `|(?P<html_italic><(?:i|em)>.*?</(?:i|em)>)` and handle `kind == "html_italic"` in `rich_text()` (`_text_items(..., bold=default_bold, italic=True)`, or recursive `rich_text` if inner links/bold exist — pass `italic` down safely).

**Verify**: Run `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` -> exit 0.

### Step 4: Add unit tests for all three fixes

Add dedicated tests in `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`:
- `· <b>它是干嘛的</b>：...` -> `bulleted_list_item` (not `paragraph`), preserving bold prefix.
- Inside `AI 产业日报` after `📄 The Details：`, a `< 120`-char prose sentence with an inline `<a href="https://example.com">...</a>` becomes `paragraph`, while the next standalone news link `<a href="https://example.com/2"><b>下一条头条</b></a>` becomes `heading_2`.
- `[Wiki](https://en.wikipedia.org/wiki/Claude_(language_model))` preserves the full URL with closing `)`.
- `<i>italic note</i>` emits `"italic": True` in Notion annotations.
- Leading 6 blank lines before `🐙 GitHub Trending` still strip the redundant top H1.

**Verify**: `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` -> exit 0, all new and baseline tests pass.

## Test plan

- File: `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`
- Run: `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v`
- Expectation: Exit 0, zero failures, all new regression tests pass.

## Done criteria

- [ ] `notion_archive.py` converts `· ` (`U+00B7`) lines to `bulleted_list_item`.
- [ ] Short detail sentences with inline `<a href>` inside `📄 The Details：` never become `heading_2`, while consecutive headlines still become `heading_2`.
- [ ] Markdown links with balanced `(...)` and `<i>`/`<em>` tags preserve complete URLs and italic annotations.
- [ ] `py_compile` and full `unittest` suite exit 0; no files outside `notion_archive.py` and `tests/test_notion_archive.py` are modified.

## STOP conditions

Stop and report back (do not improvise) if:
- Any baseline source-layout test from Plan `002` fails after the `_is_news_headline_line` / `in_details` change (for example, an existing `美股要闻` item with inline link in its headline format).
- Notion block schema fails validation for `italic` or `bulleted_list_item` formatting.

## Maintenance notes

- Keep `_is_news_headline_line` synchronized with `AI Daily News Bot/prompt.md` and `us stock bot/prompt_news.md` headline formats (`<a href="..."><b>标题</b></a>` or `## [...]`).
- Multi-level nested parentheses in Markdown URLs remain unsupported beyond 1 balanced level; HTML `<a href="...">` remains preferred in bot prompts.
