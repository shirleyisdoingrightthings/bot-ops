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
    r"|(?P<bold>\*\*.+?\*\*)"
    r"|(?P<html_bold><b>.*?</b>)"
    r"|(?P<link>\[[^\]\n]+\]\([^()\s]+\))"
    r"|(?P<html_link><a\s+[^>]*?href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<anchor>.*?)</a>)",
    re.IGNORECASE,
)

_RESIDUAL_TAG_RE = re.compile(r"</?(?:b|strong|i|em|code|a)(?:\s+[^<>]*)?>", re.I)


def _clean_text(s: str) -> str:
    return html.unescape(_RESIDUAL_TAG_RE.sub("", s or ""))

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
    # 预处理嵌套 <b>1. <a href="...">Title</a></b> → <b>1.</b> <a href="..."><b>Title</b></a>
    text = re.sub(
        r"<b>(\d+\.)\s*(<a\s+[^>]+>)(?:<b>)?(.*?)(?:</b>)?</a>\s*</b>",
        r"<b>\1</b> \2<b>\3</b></a>",
        text,
        flags=re.I,
    )
    parts = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            parts += _text_items(_clean_text(text[pos : m.start()]))
        kind = m.lastgroup
        raw = m.group()
        if kind == "code":
            parts += _text_items(html.unescape(raw[1:-1]), code=True)
        elif kind == "bold":
            parts += _text_items(_clean_text(raw[2:-2]), bold=True)
        elif kind == "html_bold":
            inner = raw[3:-4]
            parts += _text_items(_clean_text(inner), bold=True)
        elif kind == "link":
            match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", raw)
            if match:
                label, url = match.groups()
                parts += _text_items(html.unescape(label), link=url)
        elif kind == "html_link":
            href = html.unescape(m.group("href"))
            anchor = m.group("anchor")
            is_bold = bool(re.search(r"<\s*(?:b|strong)\b", anchor, re.I))
            clean_anchor = html.unescape(re.sub(r"<[^>]+>", "", anchor)).strip()
            parts += _text_items(clean_anchor or href, bold=is_bold, link=href)
        pos = m.end()
    if pos < len(text):
        parts += _text_items(_clean_text(text[pos:]))
    return parts or _text_items(_clean_text(text))


def extract_summary(text: str) -> str:
    """从稿件中抽取 30 秒速览或核心要点"""
    # 匹配 30秒速览 区块（兼容带 <b> 包裹的章节标题，遇到 ⭐ 星级条目或大板块 emoji / 分割线即止）
    m = re.search(
        r"(?:⚡\s*30秒速览|30秒速览)[\s\S]*?(?=\n\s*(?:<(?:b|strong)\b[^>]*>\s*)*(?:[#🚀🔥❄️⚡🔭🎯📰📎📈🗽🤖🐦🛠️⭐]|---)|\Z)",
        text,
        re.IGNORECASE,
    )
    if m:
        summary_block = m.group().strip()
        lines = [line.strip() for line in summary_block.splitlines() if line.strip()]
        # 过滤掉标题行，剥离残留 HTML 标签后截断，避免 [:500] 截断半个 <a href> 标签
        content_lines = [
            html.unescape(re.sub(r"<[^>]+>", "", l)).lstrip("-*•> ").strip()
            for l in lines
            if not re.search(r"30秒速览", l)
        ]
        content_lines = [l for l in content_lines if l]
        if content_lines:
            combined = "；".join(content_lines)
            return combined[:500]
    # 兜底：取前 300 字符纯文本
    clean = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
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

        # 30 秒速览 Callout 灰框（须先于 heading 判定）
        plain_no_b = re.sub(r"</?b>", "", line).strip()
        if "30秒速览" in plain_no_b or line.startswith("> ⚡"):
            quote_lines = [line]
            i += 1
            while i < len(lines) and (lines[i].strip().startswith("-") or lines[i].strip().startswith("•") or lines[i].strip().startswith(">") or not lines[i].strip()):
                if lines[i].strip():
                    quote_lines.append(lines[i].strip())
                i += 1
            while quote_lines and not quote_lines[-1]:
                quote_lines.pop()
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

        # HTML 顶层主标题（日报/早报/收盘复盘总标题 → heading_1）
        if re.match(
            r"^(?:🌅\s*)?(?:📊\s*美股收盘|📋\s*(?:AI\s*产业日报|美股要闻)|🐙\s*GitHub|🔥\s*X\s*热点|🛠️?\s*AI\s*Builder|🇨🇳\s*A股(?:开盘前瞻|收盘复盘)|🇭🇰\s*港股(?:开盘前瞻|收盘复盘))",
            plain_no_b,
        ) and (line.startswith("<b>") and line.endswith("</b>") or line.startswith("📋")):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": rich_text(plain_no_b)}
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
