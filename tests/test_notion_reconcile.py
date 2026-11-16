"""Offline tests for Plan 007: archive_and_sync_notion, health_check_base.sh, and notion_reconcile.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

SHARED_DIR = Path(__file__).resolve().parent.parent
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import bot_utils  # noqa: E402
import notion_archive  # noqa: E402
import notion_reconcile  # noqa: E402


class TestArchiveAndSyncNotion(unittest.TestCase):
    def test_writes_archive_file_and_returns_status_dicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            adir = Path(tmp) / "archive"
            with patch.object(notion_archive, "archive_to_notion", return_value=(True, "https://notion.so/ok1")):
                res_ok = bot_utils.archive_and_sync_notion(
                    "正文内容",
                    "🤖 AI 产业日报",
                    date_str="2026-11-14",
                    archive_dir=adir,
                    archive_filename="2026-11-14.txt",
                )
            self.assertEqual(
                res_ok,
                {"notion_ok": True, "notion_url": "https://notion.so/ok1", "notion_date": "2026-11-14"},
            )
            self.assertEqual((adir / "2026-11-14.txt").read_text(encoding="utf-8"), "正文内容")

            long_err = "E" * 260
            with patch.object(notion_archive, "archive_to_notion", return_value=(False, long_err)):
                res_fail = bot_utils.archive_and_sync_notion(
                    "失败重试稿",
                    "🤖 AI 产业日报",
                    date_str="2026-11-14",
                    archive_dir=adir,
                )
            self.assertFalse(res_fail["notion_ok"])
            self.assertEqual(res_fail["notion_url"], "")
            self.assertEqual(len(res_fail["notion_err"]), 200)

            with patch.object(notion_archive, "archive_to_notion", side_effect=RuntimeError("boom")):
                res_exc = bot_utils.archive_and_sync_notion(
                    "异常稿",
                    "🤖 AI 产业日报",
                    date_str="2026-11-14",
                )
            self.assertFalse(res_exc["notion_ok"])
            self.assertEqual(res_exc["notion_url"], "")
            self.assertIn("boom", res_exc["notion_err"])


class TestNotionReconcile(unittest.TestCase):
    def _seed_bot(self, root: Path, bot_name: str, archives: dict[str, str], jsonl_rows: list[dict]):
        logs_dir = root / bot_name / "logs"
        arch_dir = logs_dir / "archive"
        arch_dir.mkdir(parents=True, exist_ok=True)
        for fname, content in archives.items():
            (arch_dir / fname).write_text(content, encoding="utf-8")
        if jsonl_rows:
            (logs_dir / "run.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in jsonl_rows) + "\n",
                encoding="utf-8",
            )

    def test_parses_cn_hk_sessions_and_github_weekly_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_bot(
                root,
                "cn-hk-stock-bot",
                {
                    "2026-11-14_premarket.txt": "早盘正文",
                    "2026-11-14_close.txt": "收盘正文",
                },
                [
                    {
                        "ts": "2026-11-14 09:05",
                        "status": "OK",
                        "session": "premarket",
                        "notion_ok": False,
                        "notion_date": "2026-11-14",
                        "notion_err": "HTTP 500",
                    },
                    {
                        "ts": "2026-11-14 16:20",
                        "status": "OK",
                        "session": "close",
                        "notion_ok": True,
                        "notion_date": "2026-11-14",
                    },
                ],
            )
            self._seed_bot(
                root,
                "github-hn-bot",
                {"2026-11-14.txt": "日常榜正文", "2026-11-09.txt": "周榜"},
                [
                    {
                        "ts": "2026-11-14 09:35",
                        "status": "OK",
                        "since": "weekly",
                        "notion_ok": False,
                        "notion_date": "2026-11-14",
                    }
                ],
            )

            # --only-failed picks premarket (failed) and skips close (succeeded), plus github-hn failed weekly
            failed_tasks = notion_reconcile.collect_reconcile_tasks(
                bots_root=root, target_dates={"2026-11-14"}, only_failed=True
            )
            self.assertEqual(len(failed_tasks), 2)
            cn_task = [t for t in failed_tasks if t["bot"] == "cn-hk-stock-bot"][0]
            self.assertEqual(cn_task["report_type"], "开盘前瞻")
            self.assertIsNone(cn_task["title_override"])
            gh_task = [t for t in failed_tasks if t["bot"] == "github-hn-bot"][0]
            self.assertEqual(gh_task["report_type"], "周盘点")

            # --force picks both premarket and close for cn-hk-stock-bot
            force_tasks = notion_reconcile.collect_reconcile_tasks(
                bots_root=root, target_dates={"2026-11-14"}, bot_filter="cn-hk-stock-bot", only_failed=False
            )
            self.assertEqual(
                [(t["report_type"], t["title_override"]) for t in force_tasks],
                [
                    ("收盘复盘", None),
                    ("开盘前瞻", None),
                ],
            )

    def test_dry_run_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._seed_bot(
                root,
                "AI Daily News Bot",
                {"2026-11-14.txt": "AI 日报正文"},
                [{"ts": "2026-11-14 15:10", "status": "OK", "notion_ok": False}],
            )
            with patch.object(notion_reconcile, "archive_to_notion") as mock_arch:
                rc_dry = notion_reconcile.run_reconcile(
                    bots_root=root, date_str="2026-11-14", only_failed=True, dry_run=True
                )
            self.assertEqual(rc_dry, 0)
            mock_arch.assert_not_called()

            with patch.object(notion_reconcile, "archive_to_notion", return_value=(False, "HTTP 502")):
                rc_fail = notion_reconcile.run_reconcile(
                    bots_root=root, date_str="2026-11-14", only_failed=True, dry_run=False
                )
            self.assertEqual(rc_fail, 1)

            with patch.object(notion_reconcile, "archive_to_notion", return_value=(True, "https://notion.so/p9")):
                rc_ok = notion_reconcile.run_reconcile(
                    bots_root=root, date_str="2026-11-14", only_failed=True, dry_run=False
                )
            self.assertEqual(rc_ok, 0)


class TestHealthCheckBaseNotionWarn(unittest.TestCase):
    def test_health_check_warns_on_notion_ok_false_and_exits_zero(self):
        health_base = SHARED_DIR / "health_check_base.sh"
        today = datetime.now().strftime("%Y-%m-%d")
        with tempfile.TemporaryDirectory() as tmp:
            bot_dir = Path(tmp)
            logs_dir = bot_dir / "logs"
            logs_dir.mkdir(parents=True)
            (logs_dir / "run.log").write_text(f"{today} 15:05  [OK]  AI写稿 → 飞书推送成功 | Notion ⚠️\n", encoding="utf-8")
            (logs_dir / "run.jsonl").write_text(
                json.dumps(
                    {
                        "ts": f"{today} 15:05",
                        "status": "OK",
                        "notion_ok": False,
                        "notion_err": "HTTP 503",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            wrapper = bot_dir / "health_check.sh"
            wrapper.write_text(
                f"""#!/bin/bash
