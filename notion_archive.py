#!/usr/bin/env python3
"""
notion_archive.py — 定时 Bot 每日内容同步归档至 Notion 数据库。

数据库：每日情报归档与决策看板
URL: https://app.notion.com/p/e072f4c04bbf467793879e7dce4e4373
Database ID: e072f4c04bbf467793879e7dce4e4373
Collection ID: e1052ed6-a74e-4029-9396-499280ad5f2d

支持两种调用模式：
1. Python 模块调用：from notion_archive import archive_to_notion
2. CLI 命令行调用：python3 notion_archive.py --source "🐙 GitHub & HN" --draft "path/to/draft.txt"
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import requests
from datetime import datetime
from pathlib import Path

# 常量定义
DEFAULT_DATABASE_ID = "e072f4c04bbf467793879e7dce4e4373"
NOTION_VERSION = "2022-06-28"
TEXT_LIMIT = 2000

# 从环境变量或 bots/shared/.env 获取专属归档 API KEY（与 youtube-to-blog 隔离）
def get_notion_api_key() -> str:
    key = os.getenv("NOTION_ARCHIVE_API_KEY", "").strip()
    if key:
        return key
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("NOTION_ARCHIVE_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


# ───────────────────────────────────────────
# Markdown / HTML 解析为 Notion Blocks
# ───────────────────────────────────────────

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


def _clean_text(s: str) -> str:
    s = re.sub(r"&amp;(?:amp;)+", "&amp;", s or "")
    return html.unescape(_RESIDUAL_TAG_RE.sub("", s))


def _text_items(content: str, *, bold: bool = False, code: bool = False, link: str | None = None) -> list:
    if not content:
        return []
    items = []
    chunks = [content[i : i + TEXT_LIMIT] for i in range(0, len(content), TEXT_LIMIT)]
    for chunk in chunks:
        item = {"type": "text", "text": {"content": chunk}}
        if link:
            item["text"]["link"] = {"url": link}
        annotations = {}
        if bold:
            annotations["bold"] = True
        if code:
            annotations["code"] = True
        if annotations:
            item["annotations"] = annotations
        items.append(item)
    return items


def rich_text(text: str, *, default_bold: bool = False) -> list:
    """把行内 Markdown 与受控 HTML 转换为 Notion rich_text"""
    # 预处理嵌套 <b>1. <a href="...">Title</a></b> → <b>1.</b> <a href="..."><b>Title</b></a>
    text = re.sub(
        r"<b>(\d+\.)\s*(<a\s+[^>]+>)(?:<b>)?(.*?)(?:</b>)?</a>\s*</b>",
        r"<b>\1</b> \2<b>\3</b></a>",
        text,
        flags=re.I,
    )
    # 预处理裸包裹 <b><a href="...">Title</a></b> → <a href="..."><b>Title</b></a>
    text = re.sub(
        r"<b>\s*(<a\s+[^>]+>)(?:<b>)?(.*?)(?:</b>)?</a>\s*</b>",
        r"\1<b>\2</b></a>",
        text,
        flags=re.I,
    )
    parts = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            parts += _text_items(_clean_text(text[pos : m.start()]), bold=default_bold)
        kind = m.lastgroup
        raw = m.group()
        if kind == "code":
            parts += _text_items(html.unescape(raw[1:-1]), bold=default_bold, code=True)
        elif kind == "bold_link":
            match = re.match(r"\*\*\[([^\]]+)\]\(([^)]+)\)\*\*", raw)
            if match:
                label, url = match.groups()
                parts += _text_items(html.unescape(label), bold=True, link=url)
        elif kind == "bold":
            inner = raw[2:-2]
            if re.search(r"<a\s|\[[^\]\n]+\]\([^()\s]+\)", inner, re.I):
                parts += rich_text(inner, default_bold=True)
            else:
                parts += _text_items(_clean_text(inner), bold=True)
        elif kind == "html_bold":
            inner = raw[3:-4]
            if re.search(r"<a\s|\[[^\]\n]+\]\([^()\s]+\)", inner, re.I):
                parts += rich_text(inner, default_bold=True)
            else:
                parts += _text_items(_clean_text(inner), bold=True)
        elif kind == "link":
            match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", raw)
            if match:
                label, url = match.groups()
                parts += _text_items(html.unescape(label), bold=default_bold, link=url)
        elif kind == "html_link":
            href = html.unescape(m.group("href")).strip()
            anchor = m.group("anchor")
            is_bold = default_bold or bool(re.search(r"<\s*(?:b|strong)\b", anchor, re.I))
            clean_anchor = html.unescape(re.sub(r"<[^>]+>", "", anchor)).strip()
            valid_href = href if href.lower().startswith(("http://", "https://")) else None
            parts += _text_items(clean_anchor or href, bold=is_bold, link=valid_href)
        pos = m.end()
    if pos < len(text):
        parts += _text_items(_clean_text(text[pos:]), bold=default_bold)
    return parts or _text_items(_clean_text(text), bold=default_bold)


def _strip_tags_plain(s: str) -> str:
    """将 HTML / Markdown 链接剥离为可读纯文本"""
    s = re.sub(r"<a\s+[^>]*?href=[\"'][^\"']+[\"'][^>]*>(.*?)</a>", r"\1", s or "", flags=re.I | re.S)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    return html.unescape(s).strip()


def _join_clauses(clauses: list[str], max_chars: int = 1400) -> str:
    """完整分句拼接，严格避免截断在半句话中间"""
    cleaned = []
    for c in clauses:
        t = re.sub(r"\s+", " ", (c or "")).strip().rstrip("；;。")
        if t:
            cleaned.append(t)
    if not cleaned:
        return ""
    out_parts = []
    cur_len = 0
    for c in cleaned:
        add_len = len(c) + (1 if out_parts else 0)
        if out_parts and cur_len + add_len > max_chars:
            break
        out_parts.append(c)
        cur_len += add_len
    res = "；".join(out_parts)
    if len(res) > max_chars:
        cut = res[:max_chars]
        for sep in ("；", "。", "，", " "):
            idx = cut.rfind(sep)
            if idx >= max_chars // 2:
                cut = cut[:idx]
                break
        res = cut.rstrip("；，, ")
    return res + "。" if res and not res.endswith(("。", "！", "？")) else res


def _extract_cn_hk_market_brief(section_text: str, market_label: str, is_premarket: bool) -> str:
    """从 A股 或 港股 单篇正文提取完整不截断的摘要片段"""
    plain_lines = [_strip_tags_plain(l) for l in section_text.splitlines()]
    plain_lines = [
        re.sub(r"^#{1,3}\s*", "", l).strip()
        for l in plain_lines
        if l and not re.match(r"^(?:#{1,3}\s*)?(?:📈|📉|🇭🇰|🇨🇳|\s)*(?:A股|港股)市场（.*?）\s*$", l)
    ]

    indices_str = ""
    width_str = ""
    signal_str = ""
    gainers: list[str] = []
    losers: list[str] = []
    watch_titles: list[str] = []

    mode_section = ""
    for line in plain_lines:
        clean_line = re.sub(r"^(?:[\U0001F1E6-\U0001F1FF]{2}|[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\s])+", "", line).strip()
        if is_premarket:
            if not indices_str and re.match(r"^隔夜(?:外围映射|中概)", clean_line):
                indices_str = clean_line
            elif not width_str and re.match(r"^前日(?:收盘|港股)技术锚点", clean_line):
                width_str = clean_line
            elif line.startswith("⚡"):
                mode_section = "watch"
            elif line.startswith("🎯"):
                mode_section = "signal"
            elif mode_section == "watch" and re.match(r"^\d+\.\s+", line):
                head = line.split("：", 1)[0].split(":", 1)[0].strip()
                watch_titles.append(head)
            elif mode_section == "signal" and ("信号灯" in line):
                sig = line.lstrip("·• ").strip()
                signal_str = sig.split("—", 1)[0].strip()
        else:
            if not indices_str and re.match(r"^核心指数", clean_line):
                indices_str = clean_line
            elif line.startswith("🧭 市场宽度"):
                if "—" in line:
                    width_str = line.split("—", 1)[1].strip()
            elif line.startswith("🔥"):
                mode_section = "gain"
            elif line.startswith("❄️"):
                mode_section = "loss"
            elif line.startswith(("🔭", "🎯")):
                mode_section = "signal" if line.startswith("🎯") else ""
            elif mode_section in ("gain", "loss") and re.match(r"^\d+\.\s+", line):
                item = re.sub(r"^\d+\.\s+", "", line).strip()
                if mode_section == "gain" and len(gainers) < 3:
                    gainers.append(item)
                elif mode_section == "loss" and len(losers) < 3:
                    losers.append(item)
            elif mode_section == "signal" and "信号灯状态" in line:
                sig = line.lstrip("·• ").strip()
                signal_str = sig.split("—", 1)[0].strip()

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

    # 4. 兜底：取完整句子，不超过 600 字符，严禁半句截断
    clean = _strip_tags_plain(text).replace("\n", " ")
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) <= 600:
        return clean
    cut = clean[:600]
    for sep in ("。", "！", "？", "；", ". "):
        idx = cut.rfind(sep)
        if idx >= 180:
            return cut[: idx + (1 if sep != ". " else 1)].strip()
    return cut


def _is_star_line(line: str) -> bool:
    plain = _strip_tags_plain(line).strip()
    return bool(re.match(r"^⭐+(?:\s+#\S+.*)?$", plain))


def _is_news_headline_line(line: str) -> bool:
    """判断在 AI 产业日报 / 美股要闻 中该行是否为单条新闻标题行"""
    s = line.strip()
    if not s:
        return False
    plain = _strip_tags_plain(s)
    if not plain or len(plain) > 120:
        return False
    if plain.startswith(("⭐", "📄", "⚡", "📋", "📊", "🌅", "🇨🇳", "🇭🇰", "🐙", "🔥", "❄️", "🔭", "🎯", "📎", "🚀", "📰", "🧭", "📐", "📈", "💰", "🌡", "🪙", "🇺🇸", "🌍", "·", "•", "-", "30秒速览")):
        return False
    if re.search(r"<a\s+[^>]*href=", s, re.I) or re.match(r"^(?:\*\*)?\[[^\]]+\]\([^)]+\)(?:\*\*)?$", s):
        return True
    if s.startswith(("<b>", "**")) and ("。" not in plain or len(plain) <= 45):
        return True
    return False


def _format_cn_hk_heading(plain_title: str) -> str:
    """将 A股/港股 标题中的 2026年11月13日 统一规范为 2026-11-13"""
    def _repl(m):
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return re.sub(r"(\d{4})年(\d{1,2})月(\d{1,2})日", _repl, plain_title)


def convert_to_blocks(content: str, source: str = "") -> list[dict]:
    """将稿件转换为 Notion Blocks 结构，并按信源优化 Notion 目录层级与去重排版"""
    blocks = []
    lines = content.splitlines()
    is_gh = ("GitHub & HN" in source)
    is_ai_daily = ("AI 产业日报" in source)
    is_us = ("美股" in source)
    is_cn_hk = ("A股与港股" in source)
    in_us_news = False
    pending_star_line: str | None = None

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue

        plain_no_b = html.unescape(re.sub(r"</?(?:b|strong)>", "", line, flags=re.I)).strip()

        # 跟踪美股要闻段落边界（美股收盘消息①之后、--- 之后）
        if is_us and re.match(r"^(?:#\s*)?(?:<b>)?📋\s*美股要闻", plain_no_b):
            in_us_news = True

        # A股与港股：删掉冗余的 `## 📈 A股市场（...）` / `## 🇭🇰 港股市场（...）` 外层标题
        if is_cn_hk and re.match(r"^(?:#{1,3}\s*)?(?:📈|📉|🇭🇰|🇨🇳|\s)*(?:A股|港股)市场（.*?）\s*$", plain_no_b):
            i += 1
            continue

        # GitHub & HN：删掉 Notion 正文顶部的重复大标题（页面标题已展示）
        if is_gh and i <= 4 and re.match(r"^(?:#\s*)?🐙\s*GitHub\s+(?:Trending|Weekly)", plain_no_b, re.I):
            i += 1
            continue

        # 分割线
        if line.startswith("---") or line.startswith("━━━"):
            if pending_star_line:
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(pending_star_line)}})
                pending_star_line = None
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # 30 秒速览处理：AI 产业日报 / 美股要闻 / GitHub & HN 在 Notion 正文中删去重复的 30秒速览（上方属性已完整显示）
        if "30秒速览" in plain_no_b and (line.startswith(("<b>", "#", ">", "⚡", "30秒速览", "**")) or re.match(r"^#{1,3}\s*⚡?\s*30秒速览", line)):
            i += 1
            while i < len(lines) and (
                lines[i].strip().startswith(("-", "•", ">"))
                or not lines[i].strip()
            ):
                i += 1
            continue

        # GitHub & HN：一级标题与二级标题层级（跳过普通 markdown/HTML 判定前优先识别）
        if is_gh:
            if any(plain_no_b.startswith(p) for p in ("🚀 一、", "🔥 一、", "🔥 二、", "📰 二、", "🔥 持续霸榜")):
                blocks.append({
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {"rich_text": rich_text(plain_no_b)}
                })
                i += 1
                continue
            if re.match(r"^(?:<b>|\*\*)?\d+\.(?:</b>|\*\*)?\s*(?:<a\b|\[|<b\b|\*\*)", line, re.I):
                blocks.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": rich_text(line)}
                })
                i += 1
                continue

        # AI 产业日报 & 美股要闻：新闻标题（heading_2）→ 星级以及 tag 标签 → details（兼容新旧两种顺序）
        if is_ai_daily or (is_us and in_us_news):
            if _is_star_line(line):
                # 兼容旧顺序：先遇到星级行，暂存，紧接着把下一行的标题作为 H2 放到前面
                if pending_star_line:
                    blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(pending_star_line)}})
                pending_star_line = line
                i += 1
                continue

            if _is_news_headline_line(line):
                title_for_h2 = re.sub(r"^#{1,3}\s*", "", line).strip()
                blocks.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": rich_text(title_for_h2)}
                })
                if pending_star_line:
                    blocks.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": rich_text(pending_star_line)}
                    })
                    pending_star_line = None
                i += 1
                continue

            if pending_star_line:
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(pending_star_line)}})
                pending_star_line = None

        # Markdown 标题处理（含从 Notion 导出的 #/##/###）
        if line.startswith("### "):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": rich_text(line[4:].strip())}
            })
            i += 1
            continue
        if line.startswith("## "):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": rich_text(line[3:].strip())}
            })
            i += 1
            continue
        if line.startswith("# "):
            h1_text = line[2:].strip()
            if is_cn_hk:
                h1_text = _format_cn_hk_heading(h1_text)
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": rich_text(h1_text)}
            })
            i += 1
            continue

        # HTML 顶层主标题（日报/早报/收盘复盘总标题 → heading_1）
        if re.match(
            r"^(?:🌅\s*)?(?:📊\s*美股收盘|📋\s*(?:AI\s*产业日报|美股要闻)|🐙\s*GitHub|🔥\s*X\s*热点|🛠️?\s*AI\s*Builder|🇨🇳\s*A股(?:开盘前瞻|收盘复盘)|🇭🇰\s*港股(?:开盘前瞻|收盘复盘))",
            plain_no_b,
        ) and ((line.startswith("<b>") and line.endswith("</b>")) or line.startswith(("📋", "📊", "🌅", "🇨🇳", "🇭🇰"))):
            h1_text = _format_cn_hk_heading(plain_no_b) if is_cn_hk else plain_no_b
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": rich_text(h1_text)}
            })
            i += 1
            continue

        # HTML 风格板块标题（🚀/🔥/❄️/⚡/🔭/🎯/📰/📎/一、/二、/三、 → heading_2）
        _H2_PREFIXES = ("🚀", "🔥", "❄️", "⚡", "🔭", "🎯", "📰", "📎", "一、", "二、", "三、", "四、")
        if line.startswith("<b>") and line.endswith("</b>") and line.count("<b>") == 1 and any(plain_no_b.startswith(p) for p in _H2_PREFIXES):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": rich_text(plain_no_b)}
            })
            i += 1
            continue

        # 列表条目
        if line.startswith("- ") or line.startswith("• "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": rich_text(line[2:].strip())}
            })
            i += 1
            continue

        # 普通段落
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": rich_text(line)}
        })
        i += 1

    if pending_star_line:
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(pending_star_line)}})

    return blocks


def archive_to_notion(
    report_text: str,
    source: str,
    date_str: str | None = None,
    report_type: str = "日报",
    title_override: str | None = None,
    database_id: str = DEFAULT_DATABASE_ID,
) -> tuple[bool, str]:
    """
    将成稿归档上传到 Notion 数据库。
    返回 (成功标志, 页面URL或错误信息)
    """
    api_key = get_notion_api_key()
    if not api_key:
        return False, "未找到有效的 NOTION_ARCHIVE_API_KEY（请检查 bots/shared/.env）"

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # 计算周次 (例如 2026-W46)
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    year, week, _ = dt.isocalendar()
    week_str = f"{year}-W{week:02d}"

    # 自动推导标题与图标
    icon_map = {
        "🐙 GitHub & HN": ("🐙", f"[GitHub & HN] {date_str} 今日早报"),
        "🗽 美股与加密": ("🗽", f"[美股收盘] {date_str} 美股与加密行情"),
        "📈 A股与港股": ("📈", f"[A股与港股] {date_str} 决策复盘"),
        "🤖 AI 产业日报": ("🤖", f"[AI 产业日报] {date_str} 行业观察"),
        "🐦 X 热点播报": ("🐦", f"[X 热点播报] {date_str} 圈内动态"),
        "🛠️ AI Builder": ("🛠️", f"[AI Builder] {date_str} 开发者动态"),
    }

    icon, default_title = icon_map.get(source, ("📑", f"[{source}] {date_str} 日报"))
    if report_type == "周盘点":
        default_title = default_title.replace("今日早报", "本周趋势榜").replace("日报", "周盘点")
    title = title_override or default_title

    summary = extract_summary(report_text, source=source)
    blocks = convert_to_blocks(report_text, source=source)

    # 构造请求体 (首次写入前 90 个 block，若超过在后序 append)
    first_chunk = blocks[:90]
    payload = {
        "parent": {"database_id": database_id},
        "icon": {"type": "emoji", "emoji": icon},
        "properties": {
            "标题": {"title": [{"text": {"content": title}}]},
            "日期": {"date": {"start": date_str}},
            "周次": {"select": {"name": week_str}},
            "信源": {"select": {"name": source}},
            "类型": {"select": {"name": report_type}},
            "30秒速览": {"rich_text": rich_text(summary)},
        },
        "children": first_chunk,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    try:
        # 使用 bot_utils.resolve_proxy 探测可用代理（兼容系统 Python LibreSSL 直连偶发 EOF 问题）
        shared_dir = str(Path(__file__).resolve().parent)
        if shared_dir not in sys.path:
            sys.path.insert(0, shared_dir)
        from bot_utils import resolve_proxy

        configured_proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "http://127.0.0.1:1082"
        resolved_proxy, _ = resolve_proxy(configured_proxy)

        def _make_session(proxy_url: str | None) -> requests.Session:
            s = requests.Session()
            s.trust_env = False
            s.proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else {}
            return s

        class _CurlResp:
            def __init__(self, status_code: int, text: str):
                self.status_code = status_code
                self.text = text

            def json(self):
                return json.loads(self.text)

        def _curl_request(method: str, url: str, body_dict: dict, timeout: int = 35):
            """LibreSSL 2.8.3 等系统 Python 对 Notion TLS 偶发 EOF 时，回退系统 /usr/bin/curl。"""
            # 优先使用已探测到的可用代理；若已选直连或代理临时失败，顺次尝试 1082 与直连
            candidates: list[str | None] = []
            for p in (resolved_proxy if resolved_proxy else None, configured_proxy, "http://127.0.0.1:1082", None):
                if p == "":
                    p = None
                if p not in candidates:
                    candidates.append(p)

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tf:
                    json.dump(body_dict, tf, ensure_ascii=False)
                    tmp_path = tf.name

                last_exc = None
                for px in candidates:
                    cmd = ["/usr/bin/curl", "-sS", "--max-time", str(timeout)]
                    if px:
                        cmd += ["-x", px]
                    cmd += [
                        "-X", method, url,
                        "-H", f"Notion-Version: {NOTION_VERSION}",
                        "-H", "Content-Type: application/json",
                        "-K", "-",
                        "--data-binary", f"@{tmp_path}",
                        "-w", "\n%{http_code}",
                    ]
                    r = subprocess.run(
                        cmd,
                        input=f'header = "Authorization: Bearer {api_key}"\n',
                        text=True,
                        capture_output=True,
                    )
                    if r.returncode != 0:
                        last_exc = RuntimeError(f"curl exit {r.returncode}: {r.stderr.strip()}")
                        continue
                    body, _, code_str = r.stdout.rpartition("\n")
                    try:
                        status_code = int(code_str.strip())
                    except ValueError:
                        last_exc = RuntimeError(f"curl bad status output: {r.stdout[-120:]}")
                        continue
                    return _CurlResp(status_code, body)
                raise last_exc or RuntimeError("curl fallback failed")
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        session = _make_session(resolved_proxy if resolved_proxy else None)
        prefer_curl = False

        def _req_with_fallback(method: str, url: str, **kwargs):
            nonlocal session, prefer_curl
            body_dict = kwargs.get("json")
            if prefer_curl and body_dict is not None:
                return _curl_request(method, url, body_dict, timeout=int(kwargs.get("timeout", 30)))
            try:
                return session.request(method, url, **kwargs)
            except requests.RequestException:
                # 先尝试 requests 切换直连/1082；若仍因 LibreSSL 2.8.3 TLS EOF 失败，永久切至系统 curl
                try:
                    alt = None if session.proxies else "http://127.0.0.1:1082"
                    session = _make_session(alt)
                    return session.request(method, url, **kwargs)
                except requests.RequestException:
                    if body_dict is not None and os.path.exists("/usr/bin/curl"):
                        prefer_curl = True
                        return _curl_request(method, url, body_dict, timeout=int(kwargs.get("timeout", 30)))
                    raise

        last_err = None
        resp = None
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

        if resp is None:
            return False, f"Notion 同步异常（重试3次均失败）: {last_err}"

        if resp.status_code >= 400:
            return False, f"Notion API HTTP {resp.status_code}: {resp.text}"

        data = resp.json()
        page_id = data.get("id")
        page_url = data.get("url", f"https://notion.so/{page_id.replace('-', '')}")

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
    except Exception as e:
        return False, f"Notion 同步异常: {str(e)}"


def main():
    parser = argparse.ArgumentParser(description="同步 Bot 稿件到 Notion 数据库")
    parser.add_argument("--source", required=True, help="信源名称，如 '🐙 GitHub & HN', '🗽 美股与加密' 等")
    parser.add_argument("--draft", required=True, help="稿件文本路径")
    parser.add_argument("--date", default=None, help="日期 YYYY-MM-DD，缺省为当天")
    parser.add_argument("--type", default="日报", choices=["日报", "周盘点", "开盘前瞻", "收盘复盘"], help="类型")
    parser.add_argument("--title", default=None, help="自定义标题")
    args = parser.parse_args()

    draft_path = Path(args.draft)
    if not draft_path.exists():
        print(f"❌ 稿件文件不存在: {draft_path}", file=sys.stderr)
        sys.exit(1)

    text = draft_path.read_text(encoding="utf-8").strip()
    if not text:
        print("❌ 稿件为空", file=sys.stderr)
        sys.exit(1)

    ok, res = archive_to_notion(
        report_text=text,
        source=args.source,
        date_str=args.date,
        report_type=args.type,
        title_override=args.title,
    )
    if ok:
        print(f"✅ Notion 归档成功: {res}")
        sys.exit(0)
    else:
        print(f"⚠️ Notion 归档未完成: {res}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
