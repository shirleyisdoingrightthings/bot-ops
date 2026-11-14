# Plan 004: Surface market signals & focus highlights at the start of `30秒速览`

> **Executor instructions**: Follow this plan step by step. Run every verification command and confirm the expected result before moving to the next step. If anything in the "STOP conditions" section occurs, stop and report — do not improvise. When done, update the status row for this plan in `plans/README.md` — unless a reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `git -C /Users/jialiwu/.gemini/bots/shared diff --stat 7c2707a..HEAD -- notion_archive.py tests/test_notion_archive.py`
> Confirm Plan `002` is `DONE` and compare the "Current state" excerpts below against live `notion_archive.py`.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: `plans/002-notion-archive-unit-test-baseline.md`
- **Category**: dx (Notion UX / scannability)
- **Planned at**: commit `7c2707a` (`bot-ops` / `shared`), `2026-11-15`

## Why this matters

Live inspection of all 18 rows in Notion DB `e072f4c04bbf467793879e7dce4e4373` shows that `30秒速览` currently buries or drops the highest-leverage decision cues in truncated previews:
1. `🗽 美股与加密` (`41818b4d66e98132bc84e1ba03fda2dc`, `41718b4d66e981968924c5d4391b757e`): `extract_summary` only extracts the `30秒速览` block inside message ② (`美股要闻`), completely omitting message ①'s US index moves, BTC / Fear & Greed snapshot, and `信号灯状态`.
2. `📈 A股与港股` (`41818b4d66e981c7846ef556fcb6fd29`, `41818b4d66e9810c96f4e46901ae87ff`): `_extract_cn_hk_market_brief` places 250+ characters of index/sector details first and puts `信号灯状态：🔴 防守控仓` at the very end of each market half, so table/board previews hide the action signal completely.
3. `🛠️ AI Builder` (`41818b4d66e9818fb83bc3419476ddfd`, `...44fc3`, `...946f`): `extract_summary` starts with `"这批推文来自 2026-11-13 09:04 ~ 2026-11-14 05:19 UTC（北京时间 ...）"`, burning the first ~60–80 visible characters on timestamp boilerplate instead of the main conclusion and `本期焦点`.

## Current state

Excerpts from `/Users/jialiwu/.gemini/bots/shared/notion_archive.py` (`7c2707a`):

- Lines `249-270` (`_extract_cn_hk_market_brief`):
  ```python
    parts = []
    if indices_str:
        parts.append(indices_str)
    if is_premarket:
        if width_str:
            parts.append(width_str)
        if watch_titles:
            parts.append("核心看点：" + " / ".join(watch_titles[:3]))
    else:
        if width_str:
            parts.append(width_str)
        if gainers:
            parts.append("领涨：" + "、".join(gainers))
        if losers:
            parts.append("领跌：" + "、".join(losers))
    if signal_str:
        parts.append(signal_str)
    parts = [p.strip().rstrip("；;。") for p in parts if p and p.strip().rstrip("；;。")]
    if parts:
        parts[0] = f"【{market_label}】{parts[0]}"
    return "；".join(parts)
  ```
