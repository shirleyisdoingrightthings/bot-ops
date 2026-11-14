"""Offline regression tests for Plan 005: report_type & business date_str alignment."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime as real_datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

SHARED_DIR = Path(__file__).resolve().parent.parent
BOTS_DIR = SHARED_DIR.parent
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import bot_utils  # noqa: E402
import notion_archive  # noqa: E402


def _load_module(name: str, bot_dir: Path, filename: str):
    path = bot_dir / filename
    added = False
    if str(bot_dir) not in sys.path:
        sys.path.insert(0, str(bot_dir))
        added = True
    try:
        spec = importlib.util.spec_from_file_location(name, str(path))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        return mod
    finally:
        if added and str(bot_dir) in sys.path:
            sys.path.remove(str(bot_dir))


class _FakeDatetimeSunday(real_datetime):
    @classmethod
    def now(cls, tz=None):
        # 2026-11-15 is a Sunday (weekday() == 6)
        return cls(2026, 11, 15, 10, 0, 0)


class _FakeDatetimeNov14(real_datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 14, 15, 0, 0)


class TestExtractReportDate(unittest.TestCase):
    def test_extracts_cn_and_iso_and_ignores_builder_utc_span(self):
        self.assertEqual(
            bot_utils.extract_report_date("<b>🔥 X 热点 · 2026年11月13日</b>\n\n正文"),
            "2026-11-13",
        )
        self.assertEqual(
            bot_utils.extract_report_date(
                "<b>🛠 AI Builder 日报 · 2026-11-14</b>\n\n这批推文来自 2026-11-13 UTC，讨论热点。"
            ),
            "2026-11-14",
        )

    def test_returns_default_when_missing_or_invalid_or_only_utc_span(self):
        self.assertEqual(bot_utils.extract_report_date("无日期标题\n\n正文", default="2026-11-10"), "2026-11-10")
        self.assertIsNone(bot_utils.extract_report_date("<b>标题 · 2026-13-45</b>"))
        self.assertEqual(
            bot_utils.extract_report_date(
                "AI Builder 动态\n\n这批推文来自 2026-11-13 09:04 ~ 2026-11-14 05:19 UTC，正文。",
                default="2026-11-14",
            ),
            "2026-11-14",
        )


class TestSendXLinkedDateForwarding(unittest.TestCase):
    def test_forwards_heading_date_over_clock_and_falls_back_to_fetch_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            draft = tdir / "draft.txt"
            log_file = tdir / "run.log"
            cache_file = tdir / "pending.json"
            fetch_meta = tdir / "fetch_meta.json"
            sent_urls = tdir / "sent_urls.json"

            fetch_meta.write_text(
                json.dumps({"log_summary": "原帖 3 条", "fetch_date": "2026-11-12", "metrics": {}}),
                encoding="utf-8",
            )
            draft.write_text(
                '<b>🔥 X 热点 · 2026-11-13</b>\n\n1. 测试话题\n\n<a href="https://x.com/u/status/123">原帖</a>',
                encoding="utf-8",
            )
            write_log = MagicMock()
            save_pending = MagicMock()

            with patch.object(bot_utils, "already_ran_today", return_value=False), patch.object(
                bot_utils, "send_feishu", return_value=1
            ), patch.object(bot_utils, "record_sent_urls", return_value=1), patch.object(
                bot_utils, "datetime", _FakeDatetimeNov14
            ), patch.object(
                notion_archive, "archive_to_notion", return_value=(True, "https://notion.so/p1")
            ) as mock_archive:
                rc = bot_utils.send_x_linked_report(
                    draft,
                    log_file=log_file,
                    cache_file=cache_file,
                    fetch_meta=fetch_meta,
                    sent_urls=sent_urls,
                    webhook="https://hook.local",
                    write_log=write_log,
                    save_pending=save_pending,
                    link_label="原帖",
                )
            self.assertEqual(rc, 0)
            mock_archive.assert_called_once()
            self.assertEqual(mock_archive.call_args.kwargs["date_str"], "2026-11-13")

            # Fallback to fetch_meta.fetch_date when heading lacks a date
            draft.write_text(
                '<b>🛠 AI Builder 动态</b>\n\n<a href="https://x.com/u/status/456">原推</a>',
                encoding="utf-8",
            )
            with patch.object(bot_utils, "already_ran_today", return_value=False), patch.object(
                bot_utils, "send_feishu", return_value=1
            ), patch.object(bot_utils, "record_sent_urls", return_value=1), patch.object(
                bot_utils, "datetime", _FakeDatetimeNov14
            ), patch.object(
                notion_archive, "archive_to_notion", return_value=(True, "https://notion.so/p2")
            ) as mock_archive2:
                rc2 = bot_utils.send_x_linked_report(
                    draft,
                    log_file=log_file,
                    cache_file=cache_file,
                    fetch_meta=fetch_meta,
                    sent_urls=sent_urls,
                    webhook="https://hook.local",
                    write_log=write_log,
                    save_pending=save_pending,
                    link_label="原推",
                )
            self.assertEqual(rc2, 0)
            self.assertEqual(mock_archive2.call_args.kwargs["date_str"], "2026-11-12")


class TestGithubHnAndAiDailyAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gh_mod = _load_module("test_github_hn_report_mod", BOTS_DIR / "github-hn-bot", "github_hn_report.py")
        cls.daily_mod = _load_module("test_daily_report_mod", BOTS_DIR / "AI Daily News Bot", "daily_report.py")

    def test_github_hn_since_override_and_fetch_meta_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            archive_dir = tdir / "archive"
            archive_dir.mkdir()
            draft = tdir / "draft.txt"
            log_file = tdir / "run.log"
            cache_file = tdir / "pending.json"
            fetch_meta = tdir / "fetch_meta.json"
            seen_history = tdir / "seen.json"

            draft.write_text(
                '<b>🐙 GitHub Trending · 2026年11月14日</b>\n\n<a href="https://github.com/a/b">a/b</a>',
                encoding="utf-8",
            )
            fetch_meta.write_text(json.dumps({"metrics": {"since": "daily"}}), encoding="utf-8")

            with patch.object(self.gh_mod, "DRAFT_FILE", draft), patch.object(
                self.gh_mod, "LOG_FILE", log_file
            ), patch.object(self.gh_mod, "CACHE_FILE", cache_file), patch.object(
                self.gh_mod, "FETCH_META", fetch_meta
            ), patch.object(self.gh_mod, "ARCHIVE_DIR", archive_dir), patch.object(
                self.gh_mod, "SEEN_HISTORY", seen_history
            ), patch.object(self.gh_mod, "already_ran_today", return_value=False), patch.object(
                self.gh_mod, "send_feishu", return_value=1
            ), patch.object(self.gh_mod, "record_seen_history", return_value=1), patch.object(
                self.gh_mod, "write_log"
            ), patch.object(
                self.gh_mod, "datetime", _FakeDatetimeNov14
            ), patch.object(
                notion_archive, "archive_to_notion", return_value=(True, "https://notion.so/gh1")
            ) as mock_archive:
                rc = self.gh_mod.run_send(since_override="weekly")
            self.assertEqual(rc, 0)
            self.assertEqual(mock_archive.call_args.kwargs["report_type"], "周盘点")
            self.assertEqual(mock_archive.call_args.kwargs["date_str"], "2026-11-14")

            # Passing since_override="daily" on a mocked Sunday still produces 日报
            with patch.object(self.gh_mod, "DRAFT_FILE", draft), patch.object(
                self.gh_mod, "LOG_FILE", log_file
            ), patch.object(self.gh_mod, "CACHE_FILE", cache_file), patch.object(
                self.gh_mod, "FETCH_META", fetch_meta
            ), patch.object(self.gh_mod, "ARCHIVE_DIR", archive_dir), patch.object(
                self.gh_mod, "SEEN_HISTORY", seen_history
            ), patch.object(self.gh_mod, "already_ran_today", return_value=False), patch.object(
                self.gh_mod, "send_feishu", return_value=1
            ), patch.object(self.gh_mod, "record_seen_history", return_value=1), patch.object(
                self.gh_mod, "write_log"
            ), patch.object(
                self.gh_mod, "datetime", _FakeDatetimeSunday
            ), patch.object(
                notion_archive, "archive_to_notion", return_value=(True, "https://notion.so/gh2")
            ) as mock_archive2:
                rc2 = self.gh_mod.run_send(since_override="daily")
            self.assertEqual(rc2, 0)
            self.assertEqual(mock_archive2.call_args.kwargs["report_type"], "日报")

            # No CLI override & no date in heading: recovers both date_str and weekly from fetch_meta
            draft.write_text('<a href="https://github.com/a/b">a/b</a>', encoding="utf-8")
            fetch_meta.write_text(
                json.dumps({"date_str": "2026-11-09", "metrics": {"since": "weekly"}}),
                encoding="utf-8",
            )
            with patch.object(self.gh_mod, "DRAFT_FILE", draft), patch.object(
                self.gh_mod, "LOG_FILE", log_file
            ), patch.object(self.gh_mod, "CACHE_FILE", cache_file), patch.object(
                self.gh_mod, "FETCH_META", fetch_meta
            ), patch.object(self.gh_mod, "ARCHIVE_DIR", archive_dir), patch.object(
                self.gh_mod, "SEEN_HISTORY", seen_history
            ), patch.object(self.gh_mod, "already_ran_today", return_value=False), patch.object(
                self.gh_mod, "send_feishu", return_value=1
            ), patch.object(self.gh_mod, "record_seen_history", return_value=1), patch.object(
                self.gh_mod, "write_log"
            ), patch.object(
                self.gh_mod, "datetime", _FakeDatetimeNov14
            ), patch.object(
                notion_archive, "archive_to_notion", return_value=(True, "https://notion.so/gh3")
            ) as mock_archive3:
                rc3 = self.gh_mod.run_send()
            self.assertEqual(rc3, 0)
            self.assertEqual(mock_archive3.call_args.kwargs["date_str"], "2026-11-09")
            self.assertEqual(mock_archive3.call_args.kwargs["report_type"], "周盘点")
            self.assertTrue((archive_dir / "2026-11-09.txt").exists())

    def test_daily_report_forwards_business_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            draft = tdir / "draft.txt"
            log_file = tdir / "run.log"
            cache_file = tdir / "pending.json"
            fetch_meta = tdir / "fetch_meta.json"
            sent_urls = tdir / "sent_urls.json"

            fetch_meta.write_text(
                json.dumps({"log_summary": "抓取5条 → 保留2条", "fetch_date": "2026-11-12", "metrics": {}}),
                encoding="utf-8",
            )
            draft.write_text(
                '<b>📋 AI 产业日报 · 2026-11-13</b>\n\n<a href="https://a.com"><b>标题</b></a>',
                encoding="utf-8",
            )
            with patch.object(self.daily_mod, "LOG_FILE", log_file), patch.object(
                self.daily_mod, "CACHE_FILE", cache_file
            ), patch.object(self.daily_mod, "FETCH_META", fetch_meta), patch.object(
                self.daily_mod, "SENT_URLS", sent_urls
            ), patch.object(self.daily_mod, "already_ran_today", return_value=False), patch.object(
                self.daily_mod, "send_report", return_value=1
            ), patch.object(self.daily_mod, "record_sent_urls", return_value=1), patch.object(
                self.daily_mod, "write_log"
            ), patch.object(
                self.daily_mod, "datetime", _FakeDatetimeNov14
            ), patch.object(
                notion_archive, "archive_to_notion", return_value=(True, "https://notion.so/ai1")
            ) as mock_archive:
                rc = self.daily_mod.run_send(draft)
            self.assertEqual(rc, 0)
            self.assertEqual(mock_archive.call_args.kwargs["date_str"], "2026-11-13")


if __name__ == "__main__":
    unittest.main()
