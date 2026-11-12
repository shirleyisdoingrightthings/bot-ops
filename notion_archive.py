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
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# 常量定义
DEFAULT_DATABASE_ID = "e072f4c04bbf467793879e7dce4e4373"
NOTION_VERSION = "2022-06-28"
TEXT_LIMIT = 2000

# 从 youtube-to-blog 或环境变量获取 API KEY
def get_notion_api_key() -> str:
    key = os.getenv("NOTION_API_KEY", "")
    if key:
        return key
    env_path = Path("/Users/jialiwu/.gemini/config/skills/youtube-to-blog/.env")
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("NOTION_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


# ───────────────────────────────────────────
# Markdown / HTML 解析为 Notion Blocks
# ───────────────────────────────────────────

INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<bold>\*\*.+?\*\*)"
    r"|(?P<html_bold><b>.+?</b>)"
    r"|(?P<link>\[[^\]\n]+\]\([^()\s]+\))"
    r"|(?P<html_link><a\s+href=[\"'](?P<href>[^\"']+)[\"']>(?P<anchor>.*?)</a>)"
)

def _text_items(content: str, *, bold: bool = False, code: bool = False, link: str | None = None) -> list:
    items = []
    chunks = [content[i : i + TEXT_LIMIT] for i in range(0, len(content), TEXT_LIMIT)] or [content]
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

def rich_text(text: str) -> list:
    """把行内 Markdown 与受控 HTML 转换为 Notion rich_text"""
    parts = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            parts += _text_items(text[pos : m.start()])
        kind = m.lastgroup
        raw = m.group()
        if kind == "code":
            parts += _text_items(raw[1:-1], code=True)
        elif kind == "bold":
            parts += _text_items(raw[2:-2], bold=True)
        elif kind == "html_bold":
            inner = raw[3:-4]
            parts += _text_items(inner, bold=True)
        elif kind == "link":
            match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", raw)
            if match:
                label, url = match.groups()
                parts += _text_items(label, link=url)
        elif kind == "html_link":
            href = m.group("href")
            anchor = m.group("anchor")
            # 剥离内部标签
            clean_anchor = re.sub(r"<[^>]+>", "", anchor)
            parts += _text_items(clean_anchor or href, link=href)
        pos = m.end()
    if pos < len(text):
        parts += _text_items(text[pos:])
    return parts or _text_items(text)


def extract_summary(text: str) -> str:
    """从稿件中抽取 30 秒速览或核心要点"""
    # 匹配 30秒速览 区块
    m = re.search(r"(?:⚡\s*30秒速览|30秒速览)[\s\S]*?(?=\n\s*(?:[#🚀🔥📈🗽🤖🐦🛠️]|---)|\Z)", text)
    if m:
        summary_block = m.group().strip()
        lines = [line.strip() for line in summary_block.splitlines() if line.strip()]
        # 过滤掉标题行
        content_lines = [l.lstrip("-*•> ").strip() for l in lines if not re.search(r"30秒速览", l)]
        if content_lines:
            combined = "；".join(content_lines)
            return combined[:500]
    # 兜底：取前 300 字符纯文本
    clean = re.sub(r"<[^>]+>", "", text).strip()
    return clean[:300].replace("\n", " ")


def convert_to_blocks(content: str) -> list[dict]:
    """将稿件转换为 Notion Blocks 结构"""
    blocks = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue

        # 分割线
        if line.startswith("---") or line.startswith("━━━"):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # 标题处理
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
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": rich_text(line[2:].strip())}
            })
            i += 1
            continue

        # HTML 风格标题如 <b>🚀 一、...</b>
        if (line.startswith("<b>🚀") or line.startswith("<b>🔥") or line.startswith("<b>一、") or line.startswith("<b>二、") or line.startswith("<b>三、")) and line.endswith("</b>"):
            clean_title = re.sub(r"</?b>", "", line)
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": rich_text(clean_title)}
            })
            i += 1
            continue

        # 30 秒速览 Callout 灰框
        if "30秒速览" in line or line.startswith("> ⚡") or line.startswith("<b>⚡ 30秒速览</b>"):
            quote_lines = [line]
            i += 1
            while i < len(lines) and (lines[i].strip().startswith("-") or lines[i].strip().startswith("•") or lines[i].strip().startswith(">") or not lines[i].strip()):
                if lines[i].strip():
                    quote_lines.append(lines[i].strip())
                i += 1
            full_quote = "\n\n".join(quote_lines)
            blocks.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": rich_text(full_quote),
                    "icon": {"type": "emoji", "emoji": "⚡"},
                    "color": "gray_background"
                }
            })
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
        return False, "未找到有效的 NOTION_API_KEY"

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

    summary = extract_summary(report_text)
    blocks = convert_to_blocks(report_text)

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
        req = urllib.request.Request(
            "https://api.notion.com/v1/pages",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            page_id = data.get("id")
            page_url = data.get("url", f"https://notion.so/{page_id.replace('-', '')}")

        # 追加剩余 blocks
        if len(blocks) > 90 and page_id:
            for j in range(90, len(blocks), 90):
                chunk = blocks[j : j + 90]
                append_req = urllib.request.Request(
                    f"https://api.notion.com/v1/blocks/{page_id}/children",
                    data=json.dumps({"children": chunk}, ensure_ascii=False).encode("utf-8"),
                    headers=headers,
                    method="PATCH",
                )
                with urllib.request.urlopen(append_req, timeout=30):
                    time.sleep(0.3)

        return True, page_url
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="ignore")
        return False, f"Notion API HTTP {e.code}: {err_msg}"
    except Exception as e:
        return False, f"Notion 同步异常: {str(e)}"


def main():
    parser = argparse.ArgumentParser(description="同步 Bot 稿件到 Notion 数据库")
    parser.add_argument("--source", required=True, help="信源名称，如 '🐙 GitHub & HN', '🗽 美股与加密' 等")
    parser.add_argument("--draft", required=True, help="稿件文本路径")
    parser.add_argument("--date", default=None, help="日期 YYYY-MM-DD，缺省为当天")
    parser.add_argument("--type", default="日报", choices=["日报", "周盘点"], help="类型")
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