- Lines `272-323` (`extract_summary`):
  ```python
  def extract_summary(text: str, source: str = "") -> str:
      """从稿件中抽取 30 秒速览或完整结构化要点（保证绝不半句截断）"""
      # 1. A股与港股：分别抽取 A股 + 港股 核心数据与看点/信号灯
      if "A股与港股" in source or ("A股开盘前瞻" in text or "A股收盘复盘" in text):
          secs = re.split(r"\n\s*---+\s*\n", text, maxsplit=1)
          is_pre = ("开盘前瞻" in text)
          cn_brief = _extract_cn_hk_market_brief(secs[0], "A股", is_pre)
          hk_brief = _extract_cn_hk_market_brief(secs[1], "港股", is_pre) if len(secs) > 1 else ""
          combined = _join_clauses([p for p in (cn_brief, hk_brief) if p], max_chars=1600)
          if combined:
              return combined

      # 2. 匹配 30秒速览 区块（兼容带 <b> 包裹的章节标题，遇到 ⭐ 条目 / 标题链接 / 大板块即止）
      m = re.search(
          r"(?:⚡\s*30秒速览|30秒速览)[\s\S]*?(?=\n\s*(?:<(?:b|strong)\b[^>]*>\s*)*(?:[#🚀🔥❄️⚡🔭🎯📰📎📈🗽🤖🐦🛠️⭐]|<a\s+[^>]*href=|\*\*\[|---)|\Z)",
          text,
          re.IGNORECASE,
      )
      if m:
          summary_block = m.group().strip()
          lines = [line.strip() for line in summary_block.splitlines() if line.strip()]
          content_lines = [
              _strip_tags_plain(l).lstrip("-*•> ").strip()
              for l in lines
              if not re.search(r"30秒速览", l)
          ]
          joined = _join_clauses(content_lines, max_chars=1400)
          if joined:
              return joined

      # 3. X 热点播报 & AI Builder：首段导语 + 全部编号主题标题
      if "X 热点" in source or "AI Builder" in source or re.search(r"^(?:#+\s*)?(?:<b>)?(?:🔥\s*X\s*热点|🛠\uFE0F?\s*AI\s*Builder)", text.strip()):
          plain_lines = [re.sub(r"^#{1,3}\s*", "", _strip_tags_plain(l)).strip() for l in text.splitlines()]
          plain_lines = [l for l in plain_lines if l]
          overview = ""
          topics: list[str] = []
          for idx, line in enumerate(plain_lines):
              if re.match(r"^(?:🔥\s*X\s*热点|🛠\uFE0F?\s*AI\s*Builder)", line):
                  continue
              if re.match(r"^\d+\.\s+", line) and len(line) <= 80:
                  topics.append(line)
              elif not overview and not line.startswith(("原帖：", "原推：", "长文", "素材：", "📎", "- ")):
                  overview = line
          clauses = []
          if overview:
              clauses.append(overview)
          if topics:
              clauses.append("本期焦点：" + " / ".join(topics))
          joined = _join_clauses(clauses, max_chars=1400)
          if joined:
              return joined
  ```

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Syntax check | `/usr/bin/python3 -m py_compile /Users/jialiwu/.gemini/bots/shared/notion_archive.py` | exit 0 |
| Test suite | `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` | exit 0, all pass |

## Scope

**In scope**:
- `/Users/jialiwu/.gemini/bots/shared/notion_archive.py` (`_extract_cn_hk_market_brief`, `extract_summary`, plus a helper `_extract_us_market_brief` if extracted cleanly)
- `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`

**Out of scope**:
- Do NOT touch `convert_to_blocks` or `archive_to_notion` HTTP calls in this plan.
- Do NOT truncate clauses mid-sentence (preserve `_join_clauses` complete-clause contract, `max_chars=1600`/`1400`).
- Do NOT edit individual bot `prompt*.md` files.

## Git workflow

- Working repo: `/Users/jialiwu/.gemini/bots/shared`
- Commit style: `fix(notion_archive): 前置 A/H 信号灯、补全美股盘面与清理 AI Builder 速览时间戳`
- Do NOT push without operator confirmation.

## Steps

### Step 1: Front-load `信号灯状态` / `早盘信号灯` in `_extract_cn_hk_market_brief`

In `_extract_cn_hk_market_brief` (`notion_archive.py:249-269`):
1. Put `signal_str` FIRST in `parts` (right after `【{market_label}】`), followed by `indices_str`, `width_str`, and `watch_titles`/`gainers`/`losers`.
2. Example resulting lead string: `【A股】信号灯状态：🔴 防守控仓；核心指数：上证指数 ...` and `【港股】信号灯状态：🔴 防守控仓；核心指数：...`.
3. Add an `assert` test in `tests/test_notion_archive.py` confirming `【A股】信号灯` / `【A股】早盘信号灯` appears within the first 40 characters of `extract_summary(...)` for both `开盘前瞻` and `收盘复盘`, and all clauses remain complete without mid-sentence truncation.

**Verify**: Run `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` -> exits 0.

### Step 2: Prepend US market & crypto decision snapshot to `🗽 美股与加密` `30秒速览`

