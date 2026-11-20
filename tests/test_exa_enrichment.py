"""Unit tests for Exa enrichment helpers in shared/bot_utils.py and cn_hk_report.py bug fixes."""

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "cn-hk-stock-bot"))
sys.path.insert(0, str(ROOT / "us stock bot"))

import bot_utils
import cn_hk_report
import stock_report


class TestExaHelpers(unittest.TestCase):
    def test_effort_clamps_unsafe_modes(self):
        self.assertEqual(bot_utils._normalize_exa_effort("low"), "low")
        self.assertEqual(bot_utils._normalize_exa_effort("medium"), "medium")
        self.assertEqual(bot_utils._normalize_exa_effort("auto"), "medium")
        self.assertEqual(bot_utils._normalize_exa_effort("ultra"), "medium")

    def test_exa_enrich_enabled_switch(self):
        with patch.dict(os.environ, {"EXA_API_KEY": "test-key", "ENABLE_EXA_ENRICH": "0"}):
            self.assertFalse(bot_utils.exa_enrich_enabled(default_enabled=True))
        with patch.dict(os.environ, {"EXA_API_KEY": "test-key", "ENABLE_EXA_ENRICH": "1"}):
            self.assertTrue(bot_utils.exa_enrich_enabled(default_enabled=False))

    def test_exa_fetch_contents_maps_url_key(self):
        mock_sess = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "url": "https://www.wsj.com/articles/test-story?mod=rss_markets_main",
                    "text": "A" * 400,
                },
                {
                    "url": "https://www.wsj.com/articles/too-short",
                    "text": "short",
                },
            ]
        }
        mock_sess.post.return_value = mock_resp

        with patch.dict(os.environ, {"EXA_API_KEY": "test-key"}):
            out = bot_utils.exa_fetch_contents(
                ["https://www.wsj.com/articles/test-story?mod=rss_markets_main"],
                max_chars=500,
                session=mock_sess,
            )

        self.assertIn(bot_utils.url_key("https://www.wsj.com/articles/test-story"), out)
        self.assertEqual(len(out), 1)

    def test_exa_agent_filters_only_confirmed(self):
        mock_sess = MagicMock()
        create_resp = MagicMock()
        create_resp.json.return_value = {"id": "agent_run_test123", "status": "queued"}
        poll_resp = MagicMock()
        poll_resp.json.return_value = {
            "id": "agent_run_test123",
            "status": "completed",
            "costDollars": {"total": 0.1},
            "output": {
                "structured": {
                    "items": [
                        {
                            "symbol": "PDD",
                            "name": "拼多多",
                            "verdict": "confirmed",
                            "catalyst_type": "earnings",
                            "catalyst_summary": "拼多多发布三季报营收超预期并宣布股票回购计划",
                            "source_title": "Reuters",
                            "source_url": "https://www.reuters.com/example",
                        },
                        {
                            "symbol": "NKE",
                            "name": "耐克",
                            "verdict": "absent",
                            "catalyst_type": None,
                            "catalyst_summary": None,
                            "source_title": None,
                            "source_url": None,
                        },
                        {
                            "symbol": "UNH",
                            "name": "联合健康",
                            "verdict": "cannot_verify",
                            "catalyst_type": None,
                            "catalyst_summary": "should be ignored",
                            "source_title": None,
                            "source_url": None,
                        },
                    ]
                }
            },
        }
        mock_sess.post.return_value = create_resp
        mock_sess.get.return_value = poll_resp

        entities = [
            {"symbol": "PDD", "name": "拼多多", "pct_change": "+11.04%", "sector": "中概ADR"},
            {"symbol": "NKE", "name": "耐克", "pct_change": "-5.45%", "sector": "可选消费"},
            {"symbol": "UNH", "name": "联合健康", "pct_change": "-5.55%", "sector": "医疗"},
        ]
        with patch.dict(os.environ, {"EXA_API_KEY": "test-key", "EXA_AGENT_EFFORT": "medium"}):
            confirmed = bot_utils.exa_agent_verify_catalysts(
                entities,
                market_label="美股",
                session_date="2026-11-19",
                poll_interval=0.01,
                session=mock_sess,
            )

        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["symbol"], "PDD")
        self.assertEqual(confirmed[0]["pct_change"], "+11.04%")
        block = bot_utils.format_exa_catalyst_block(confirmed)
        self.assertIn("拼多多(PDD +11.04%)", block)
        self.assertIn("[财报业绩]", block)


