#!/usr/bin/env python3
"""
notion_reconcile.py — Notion 归档补同步与干跑审计 CLI。

依赖 Plan 006 的幂等 upsert（按 日期 + 信源 + 类型 查重并原地更新）以及各 bot 落盘在
logs/archive/ 下的日期文稿：
- 默认仅回放 run.jsonl 中记录了 notion_ok=false 的失败场次（等价 --only-failed）
- 传入 --force 可强制幂等重推目标日期窗内的所有本地归档文稿
- 传入 --dry-run 只打印计划执行的映射参数，绝不请求 Notion API
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parent
BOTS_ROOT = SHARED_DIR.parent
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from bot_utils import extract_report_date  # noqa: E402
from notion_archive import archive_to_notion  # noqa: E402

BOT_SPECS: dict[str, dict[str, str]] = {
    "github-hn-bot": {"source": "🐙 GitHub & HN"},
    "us stock bot": {"source": "🗽 美股与加密"},
    "cn-hk-stock-bot": {"source": "📈 A股与港股"},
    "AI Daily News Bot": {"source": "🤖 AI 产业日报"},
    "x-hotspot-bot": {"source": "🐦 X 热点播报"},
    "ai-builder-bot": {"source": "🛠️ AI Builder"},
}


def load_jsonl_rows(jsonl_path: Path) -> list[dict]:
    if not jsonl_path.exists():
        return []
    rows: list[dict] = []
    for raw in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            continue
    return rows


def collect_failed_keys(rows: list[dict], target_dates: set[str]) -> set[tuple[str, str]]:
    """返回目标日期窗内最终状态仍为 notion_ok=False 的 (date_key, session) 集合。"""
    status_by_key: dict[tuple[str, str], bool] = {}
    for row in rows:
        if row.get("status") != "OK" or "notion_ok" not in row:
            continue
        ts_date = str(row.get("ts") or "")[:10]
        ndate = str(row.get("notion_date") or "")[:10]
        if ndate not in target_dates and ts_date not in target_dates:
            continue
        sess = str(row.get("session") or "")
        key = (ndate or ts_date, sess)
        status_by_key[key] = bool(row.get("notion_ok"))
    return {k for k, ok in status_by_key.items() if not ok}


def _resolve_github_hn_report_type(date_str: str, text: str, rows: list[dict]) -> str:
    for row in reversed(rows):
        if row.get("status") != "OK":
            continue
        row_date = str(row.get("notion_date") or str(row.get("ts") or "")[:10])
        if row_date == date_str and row.get("since") in ("daily", "weekly"):
            return "周盘点" if row["since"] == "weekly" else "日报"
    if any(tok in text for tok in ("本周趋势榜", "GitHub Weekly", "since=weekly", "持续霸榜")):
        return "周盘点"
    try:
        if datetime.strptime(date_str, "%Y-%m-%d").weekday() == 6:
            return "周盘点"
    except ValueError:
        pass
    return "日报"


def resolve_archive_task(bot_name: str, archive_path: Path, jsonl_rows: list[dict]) -> dict | None:
    """解析单个本地归档文件应传给 archive_to_notion 的全部参数。"""
    spec = BOT_SPECS.get(bot_name)
    if not spec:
        return None
    source = spec["source"]
    stem = archive_path.stem
    text = archive_path.read_text(encoding="utf-8").strip()
    if not text:
        return None

    session = ""
    title_override: str | None = None
    report_type = "日报"

    if bot_name == "cn-hk-stock-bot":
        m_cn = re.match(r"^(\d{4}-\d{2}-\d{2})_(premarket|midday|close)$", stem)
        if m_cn:
            date_str, session = m_cn.group(1), m_cn.group(2)
            report_type = {"premarket": "开盘前瞻", "midday": "午间复盘", "close": "收盘复盘"}[session]
        else:
            m_d = re.match(r"^(\d{4}-\d{2}-\d{2})$", stem)
            date_str = m_d.group(1) if m_d else (extract_report_date(text) or "")
            if not date_str:
                return None
            if "开盘前瞻" in text:
                report_type, session = "开盘前瞻", "premarket"
            elif "早盘总结" in text or "午间复盘" in text:
                report_type, session = "午间复盘", "midday"
            else:
                report_type, session = "收盘复盘", "close"
        title_override = None
    else:
        m_d = re.match(r"^(\d{4}-\d{2}-\d{2})$", stem)
        date_str = m_d.group(1) if m_d else (extract_report_date(text) or "")
        if not date_str:
            return None
        if bot_name == "github-hn-bot":
            report_type = _resolve_github_hn_report_type(date_str, text, jsonl_rows)

    return {
        "bot": bot_name,
        "source": source,
        "date_str": date_str,
        "session": session,
        "report_type": report_type,
        "title_override": title_override,
        "archive_path": archive_path,
        "text": text,
    }


def _next_day_iso(date_str: str) -> str:
    try:
        return (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def collect_reconcile_tasks(
    *,
    bots_root: Path = BOTS_ROOT,
    target_dates: set[str],
    bot_filter: str | None = None,
    only_failed: bool = True,
) -> list[dict]:
    """扫描各 bot logs/archive/ 与 logs/run.jsonl，生成待补同步任务列表。"""
    tasks: list[dict] = []
    bot_names = [bot_filter] if bot_filter else list(BOT_SPECS.keys())

    for bot_name in bot_names:
        if bot_name not in BOT_SPECS:
            continue
        logs_dir = bots_root / bot_name / "logs"
        archive_dir = logs_dir / "archive"
        if not archive_dir.is_dir():
            continue
        rows = load_jsonl_rows(logs_dir / "run.jsonl")
        failed_keys = collect_failed_keys(rows, target_dates) if only_failed else set()

        for path in sorted(archive_dir.glob("*.txt")):
            task = resolve_archive_task(bot_name, path, rows)
            if not task:
                continue
            d = task["date_str"]
            s = task["session"]
            if only_failed:
                next_d = _next_day_iso(d) if bot_name == "us stock bot" else ""
                is_failed = (d, s) in failed_keys or (bool(next_d) and (next_d, "") in failed_keys)
                if not is_failed:
                    continue
            else:
                if d not in target_dates:
                    continue
            tasks.append(task)
    return tasks


def build_target_dates(date_str: str | None, since_days: int, *, today: datetime | None = None) -> set[str]:
    if date_str:
        return {datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")}
    base = today or datetime.now()
    days = max(1, int(since_days))
    return {(base - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)}


def run_reconcile(
    *,
    bots_root: Path = BOTS_ROOT,
    date_str: str | None = None,
    since_days: int = 1,
    bot_filter: str | None = None,
    only_failed: bool = True,
    dry_run: bool = False,
) -> int:
    target_dates = build_target_dates(date_str, since_days)
    tasks = collect_reconcile_tasks(
        bots_root=bots_root,
        target_dates=target_dates,
        bot_filter=bot_filter,
        only_failed=only_failed,
    )
    if not tasks:
        mode = "only-failed" if only_failed else "force"
        print(f"没有待补同步的归档任务（mode={mode}, dates={sorted(target_dates)}）。")
        return 0

    failures = 0
    for t in tasks:
        if dry_run:
            print(
                f"[DRY-RUN] source={t['source']} date={t['date_str']} "
                f"type={t['report_type']} title={t['title_override'] or '(default)'} "
                f"path={t['archive_path']}"
            )
            continue
        ok, res = archive_to_notion(
            t["text"],
            t["source"],
            date_str=t["date_str"],
            report_type=t["report_type"],
            title_override=t["title_override"],
        )
        if ok:
            print(f"[OK] {t['source']} {t['date_str']} ({t['report_type']}) -> {res}")
        else:
            failures += 1
            print(f"[FAIL] {t['source']} {t['date_str']} ({t['report_type']}) -> {res}", file=sys.stderr)

    print(f"汇总：共 {len(tasks)} 条任务，{'dry-run 预览完成' if dry_run else f'成功 {len(tasks) - failures} / 失败 {failures}'}。")
    return 1 if failures > 0 else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Notion 归档补同步与干跑审计 CLI")
    parser.add_argument("--date", default=None, help="指定单一业务日期 YYYY-MM-DD")
    parser.add_argument("--since-days", type=int, default=1, help="回看最近 N 天（含今天，默认 1）")
    parser.add_argument("--bot", choices=sorted(BOT_SPECS.keys()), default=None, help="仅扫描指定 bot 目录名")
    parser.add_argument("--only-failed", action="store_true", help="仅补推 run.jsonl 记为 notion_ok=false 的场次（未传 --force 时默认生效）")
    parser.add_argument("--force", action="store_true", help="忽略 run.jsonl 状态，强制重推目标日期窗内的所有本地归档")
    parser.add_argument("--dry-run", action="store_true", help="仅打印计划执行的归档映射，不调用 Notion API")
    args = parser.parse_args()

    try:
        return run_reconcile(
            date_str=args.date,
            since_days=args.since_days,
            bot_filter=args.bot,
            only_failed=not args.force,
            dry_run=args.dry_run,
        )
    except ValueError as exc:
        print(f"参数错误: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