In `notion_archive.py`, add helper `_extract_us_market_brief(market_text: str) -> str` and invoke it in `extract_summary` when `"美股" in source or "美股收盘" in text`:
1. Split `text` on `\n\s*---+\s*\n` (`maxsplit=1`) into `market_sec` and `news_sec` (only when `---` exists).
2. From `market_sec`, strip tags and extract:
   - `信号灯状态` line (`· 信号灯状态：...`, split at `—` for concise badge `🟢/🟡/🔴 ...`)
   - `核心指数` line (`📈 核心指数：...`)
   - `加密（24h）` / `加密情绪` summary (`BTC` & `恐贪指数`, optional if present)
   Combine into a concise header clause e.g. `【美股盘面】信号灯：🟡 震荡分化｜核心指数：...` (staying compact).
3. Extract the existing `30秒速览` news bullets from `news_sec` (or full `text`) via the existing branch #2 regex, then combine `[market_brief] + content_lines` using `_join_clauses(..., max_chars=1600)`.
4. Ensure fallback still works cleanly if a test passes `美股要闻` alone without `market_sec`.

**Verify**: Run unit tests verifying `🗽 美股与加密` `30秒速览` contains BOTH `【美股盘面】` (signal light + indices) AND the `美股要闻` bullets, within `<= 1600` chars and without half-sentence cuts.

### Step 3: Trim boilerplate UTC timestamp prefix from `🛠️ AI Builder` `30秒速览`

In `extract_summary` branch #3 (`notion_archive.py:302-322`):
1. When building `overview` (especially for `AI Builder`), strip leading UTC/Beijing window boilerplate matching `r"^这批推文(?:集中)?(?:发布于|来自)\s+[^，,。]+(?:UTC)?(?:\s*[（(][^）)]*[）)])?\s*[，,：:]\s*"` so `overview` starts directly with the editorial theme (`"今天活跃的一线 builder 主要围绕..."` or `"今天多位一线 Builder 集中探讨了..."`).
2. Keep `本期焦点：1. ... / 2. ...` intact (or place concise `overview` + `本期焦点：...`). Do not alter `X 热点播报` behavior unless it contains the same boilerplate prefix.

**Verify**: Run `/usr/bin/python3 -m unittest discover -s /Users/jialiwu/.gemini/bots/shared/tests -v` -> all pass, and verify `AI Builder` `extract_summary` output no longer starts with `"这批推文"`.

## Test plan

- File: `/Users/jialiwu/.gemini/bots/shared/tests/test_notion_archive.py`
- Cases to add/update:
  - `test_cn_hk_summary_frontloads_signal`: verifies `开盘前瞻` and `收盘复盘` start with `【A股】早盘信号灯` / `【A股】信号灯状态`.
  - `test_us_stock_summary_includes_market_and_news`: verifies `美股与加密` combined text puts signal light + index line first, followed by news bullets.
  - `test_ai_builder_summary_strips_utc_boilerplate`: verifies `"这批推文来自 2026-11-13 09:04 ~ ... UTC（北京时间 ...），今天活跃..."` becomes `"今天活跃..."` + `本期焦点：...`.

## Done criteria

- [ ] `_extract_cn_hk_market_brief` places `信号灯` at the start of both `【A股】` and `【港股】` clauses.
- [ ] `🗽 美股与加密` `30秒速览` includes message ① signal light + core indices before message ② news bullets.
- [ ] `🛠️ AI Builder` `30秒速览` strips `"这批推文来自 ... UTC（...），"` timestamp lead boilerplate.
- [ ] `py_compile` and full `unittest` suite exit 0.

## STOP conditions

Stop and report back (do not improvise) if:
- `extract_summary` for any fixture exceeds `TEXT_LIMIT` (`2000` chars) or produces empty output when `market_sec` uses slightly different heading text.
- Any baseline test from Plan `002` for `X 热点播报` or `GitHub & HN` breaks unintentionally.

## Maintenance notes

- Keep `_extract_us_market_brief` aligned with emoji headers in `us stock bot/prompt_market.md` (`📈 核心指数`, `🪙 加密（24h）`, `· 信号灯状态：`).
- Notice `美股与加密` `1600`-char cap in `_join_clauses` drops trailing news clauses cleanly if very long; prioritize concise market header (`<= 300` chars) so top 3–5 news clauses still fit.