class TestCnHkTelegraphFixAndSelection(unittest.TestCase):
    def test_fetch_sina_telegraph_drops_stale_and_sorts_newest_first(self):
        fake_feeds = {
            "tag_id=10": [
                {"create_time": "2026-11-11 15:00:00", "rich_text": "这是九天前的陈旧A股收评内容，长度超过二十个字应该被过滤掉"},
                {"create_time": "2026-11-19 15:01:00", "rich_text": "2026-11-19 A股收评：沪指震荡收跌0.28%，半导体走势分化明显"},
            ],
            "tag_id=4": [
                {"create_time": "2026-11-20 07:30:00", "rich_text": "日本10月核心CPI同比上涨2.2%，市场继续博弈日本央行12月加息"},
            ],
            "tag_id=0": [
                {"create_time": "2026-11-20 09:00:05", "rich_text": "中国11月1年期LPR报3.0%，5年期以上LPR报3.5%，均维持不变"},
            ],
        }

        def fake_get(url, **kwargs):
            resp = MagicMock()
            for k, rows in fake_feeds.items():
                if k in url:
                    resp.json.return_value = {"result": {"data": {"feed": {"list": rows}}}}
                    return resp
            resp.json.return_value = {}
            return resp

        with patch.object(cn_hk_report.DIRECT_SESSION, "get", side_effect=fake_get):
            items = cn_hk_report.fetch_sina_telegraph(
                limit=10,
                max_age_hours=36,
                now_dt=datetime(2026, 11, 20, 9, 24, 0),
            )

        self.assertEqual(len(items), 3)
        self.assertIn("中国11月1年期LPR", items[0])
        self.assertIn("日本10月核心CPI", items[1])
        self.assertIn("2026-11-19 A股收评", items[2])
        self.assertFalse(any("九天前" in it for it in items))

    def test_select_uncovered_cn_hk_merges_dual_listed(self):
        quotes = {
            "usPDD": {"pct": 11.04},
            "usNTES": {"pct": -11.39},
            "usBABA": {"pct": -1.26},
        }
        cn_pool = {
            "gainers": [],
            "losers": [
                {
                    "name": "半导体芯片与设备",
                    "pct": -3.67,
                    "stocks": [{"code": "sh688041", "name": "海光信息", "pct": -9.39}],
                }
            ],
        }
        hk_pool = {
            "gainers": [],
            "losers": [
                {
                    "name": "游戏内容与文旅出行",
                    "pct": -3.09,
                    "stocks": [{"code": "hk09999", "name": "网易-S", "pct": -14.39}],
                }
            ],
        }
        picked = cn_hk_report._select_uncovered_cn_hk_movers(
            "premarket", quotes, cn_pool, hk_pool, telegraph=["无相关个股电报"], max_total=6
        )
        syms = [p["symbol"] for p in picked]
        self.assertEqual(syms.count("NTES / 09999.HK"), 1)
        self.assertIn("PDD", syms)
        self.assertIn("688041.SH", syms)


class TestUsUncoveredSelection(unittest.TestCase):
    def test_select_uncovered_us_movers_skips_covered(self):
        quotes = {
            "XLK": {"change_pct": "-1.90%"},
            "XLY": {"change_pct": "-2.79%"},
            "XLE": {"change_pct": "-0.65%"},
            "XLU": {"change_pct": "-1.24%"},
            "XLP": {"change_pct": "-1.45%"},
            "XLC": {"change_pct": "-2.67%"},
            "XLB": {"change_pct": "-2.06%"},
            "AMD": {"change_pct": "-7.72%", "shortName": "AMD"},
            "NKE": {"change_pct": "-5.45%", "shortName": "Nike"},
            "UNH": {"change_pct": "-5.55%", "shortName": "UnitedHealth"},
            "INTC": {"change_pct": "+1.92%", "shortName": "Intel"},
        }
        news_lines = ["[原始英文标题] AMD dives on short seller report"]
        picked = stock_report._select_uncovered_us_movers(quotes, news_lines, max_total=6)
        syms = [p["symbol"] for p in picked]
        self.assertNotIn("AMD", syms)
        self.assertIn("NKE", syms)
        self.assertIn("UNH", syms)
        self.assertIn("INTC", syms)


if __name__ == "__main__":
    unittest.main()
