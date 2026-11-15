#!/usr/bin/env python3
"""
全量检查、重建缺失归档并刷新 Notion 22 篇（或全库）页面脚本。
默认支持 `--dry-run`（仅校验并打印新版标题 / 导读 / 市场信号 / Blocks 统计，不写入）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

SHARED_DIR = Path(__file__).resolve().parent
BOTS_ROOT = SHARED_DIR.parent
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from bot_utils import resolve_proxy
import notion_archive as na


def _build_requester():
    api_key = na.get_notion_api_key()
    if not api_key:
        raise RuntimeError("未找到有效的 NOTION_ARCHIVE_API_KEY（请检查 bots/shared/.env）")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": na.NOTION_VERSION,
    }
    configured_proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "http://127.0.0.1:1082"
    resolved_proxy, _ = resolve_proxy(configured_proxy)

    sess = requests.Session()
    sess.trust_env = False
    if resolved_proxy:
        sess.proxies = {"http": resolved_proxy, "https": resolved_proxy}

    def _req(method: str, url: str, json_body: dict | None = None) -> dict:
        last_err = ""
        for attempt in range(4):
            try:
                if attempt < 2:
                    resp = sess.request(method, url, headers=headers, json=json_body, timeout=30)
                    status = resp.status_code
                    text = resp.text
                else:
                    cmd = ["curl", "-sS", "-m", "30", "-X", method, "-w", "\n__HTTP_CODE__:%{http_code}"]
                    if resolved_proxy:
                        cmd.extend(["-x", resolved_proxy])
                    for k, v in headers.items():
                        cmd.extend(["-H", f"{k}: {v}"])
                    if json_body is not None:
                        cmd.extend(["--data-raw", json.dumps(json_body, ensure_ascii=False)])
                    cmd.append(url)
                    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
                    if proc.returncode != 0:
                        raise RuntimeError(proc.stderr.strip() or f"curl rc={proc.returncode}")
                    out = proc.stdout
                    marker = "\n__HTTP_CODE__:"
                    pos = out.rfind(marker)
                    text = out[:pos]
                    status = int(out[pos + len(marker) :].strip())

                if status == 429 or status >= 500:
                    last_err = f"HTTP {status}: {text[:200]}"
                    time.sleep(min(2 ** attempt, 6))
                    continue
                if status >= 400:
                    raise RuntimeError(f"HTTP {status}: {text[:300]}")
                return json.loads(text)
            except Exception as e:
                last_err = str(e)
                if attempt < 3:
                    time.sleep(min(2 ** attempt, 6))
        raise RuntimeError(f"Notion 请求失败 ({method} {url}): {last_err}")

    return _req


def fetch_all_pages(_req, database_id: str) -> list[dict]:
    pages: list[dict] = []
    cursor: str | None = None
    while True:
        body: dict = {
            "page_size": 100,
            "sorts": [
                {"property": "日期", "direction": "descending"},
                {"timestamp": "last_edited_time", "direction": "descending"},
            ],
        }
        if cursor:
            body["start_cursor"] = cursor
        data = _req("POST", f"https://api.notion.com/v1/databases/{database_id}/query", body)
        pages.extend([p for p in (data.get("results") or []) if not p.get("archived")])
        if not data.get("has_more") or not data.get("next_cursor"):
            break
        cursor = data["next_cursor"]
        time.sleep(0.25)
    return pages


def fetch_block_tree(_req, block_id: str) -> list[dict]:
    items: list[dict] = []
    cursor: str | None = None
    while True:
        url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"
        data = _req("GET", url)
        results = data.get("results") or []
        for blk in results:
            if blk.get("has_children"):
                time.sleep(0.2)
                blk["_children"] = fetch_block_tree(_req, blk["id"])
            items.append(blk)
        if not data.get("has_more") or not data.get("next_cursor"):
            break
        cursor = data["next_cursor"]
        time.sleep(0.2)
    return items


def _plain_prop(prop: dict | None) -> str:
    if not prop:
        return ""
    ptype = prop.get("type")
    if ptype == "title":
        return "".join(t.get("plain_text", "") for t in (prop.get("title") or []))
    if ptype == "rich_text":
        return "".join(t.get("plain_text", "") for t in (prop.get("rich_text") or []))
    if ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    if ptype == "date":
        dt = prop.get("date")
        return dt.get("start", "") if dt else ""
    return ""


def _rt_to_html(rt_list: list[dict]) -> str:
    out: list[str] = []
    for item in (rt_list or []):
        txt = item.get("plain_text") or (item.get("text") or {}).get("content") or ""
        if not txt:
            continue
        ann = item.get("annotations") or {}
        href = item.get("href") or ((item.get("text") or {}).get("link") or {}).get("url")
        if ann.get("code"):
            seg = f"`{txt}`"
        else:
            seg = txt
            if ann.get("bold"):
                seg = f"<b>{seg}</b>"
            if ann.get("italic"):
                seg = f"<i>{seg}</i>"
        if href:
            seg = f'<a href="{href}">{seg}</a>'
        out.append(seg)
    merged = "".join(out).strip()
    # 合并相邻同类标签，避免 <b>A</b><b>B</b> 噪音
    merged = re.sub(r"</b><b>", "", merged)
    merged = re.sub(r"</i><i>", "", merged)
    return re.sub(r"(\d+)\\\.", r"\1.", merged)


def blocks_to_draft(blocks: list[dict]) -> str:
    """将 Notion Block 树忠实逆向还原为结构化稿件文本（保留超链接、加粗与列表结构）"""
    lines: list[str] = []
    num_counter = 0

    for blk in blocks:
        btype = blk.get("type", "")
        inner = blk.get(btype) or {}
        if btype != "numbered_list_item":
            num_counter = 0

        if btype == "heading_1":
            lines.append(f"# {_rt_to_html(inner.get('rich_text') or [])}")
        elif btype == "heading_2":
            lines.append(f"## {_rt_to_html(inner.get('rich_text') or [])}")
        elif btype == "heading_3":
            lines.append(f"### {_rt_to_html(inner.get('rich_text') or [])}")
        elif btype == "paragraph":
            txt = _rt_to_html(inner.get("rich_text") or [])
            if txt:
                lines.append(txt)
        elif btype == "bulleted_list_item":
            lines.append(f"- {_rt_to_html(inner.get('rich_text') or [])}")
        elif btype == "numbered_list_item":
            num_counter += 1
            lines.append(f"{num_counter}. {_rt_to_html(inner.get('rich_text') or [])}")
        elif btype == "divider":
            lines.append("---")
        elif btype == "callout":
            title_txt = _rt_to_html(inner.get("rich_text") or [])
            plain_t = na._strip_tags_plain(title_txt)
            # 若已是升级后的顶部 30秒速览 Callout，重新还原为 ⚡ 30秒速览 段落以保证完全幂等
            if "30秒速览" in plain_t:
                lines.append(title_txt)
                sub = blocks_to_draft(blk.get("_children") or [])
                if sub:
                    lines.append(sub)
            elif plain_t.startswith("🎯"):
                lines.append(f"## {title_txt}")
                sub = blocks_to_draft(blk.get("_children") or [])
                if sub:
                    lines.append(sub)
            else:
                lines.append(title_txt)
                sub = blocks_to_draft(blk.get("_children") or [])
                if sub:
                    lines.append(sub)
        elif btype == "toggle":
            title_txt = _rt_to_html(inner.get("rich_text") or [])
            # 去掉自动追加的计数尾缀以防二次执行叠加
            clean_toggle_title = re.sub(r"（本周反复上榜\s*·\s*共\s*\d+\s*项，点击展开）", "", title_txt).strip()
            lines.append(f"## {clean_toggle_title}")
            sub = blocks_to_draft(blk.get("_children") or [])
            if sub:
                lines.append(sub)
        elif btype == "table":
            rows = blk.get("_children") or []
            for idx, r in enumerate(rows):
                cells = (r.get("table_row") or {}).get("cells") or []
                if len(cells) >= 2:
                    c1 = na._strip_tags_plain(_rt_to_html(cells[0]))
                    c2 = _rt_to_html(cells[1])
                    if idx == 0 and c1 == "指标维度":
                        continue
                    if c1 and c2:
                        lines.append(f"{c1}：{c2}")

    return "\n\n".join(l for l in lines if l is not None).strip()


def _date_variants(date_str: str) -> tuple[str, str]:
    y, m, d = date_str.split("-")
    return date_str, f"{int(y)}年{int(m)}月{int(d)}日"


def resolve_local_draft(source: str, date_str: str, report_type: str) -> tuple[str | None, Path | None]:
    """匹配本地权威草稿或归档原文；返回 (text, archive_target_path)"""
    iso_d, cn_d = _date_variants(date_str)

    if "GitHub & HN" in source:
        arch = BOTS_ROOT / "github-hn-bot/logs/archive" / f"{date_str}.txt"
        if arch.exists():
            return arch.read_text(encoding="utf-8").strip(), arch
        return None, arch

    if "AI 产业日报" in source:
        arch = BOTS_ROOT / "AI Daily News Bot/logs/archive" / f"{date_str}.txt"
        if arch.exists():
            return arch.read_text(encoding="utf-8").strip(), arch
        return None, arch

    if "X 热点" in source:
        arch = BOTS_ROOT / "x-hotspot-bot/logs/archive" / f"{date_str}.txt"
        if arch.exists():
            return arch.read_text(encoding="utf-8").strip(), arch
        return None, arch

    if "AI Builder" in source:
        arch = BOTS_ROOT / "ai-builder-bot/logs/archive" / f"{date_str}.txt"
        if arch.exists():
            return arch.read_text(encoding="utf-8").strip(), arch
        return None, arch

    if "美股" in source:
        arch = BOTS_ROOT / "us stock bot/logs/archive" / f"{date_str}.txt"
        if arch.exists():
            return arch.read_text(encoding="utf-8").strip(), arch
        mkt_p = BOTS_ROOT / "us stock bot/logs/report_market.txt"
        news_p = BOTS_ROOT / "us stock bot/logs/report_news.txt"
        if mkt_p.exists() and news_p.exists():
            mkt = mkt_p.read_text(encoding="utf-8").strip()
            news = news_p.read_text(encoding="utf-8").strip()
            if (iso_d in mkt or cn_d in mkt) and (iso_d in news or cn_d in news):
                return f"{mkt}\n\n---\n\n{news}", arch
        return None, arch

    if "A股与港股" in source:
        suffix = "premarket" if report_type == "开盘前瞻" else "close"
        arch = BOTS_ROOT / "cn-hk-stock-bot/logs/archive" / f"{date_str}_{suffix}.txt"
        if arch.exists():
            return arch.read_text(encoding="utf-8").strip(), arch
        cn_p = BOTS_ROOT / "cn-hk-stock-bot/logs/report_cn.txt"
        hk_p = BOTS_ROOT / "cn-hk-stock-bot/logs/report_hk.txt"
        if cn_p.exists() and hk_p.exists():
            cn_txt = cn_p.read_text(encoding="utf-8").strip()
            hk_txt = hk_p.read_text(encoding="utf-8").strip()
            expected_kw = "开盘前瞻" if report_type == "开盘前瞻" else "收盘复盘"
            if expected_kw in cn_txt and (iso_d in cn_txt or cn_d in cn_txt):
                return f"{cn_txt}\n\n---\n\n{hk_txt}", arch
        return None, arch

    return None, None


def recover_stripped_overview(
    body_draft: str,
    prop_summary: str,
    source: str,
    date_str: str,
) -> str:
    """若历史 Notion 页面的正文曾剥离 `30秒速览` 或顶部导语，从现有 `30秒速览` 属性中忠实还原"""
    summary = (prop_summary or "").strip()
    if not summary:
        return body_draft

    if "AI 产业日报" in source and "30秒速览" not in body_draft:
        clauses = [c.strip().rstrip("。") for c in summary.split("；") if c.strip()]
        if clauses:
            bullets = "\n".join(f"- {c}" for c in clauses)
            return f"📋 AI 产业日报 · {date_str}\n\n⚡ 30秒速览：\n{bullets}\n\n---\n\n{body_draft}"

    if ("X 热点" in source or "AI Builder" in source):
        first_non_empty = next((l.strip() for l in body_draft.splitlines() if l.strip()), "")
        if re.match(r"^(?:#{1,3}\s*)?(?:<b>)?\d+\.", first_non_empty):
            overview = summary.split("本期焦点：", 1)[0].strip().rstrip("；;。")
            overview = re.sub(
                r"^这批(?:推文|动态)(?:集中)?(?:发布于|来自|涵盖)\s+[^\n，。]*?(?:\s*[（(][^）)]*[）)])?\s*(?:[，,]|(?<!\d)[：:](?!\d))\s*",
                "",
                overview,
            ).strip()
            if overview:
                prefix = "🔥 X 热点" if "X 热点" in source else "🛠️ AI Builder 日报"
                return f"{prefix} · {date_str}\n\n{overview}\n\n{body_draft}"

    if "美股" in source and "30秒速览" not in body_draft:
        clauses = [c.strip().rstrip("。") for c in summary.split("；") if c.strip()]
        news_clauses = [c for c in clauses if not c.startswith("【美股盘面】")]
        if news_clauses:
            bullets = "\n".join(f"- {c}" for c in news_clauses)
            m = re.search(r"^(?:#{1,3}\s*)?(?:<b>)?📋\s*美股要闻[^\n]*$", body_draft, re.M)
            if m:
                pos = m.end()
                return f"{body_draft[:pos]}\n\n⚡ 30秒速览：\n{bullets}\n{body_draft[pos:]}"

    return body_draft


def main() -> int:
    parser = argparse.ArgumentParser(description="全量检查并刷新 Notion 22 篇页面结构与属性")
    parser.add_argument("--dry-run", action="store_true", help="只检查并打印预览结果，不写入 Notion 或本地磁盘")
    parser.add_argument("--save-missing-archive", action="store_true", help="将重建的历史页面原文补写至缺失的 logs/archive/（绝不覆盖已有文件）")
    parser.add_argument("--only-source", default=None, help="只处理指定信源子串（如 'AI Builder'）")
    args = parser.parse_args()

    req = _build_requester()
    pages = fetch_all_pages(req, na.DEFAULT_DATABASE_ID)
    print(f"🔎 共读取到 Notion 数据库未归档页面：{len(pages)} 篇")

    ok_count = 0
    fail_list: list[str] = []

    for idx, page in enumerate(pages, 1):
        props = page.get("properties") or {}
        source = _plain_prop(props.get("信源"))
        date_str = _plain_prop(props.get("日期"))
        report_type = _plain_prop(props.get("类型")) or "日报"
        old_title = _plain_prop(props.get("标题"))
        old_summary = _plain_prop(props.get("30秒速览"))
        page_id = page.get("id", "")

        if args.only_source and args.only_source not in source:
            continue

        draft, arch_path = resolve_local_draft(source, date_str, report_type)
        origin = "local"
        if draft is None:
            raw_blocks = fetch_block_tree(req, page_id)
            reconstructed = blocks_to_draft(raw_blocks)
            draft = recover_stripped_overview(reconstructed, old_summary, source, date_str)
            origin = "notion"

        new_title = na.build_clean_title(source, date_str, report_type=report_type)
        new_summary = na.extract_summary(draft, source=source)
        new_one_liner = na.extract_one_liner(new_summary, report_text=draft, source=source)
        new_signal = na.extract_market_signal(draft, source=source)
        new_blocks = na.convert_to_blocks(draft, source=source, summary_override=new_summary)
        chunks = na._chunk_blocks_by_count(new_blocks, max_blocks=80)
        total_rec_blocks = sum(na._count_blocks_recursive(b) for b in new_blocks)

        sig_disp = new_signal or "-"
        print(
            f"[{idx:02d}] {date_str} | {source} ({report_type}) [{origin}] "
            f"| 块={len(new_blocks)}({total_rec_blocks}rec/{len(chunks)}chunk) "
            f"| 信号={sig_disp} | 标题={new_title}"
        )
        print(f"     导读: {new_one_liner}")
        print(f"     速览: {new_summary[:120]}{'...' if len(new_summary) > 120 else ''}")

        if args.dry_run:
            ok_count += 1
            continue

        if args.save_missing_archive and arch_path and not arch_path.exists() and draft:
            arch_path.parent.mkdir(parents=True, exist_ok=True)
            arch_path.write_text(draft + "\n", encoding="utf-8")
            print(f"     💾 已补齐历史归档: {arch_path}")

        ok, res = na.archive_to_notion(
            report_text=draft,
            source=source,
            date_str=date_str,
            report_type=report_type,
        )
        if ok:
            ok_count += 1
            print(f"     ✅ 更新成功: {res}")
        else:
            fail_list.append(f"{date_str} {source} ({report_type}): {res}")
            print(f"     ❌ 更新失败: {res}", file=sys.stderr)
        time.sleep(0.4)

    print(f"\n📊 汇总：成功 {ok_count} 篇，失败 {len(fail_list)} 篇")
    if fail_list:
        for f in fail_list:
            print(f"  - {f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