DIR="{bot_dir}"
BOT_NAME="TestBot"
NO_NEWS_PATTERN="NO_NEWS_NEVER"
NO_NEWS_MSG="none"
MISSED_LOOKBACK=0
source "{health_base}"
""",
                encoding="utf-8",
            )
            proc = subprocess.run(["/bin/bash", str(wrapper)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn("[health_check] WARN: notion_ok=False (HTTP 503)", proc.stdout)

            # Once a subsequent OK with notion_ok=True lands for the same session, warning clears
            with open(logs_dir / "run.jsonl", "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {"ts": f"{today} 15:10", "status": "OK", "notion_ok": True},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
            proc2 = subprocess.run(["/bin/bash", str(wrapper)], text=True, capture_output=True)
            self.assertEqual(proc2.returncode, 0)
            self.assertNotIn("notion_ok=False", proc2.stdout)

    def test_cn_hk_session_filter_prevents_morning_ok_masking_and_matches_ere(self):
        health_base = SHARED_DIR / "health_check_base.sh"
        today = datetime.now().strftime("%Y-%m-%d")
        with tempfile.TemporaryDirectory() as tmp:
            bot_dir = Path(tmp)
            logs_dir = bot_dir / "logs"
            logs_dir.mkdir(parents=True)
            # 早盘 premarket [OK] 不得掩盖晚盘 close 缺跑或失败
            (logs_dir / "run.log").write_text(
                f"{today} 09:05  [OK]  A股(1500字) + 港股(1400字) 飞书双机器人推送成功 (premarket)\n",
                encoding="utf-8",
            )
            wrapper = bot_dir / "health_check.sh"
            wrapper.write_text(
                f"""#!/bin/bash
DIR="{bot_dir}"
BOT_NAME="CN-HK-Test"
CATCHUP_FROM=0
CATCHUP_UNTIL=24
MISSING_WAIT_SEC=0
SESSION_FILTER="close"
NO_NEWS_PATTERN="休市|非交易日|自动跳过"
NO_NEWS_MSG="今日休市"
ENABLE_CLAUDE_REPAIR=0
MISSED_LOOKBACK=0
source "{health_base}"
""",
                encoding="utf-8",
            )
            proc = subprocess.run(["/bin/bash", str(wrapper)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertEqual(proc.stderr, "")
            self.assertIn(f"[health_check] WARN: 今天（{today}）无运行记录", proc.stdout)

            # 非交易日休市 ERE WARN（含 | 分隔符）应判定为 NO_NEWS 而非 MISSING
            (logs_dir / "run.log").write_text(
                f"{today} 16:15  [WARN]  沪深港今日均休市（close；A股最近 20261113），未出稿\n",
                encoding="utf-8",
            )
            proc2 = subprocess.run(["/bin/bash", str(wrapper)], text=True, capture_output=True)
            self.assertEqual(proc2.returncode, 0, msg=proc2.stderr)
            self.assertEqual(proc2.stderr, "")
            self.assertIn(f"[health_check] NO_NEWS: 今天（{today}）今日休市", proc2.stdout)


if __name__ == "__main__":
    unittest.main()
