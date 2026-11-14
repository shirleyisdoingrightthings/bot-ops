"""Offline unit test baseline for bots/shared/notion_archive.py."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SHARED_DIR = Path(__file__).resolve().parent.parent
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import notion_archive as na  # noqa: E402


def _block_plain(block: dict) -> str:
    btype = block["type"]
    if btype == "divider":
        return "---"
    items = block[btype].get("rich_text", [])
    return "".join(it["text"]["content"] for it in items)


class TestRichText(unittest.TestCase):
    def test_plain_and_inline_formatting(self):
        self.assertEqual(
            na.rich_text("hello"),
            [{"type": "text", "text": {"content": "hello"}}],
        )
        bold_md = na.rich_text("**加粗**")
        self.assertEqual(bold_md[0]["annotations"], {"bold": True})
        self.assertEqual(bold_md[0]["text"]["content"], "加粗")

        bold_html = na.rich_text("<b>加粗</b>")
        self.assertEqual(bold_html[0]["annotations"], {"bold": True})
        self.assertEqual(bold_html[0]["text"]["content"], "加粗")

        md_link = na.rich_text("[OpenAI](https://openai.com)")
        self.assertEqual(md_link[0]["text"]["link"], {"url": "https://openai.com"})

        md_bold_link = na.rich_text("**[OpenAI](https://openai.com)**")
        self.assertEqual(md_bold_link[0]["annotations"], {"bold": True})
        self.assertEqual(md_bold_link[0]["text"]["link"], {"url": "https://openai.com"})

        html_bold_link = na.rich_text('<a href="https://openai.com"><b>标题</b></a>')
        self.assertEqual(html_bold_link[0]["annotations"], {"bold": True})
        self.assertEqual(html_bold_link[0]["text"]["link"], {"url": "https://openai.com"})
        self.assertEqual(html_bold_link[0]["text"]["content"], "标题")

    def test_nested_numbered_repo_link_normalization(self):
        items = na.rich_text('<b>1. <a href="https://github.com/a/b">a/b</a></b>')
        self.assertEqual("".join(it["text"]["content"] for it in items), "1. a/b")
        link_items = [it for it in items if it["text"].get("link")]
        self.assertEqual(len(link_items), 1)
        self.assertEqual(link_items[0]["text"]["link"]["url"], "https://github.com/a/b")
        self.assertTrue(link_items[0]["annotations"]["bold"])

    def test_non_http_links_stripped(self):
        items = na.rich_text('<a href="javascript:alert(1)">click</a>')
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], {"content": "click"})
        self.assertNotIn("link", items[0]["text"])

    def test_long_text_chunks_under_limit(self):
        long_str = "A" * (na.TEXT_LIMIT * 2 + 17)
        items = na.rich_text(long_str)
        self.assertEqual(len(items), 3)
        self.assertTrue(all(len(it["text"]["content"]) <= na.TEXT_LIMIT for it in items))
        self.assertEqual("".join(it["text"]["content"] for it in items), long_str)

    def test_parenthesized_markdown_url_and_italics(self):
        wiki = na.rich_text("[Wiki](https://en.wikipedia.org/wiki/Foo_(bar))")
        self.assertEqual(wiki[0]["text"]["content"], "Wiki")
        self.assertEqual(
            wiki[0]["text"]["link"]["url"],
            "https://en.wikipedia.org/wiki/Foo_(bar)",
        )

        bold_wiki = na.rich_text("**[BoldWiki](https://en.wikipedia.org/wiki/Foo_(bar))**")
        self.assertEqual(bold_wiki[0]["annotations"], {"bold": True})
        self.assertEqual(
            bold_wiki[0]["text"]["link"]["url"],
            "https://en.wikipedia.org/wiki/Foo_(bar)",
        )

        md_bad = na.rich_text("[bad](javascript:alert(1))")
        self.assertEqual(md_bad[0]["text"]["content"], "bad")
        self.assertNotIn("link", md_bad[0]["text"])

        it_i = na.rich_text("<i>斜体</i>与<em>强调</em>")
        self.assertEqual(it_i[0]["text"]["content"], "斜体")
        self.assertEqual(it_i[0]["annotations"], {"italic": True})
        self.assertEqual(it_i[2]["text"]["content"], "强调")
        self.assertEqual(it_i[2]["annotations"], {"italic": True})

        bold_it = na.rich_text("<b><i>粗斜体</i></b>")
        self.assertEqual(bold_it[0]["text"]["content"], "粗斜体")
        self.assertEqual(bold_it[0]["annotations"], {"bold": True, "italic": True})

        link_it = na.rich_text('<a href="https://a.com"><i>链接斜体</i></a>')
        self.assertEqual(link_it[0]["text"]["link"]["url"], "https://a.com")
        self.assertEqual(link_it[0]["annotations"], {"italic": True})


class TestHeadingHelpers(unittest.TestCase):
    def test_format_cn_hk_heading(self):
        self.assertEqual(
            na._format_cn_hk_heading("🌅 🇨🇳 A股开盘前瞻 · 2026年11月13日"),
            "🌅 🇨🇳 A股开盘前瞻 · 2026-11-13",
        )
        self.assertEqual(
            na._format_cn_hk_heading("🇭🇰 港股收盘复盘 · 2026年11月9日"),
            "🇭🇰 港股收盘复盘 · 2026-11-09",
        )

    def test_is_star_line(self):
        self.assertTrue(na._is_star_line("⭐⭐⭐⭐⭐ #AI模型 #AI产品"))
        self.assertTrue(na._is_star_line("⭐⭐⭐"))
        self.assertFalse(na._is_star_line("⭐⭐⭐ 推荐"))

    def test_is_x_builder_topic_heading(self):
        self.assertTrue(
            na._is_x_builder_topic_heading(
                "<b>1. 硅谷多位 CEO 联署声援黄仁勋</b>",
                "1. 硅谷多位 CEO 联署声援黄仁勋",
            )
        )
        self.assertFalse(
            na._is_x_builder_topic_heading(
                "1. 这只是普通列表说明文字。",
                "1. 这只是普通列表说明文字。",
            )
        )

    def test_standalone_headline_link_helper(self):
        self.assertTrue(na._is_standalone_headline_link('<a href="https://a.com"><b>标题</b></a>'))
        self.assertTrue(na._is_standalone_headline_link("**[标题](https://a.com)**"))
        self.assertFalse(na._is_standalone_headline_link('<b>前缀</b>：<a href="https://a.com">引用</a>'))


class TestConvertToBlocksBySource(unittest.TestCase):
    def test_ai_daily_layout_and_legacy_star_reorder(self):
        draft = """<b>📋 AI 产业日报 · 2026-11-13</b>

<b>⚡ 30秒速览</b>

- 第一条要点
- 第二条要点

<a href="https://example.com/1"><b>Google 发布新模型</b></a>

⭐⭐⭐⭐⭐ #AI模型

📄 The Details：
完整叙事段落内容。

⭐⭐⭐⭐ #Agent

<a href="https://example.com/2"><b>旧版先星级后标题</b></a>

📄 The Details：
第二段完整内容。
"""
        blocks = na.convert_to_blocks(draft, source="🤖 AI 产业日报")
        types_texts = [(b["type"], _block_plain(b)) for b in blocks]
        # Top title and redundant 30s summary are stripped
        self.assertFalse(any("AI 产业日报" in txt for _, txt in types_texts))
        self.assertFalse(any("第一条要点" in txt for _, txt in types_texts))
        # Both headlines become heading_2 BEFORE their star line
        h2_indices = [idx for idx, (bt, _) in enumerate(types_texts) if bt == "heading_2"]
        self.assertEqual(len(h2_indices), 2)
        self.assertEqual(types_texts[h2_indices[0]][1], "Google 发布新模型")
        self.assertEqual(types_texts[h2_indices[0] + 1], ("paragraph", "⭐⭐⭐⭐⭐ #AI模型"))
        self.assertEqual(types_texts[h2_indices[1]][1], "旧版先星级后标题")
        self.assertEqual(types_texts[h2_indices[1] + 1], ("paragraph", "⭐⭐⭐⭐ #Agent"))

    def test_x_and_builder_strip_top_intro_and_promote_topics(self):
        draft = """<b>🔥 X 热点 · 2026-11-13</b>

今天 X 上的核心争论聚焦在模型评测与定价分歧。

<b>1. 模型实测分歧</b>

正文描述与讨论。

## 📎 主流媒体同期在报

- <a href="https://techmeme.com/1">Techmeme 报道</a>
"""
        blocks = na.convert_to_blocks(draft, source="🐦 X 热点播报")
        types_texts = [(b["type"], _block_plain(b)) for b in blocks]
        self.assertEqual(types_texts[0], ("heading_2", "1. 模型实测分歧"))
        self.assertIn(("heading_2", "📎 主流媒体同期在报"), types_texts)
        self.assertIn(("bulleted_list_item", "Techmeme 报道"), types_texts)
        self.assertFalse(any("X 热点" in t for _, t in types_texts))
        self.assertFalse(any("核心争论聚焦" in t for _, t in types_texts))

    def test_github_hn_hierarchy_h2_and_h3(self):
        draft = """<b>🐙 GitHub Trending & Hacker News 早报 · 2026年11月14日</b>

<b>⚡ 30秒速览</b>
- 🛠️ <b>今日立即可用轮子</b>：foo/bar

<b>🚀 一、GitHub 今日飙升榜（Daily Top 10）</b>
<b>1.</b> <a href="https://github.com/foo/bar"><b>foo/bar</b></a>（Python · ★ 1,000 · 今日 +200）
🏷️ <b>场景定位</b>：#Agent

<b>🔥 二、Hacker News 热榜 Top 8（Best 高赞 & Top 实时热议）</b>
### 1. [某个热门讨论](https://news.ycombinator.com/item?id=1)
Original: Some title
"""
        blocks = na.convert_to_blocks(draft, source="🐙 GitHub & HN")
        types_texts = [(b["type"], _block_plain(b)) for b in blocks]
        self.assertFalse(any("GitHub Trending & Hacker News 早报" in t for _, t in types_texts))
        self.assertFalse(any("今日立即可用轮子" in t for _, t in types_texts))
        self.assertIn(("heading_2", "🚀 一、GitHub 今日飙升榜（Daily Top 10）"), types_texts)
        self.assertIn(("heading_3", "1. foo/bar（Python · ★ 1,000 · 今日 +200）"), types_texts)
        self.assertIn(("heading_2", "🔥 二、Hacker News 热榜 Top 8（Best 高赞 & Top 实时热议）"), types_texts)
        self.assertIn(("heading_3", "1. 某个热门讨论"), types_texts)

    def test_cn_hk_strips_outer_market_heading_and_splits_divider(self):
        draft = """## 📈 A股市场（2026年11月13日 收盘复盘）

<b>🇨🇳 A股收盘复盘 · 2026年11月13日</b>

---

## 🇭🇰 港股市场（2026年11月13日 收盘复盘）

<b>🇭🇰 港股收盘复盘 · 2026年11月13日</b>
"""
        blocks = na.convert_to_blocks(draft, source="📈 A股与港股")
        types_texts = [(b["type"], _block_plain(b)) for b in blocks]
        self.assertNotIn(("heading_2", "📈 A股市场（2026年11月13日 收盘复盘）"), types_texts)
        self.assertEqual(types_texts[0], ("heading_1", "🇨🇳 A股收盘复盘 · 2026-11-13"))
        self.assertEqual(types_texts[1], ("divider", "---"))
        self.assertEqual(types_texts[2], ("heading_1", "🇭🇰 港股收盘复盘 · 2026-11-13"))

    def test_dot_bullets_become_bulleted_list_items(self):
        draft = """<b>🇨🇳 A股收盘复盘 · 2026年11月13日</b>
<b>🎯 决策仪表盘</b>
· <b>信号灯状态</b>：🔴 防守控仓 — 科技成长退潮
• 条目二
- 条目三
"""
        blocks = na.convert_to_blocks(draft, source="📈 A股与港股")
        types_texts = [(b["type"], _block_plain(b)) for b in blocks]
        self.assertIn(("bulleted_list_item", "信号灯状态：🔴 防守控仓 — 科技成长退潮"), types_texts)
        self.assertIn(("bulleted_list_item", "条目二"), types_texts)
        self.assertIn(("bulleted_list_item", "条目三"), types_texts)

    def test_details_bold_lead_stays_paragraph_and_gh_leading_blanks_stripped(self):
        ai_draft = """<b>📋 AI 产业日报 · 2026-11-14</b>

<a href="https://a.com"><b>第一条新闻</b></a>

⭐⭐⭐⭐⭐ #AI

📄 The Details：
<b>核心分歧点</b>：短句加粗引导段落不应升级为标题

<a href="https://b.com"><b>第二条新闻</b></a>

⭐⭐⭐⭐ #Agent

📄 The Details：
第二段详情。
"""
        blocks = na.convert_to_blocks(ai_draft, source="🤖 AI 产业日报")
        types_texts = [(b["type"], _block_plain(b)) for b in blocks]
        h2s = [txt for bt, txt in types_texts if bt == "heading_2"]
        self.assertEqual(h2s, ["第一条新闻", "第二条新闻"])
        self.assertIn(("paragraph", "核心分歧点：短句加粗引导段落不应升级为标题"), types_texts)

        gh_draft = "\n" * 6 + """<b>🐙 GitHub Trending & Hacker News 早报 · 2026年11月14日</b>

<b>🚀 一、GitHub 今日飙升榜（Daily Top 10）</b>
"""
        gh_blocks = na.convert_to_blocks(gh_draft, source="🐙 GitHub & HN")
        gh_texts = [_block_plain(b) for b in gh_blocks]
        self.assertFalse(any("GitHub Trending" in t for t in gh_texts))
        self.assertEqual(gh_texts, ["🚀 一、GitHub 今日飙升榜（Daily Top 10）"])

    def test_us_stock_keeps_h1_strips_news_summary_and_promotes_h2(self):
        draft = """<b>📊 美股收盘 & 加密行情 · 2026-11-13</b>

📈 <b>核心指数</b>：标普500 6000 (+0.5%)

---

<b>📋 美股要闻 · 2026-11-13</b>

<b>⚡ 30秒速览</b>

- 要闻速览条1

<a href="https://cnbc.com/1"><b>美股重大财报超预期</b></a>

⭐⭐⭐⭐⭐ #财报

📄 The Details：
财报具体数字与分析。
"""
        blocks = na.convert_to_blocks(draft, source="🗽 美股与加密")
        types_texts = [(b["type"], _block_plain(b)) for b in blocks]
        self.assertIn(("heading_1", "📊 美股收盘 & 加密行情 · 2026-11-13"), types_texts)
        self.assertIn(("divider", "---"), types_texts)
        self.assertIn(("heading_1", "📋 美股要闻 · 2026-11-13"), types_texts)
        self.assertFalse(any("要闻速览条1" in t for _, t in types_texts))
        self.assertIn(("heading_2", "美股重大财报超预期"), types_texts)


class TestExtractSummaryBySource(unittest.TestCase):
    def test_cn_hk_close_and_premarket_summary_no_mid_sentence_cut(self):
        close_doc = """<b>🇨🇳 A股收盘复盘 · 2026-11-13</b>
📈 <b>核心指数</b>：上证指数 3634.35 (-0.59%) | 创业板 2426.08 (-3.32%)
🧭 <b>市场宽度</b>：涨跌比 — 全市场超4700只下跌
<b>🔥 领涨板块</b>
1. 食品饮料 (+2.15%)
<b>❄️ 领跌板块</b>
1. AI算力 (-4.27%)
<b>🎯 决策仪表盘</b>
· <b>信号灯状态</b>：🔴 防守控仓 — 科技成长退潮

---

<b>🇭🇰 港股收盘复盘 · 2026-11-13</b>
📈 <b>核心指数</b>：恒生指数 23637.60 (-1.55%)
<b>🔥 领涨板块</b>
1. 能源 (+0.71%)
<b>❄️ 领跌板块</b>
1. 电动车 (-4.30%)
<b>🎯 决策仪表盘</b>
· <b>信号灯状态</b>：🔴 防守控仓 — 恒科承压
"""
        s = na.extract_summary(close_doc, source="📈 A股与港股")
        self.assertIn("【A股】信号灯状态：🔴 防守控仓", s)
        self.assertIn("【港股】信号灯状态：🔴 防守控仓", s)
        self.assertTrue(s.index("信号灯状态：🔴 防守控仓") < s.index("核心指数：上证指数"))
        self.assertTrue(s.endswith("。"))

        premarket_doc = """<b>🌅 🇨🇳 A股开盘前瞻 · 2026-11-13</b>
🌍 <b>隔夜外围映射</b>：纳指 (-0.39%)
📐 <b>前日收盘技术锚点</b>：上证 3663.71
<b>⚡ 今日盘前核心看点</b>
1. 海外科技映射：关注算力反馈
<b>🎯 决策仪表盘</b>
· <b>早盘信号灯</b>：🔴 承压防守 — 谨慎追高
"""
        sp = na.extract_summary(premarket_doc, source="📈 A股与港股")
        self.assertIn("【A股】早盘信号灯：🔴 承压防守", sp)
        self.assertTrue(sp.index("早盘信号灯：🔴 承压防守") < sp.index("隔夜外围映射"))

    def test_ai_daily_and_github_and_builder_summary(self):
        ai_doc = """<b>📋 AI 产业日报 · 2026-11-14</b>

<b>⚡ 30秒速览</b>

- 事实一：指标提升 20%
- 事实二：成本下降 50%

<a href="https://example.com"><b>标题</b></a>
"""
        self.assertEqual(
            na.extract_summary(ai_doc, source="🤖 AI 产业日报"),
            "事实一：指标提升 20%；事实二：成本下降 50%。",
        )

        gh_doc = """<b>🐙 GitHub Trending</b>
<b>⚡ 30秒速览</b>
- 🛠️ <b>今日立即可用轮子</b>：foo/bar 好用

<b>🚀 一、GitHub 今日飙升榜</b>
"""
        self.assertEqual(
            na.extract_summary(gh_doc, source="🐙 GitHub & HN"),
            "🛠️ 今日立即可用轮子：foo/bar 好用。",
        )

        builder_doc = """<b>🛠 AI Builder 日报 · 2026-11-14</b>

这批推文来自 2026-11-13 09:04 ~ 2026-11-14 05:19 UTC，今天主要讨论 Agent 基建。

<b>1. 硅谷 CEO 联署</b>

正文。
"""
        b_sum = na.extract_summary(builder_doc, source="🛠️ AI Builder")
        self.assertIn("本期焦点：1. 硅谷 CEO 联署", b_sum)
        self.assertIn("今天主要讨论 Agent 基建", b_sum)
        self.assertNotIn("这批推文来自", b_sum)

        builder_fullwidth_utc = """<b>🛠 AI Builder 日报 · 2026-11-13</b>

这批推文来自 2026-11-12 至 11-13（UTC），今天多位一线 Builder 集中探讨了 UI 重构。

<b>1. Vercel 探讨 UI 抽象</b>
"""
        b_fw = na.extract_summary(builder_fullwidth_utc, source="🛠️ AI Builder")
        self.assertTrue(b_fw.startswith("今天多位一线 Builder 集中探讨了 UI 重构"))
        self.assertNotIn("（UTC）", b_fw)

    def test_us_stock_combined_market_and_news_summary(self):
        us_doc = """<b>📊 美股收盘 & 加密行情 · 2026-11-14</b>
📈 <b>核心指数</b>：标普500 6012 (+0.42%) | 纳指 19100 (+0.65%)
🪙 <b>加密核心 24h</b>：BTC $91,200 (+2.1%) | ETH $3,150 (+1.4%)
🌡️ <b>加密情绪</b>：恐贪指数 72 (贪婪)
· <b>信号灯</b>：🟢 温和偏多 — 权重股轮动支撑

---

<b>📋 美股要闻 · 2026-11-14</b>

<b>⚡ 30秒速览</b>

- 要闻一：美联储会议纪要偏鸽
- 要闻二：科技巨头资本开支维持高位

<a href="https://cnbc.com/1"><b>详细标题</b></a>
"""
        us_sum = na.extract_summary(us_doc, source="🗽 美股与加密")
        self.assertTrue(us_sum.startswith("【美股盘面】信号灯：🟢 温和偏多"))
        self.assertIn("BTC $91,200 (+2.1%) (恐贪指数 72 (贪婪))", us_sum)
        self.assertIn("要闻一：美联储会议纪要偏鸽", us_sum)
        self.assertIn("要闻二：科技巨头资本开支维持高位", us_sum)


class TestArchiveToNotionHttp(unittest.TestCase):
    def test_missing_api_key_returns_false_without_network(self):
        with patch.object(na, "get_notion_api_key", return_value=""), patch(
            "requests.Session.request"
        ) as mock_req:
            ok, msg = na.archive_to_notion("hello", "🤖 AI 产业日报", date_str="2026-11-14")
        self.assertFalse(ok)
        self.assertIn("NOTION_ARCHIVE_API_KEY", msg)
        mock_req.assert_not_called()

    def test_single_chunk_post_properties_and_http_400(self):
        query_empty = MagicMock(status_code=200)
        query_empty.json.return_value = {"results": []}
        ok_resp = MagicMock(status_code=200)
        ok_resp.json.return_value = {"id": "1234-5678", "url": "https://notion.so/12345678"}

        with patch.object(na, "get_notion_api_key", return_value="secret_test"), patch(
            "bot_utils.resolve_proxy", return_value=(None, "")
        ), patch("requests.Session.request", side_effect=[query_empty, ok_resp]) as mock_req, patch(
            "subprocess.run", side_effect=AssertionError("curl must not run")
        ):
            ok, url = na.archive_to_notion(
                "<b>📋 AI 产业日报 · 2026-11-14</b>\n\n<a href=\"https://a.com\"><b>头条</b></a>\n\n⭐⭐⭐⭐⭐ #AI\n\n📄 The Details：\n细节。",
                "🤖 AI 产业日报",
                date_str="2026-11-14",
            )
        self.assertTrue(ok)
        self.assertEqual(url, "https://notion.so/12345678")
        self.assertEqual(mock_req.call_count, 2)
        self.assertEqual(
            mock_req.call_args_list[0].args[:2],
            ("POST", f"https://api.notion.com/v1/databases/{na.DEFAULT_DATABASE_ID}/query"),
        )
        kwargs = mock_req.call_args_list[1].kwargs
        props = kwargs["json"]["properties"]
        self.assertEqual(props["日期"]["date"]["start"], "2026-11-14")
        self.assertEqual(props["周次"]["select"]["name"], "2026-W46")
        self.assertEqual(props["信源"]["select"]["name"], "🤖 AI 产业日报")
        self.assertEqual(props["类型"]["select"]["name"], "日报")
        self.assertEqual(props["标题"]["title"][0]["text"]["content"], "[AI 产业日报] 2026-11-14 行业观察")

        bad_resp = MagicMock(status_code=400, text="validation error")
        with patch.object(na, "get_notion_api_key", return_value="secret_test"), patch(
            "bot_utils.resolve_proxy", return_value=(None, "")
        ), patch("requests.Session.request", side_effect=[query_empty, bad_resp]):
            ok2, msg2 = na.archive_to_notion("body", "🤖 AI 产业日报", date_str="2026-11-14")
        self.assertFalse(ok2)
        self.assertIn("HTTP 400", msg2)

    def test_gt_90_blocks_splits_post_and_patch(self):
        draft = "\n\n".join(f"第 {n} 段测试文本" for n in range(1, 106))
        query_empty = MagicMock(status_code=200)
        query_empty.json.return_value = {"results": []}
        resp_post = MagicMock(status_code=200)
        resp_post.json.return_value = {"id": "page-abc", "url": "https://notion.so/pageabc"}
        resp_patch = MagicMock(status_code=200)
        resp_patch.json.return_value = {"results": []}

        with patch.object(na, "get_notion_api_key", return_value="secret_test"), patch(
            "bot_utils.resolve_proxy", return_value=(None, "")
        ), patch("requests.Session.request", side_effect=[query_empty, resp_post, resp_patch]) as mock_req, patch(
            "time.sleep"
        ):
            ok, url = na.archive_to_notion(draft, "🤖 AI 产业日报", date_str="2026-11-14")

        self.assertTrue(ok)
        self.assertEqual(url, "https://notion.so/pageabc")
        self.assertEqual(mock_req.call_count, 3)
        self.assertEqual(
            mock_req.call_args_list[0].args[:2],
            ("POST", f"https://api.notion.com/v1/databases/{na.DEFAULT_DATABASE_ID}/query"),
        )
        self.assertEqual(mock_req.call_args_list[1].args[:2], ("POST", "https://api.notion.com/v1/pages"))
        self.assertEqual(len(mock_req.call_args_list[1].kwargs["json"]["children"]), 90)
        self.assertEqual(
            mock_req.call_args_list[2].args[:2],
            ("PATCH", "https://api.notion.com/v1/blocks/page-abc/children"),
        )
        self.assertEqual(len(mock_req.call_args_list[2].kwargs["json"]["children"]), 15)

    def test_upsert_updates_in_place_preserving_page_id_and_archiving_dups(self):
        calls = []

        def fake_req(method, url, **kwargs):
            calls.append((method, url, kwargs.get("json")))
            resp = MagicMock(status_code=200)
            if url.endswith("/query"):
                resp.json.return_value = {
                    "results": [
                        {"id": "page-new", "url": "https://notion.so/pagenew", "archived": False},
                        {"id": "page-old-dup", "url": "https://notion.so/pagedup", "archived": False},
                    ]
                }
            elif method == "GET" and "/blocks/page-new/children" in url:
                if "start_cursor=c2" not in url:
                    resp.json.return_value = {
                        "results": [{"id": "old-blk-1"}],
                        "has_more": True,
                        "next_cursor": "c2",
                    }
                else:
                    resp.json.return_value = {
                        "results": [{"id": "old-blk-2"}],
                        "has_more": False,
                        "next_cursor": None,
                    }
            elif method == "PATCH" and url.endswith("/blocks/page-new/children"):
                resp.json.return_value = {"results": [{"id": "new-blk-1"}]}
            elif method == "DELETE" and url.endswith("/blocks/old-blk-2"):
                # Verify harmless 404/already archived handling on second old block
                resp = MagicMock(status_code=404, text='{"code": "object_not_found"}')
            else:
                resp.json.return_value = {"id": "page-new"}
            return resp

        with patch.object(na, "get_notion_api_key", return_value="secret_test"), patch(
            "bot_utils.resolve_proxy", return_value=(None, "")
        ), patch("requests.Session.request", side_effect=fake_req), patch("time.sleep"):
            ok, url = na.archive_to_notion("新段落内容", "🤖 AI 产业日报", date_str="2026-11-14")

        self.assertTrue(ok)
        self.assertEqual(url, "https://notion.so/pagenew")
        endpoints = [(m, u) for m, u, _ in calls]
        self.assertFalse(any(m == "POST" and u.endswith("/v1/pages") for m, u in endpoints))
        patch_children_idx = endpoints.index(("PATCH", "https://api.notion.com/v1/blocks/page-new/children"))
        del1_idx = endpoints.index(("DELETE", "https://api.notion.com/v1/blocks/old-blk-1"))
        del2_idx = endpoints.index(("DELETE", "https://api.notion.com/v1/blocks/old-blk-2"))
        self.assertLess(patch_children_idx, del1_idx)
        self.assertLess(patch_children_idx, del2_idx)
        self.assertIn(
            ("PATCH", "https://api.notion.com/v1/pages/page-old-dup", {"archived": True}),
            calls,
        )

    def test_retries_http_429_respecting_retry_after(self):
        query_empty = MagicMock(status_code=200)
        query_empty.json.return_value = {"results": []}
        rate_limited = MagicMock(status_code=429, headers={"Retry-After": "2"}, text="rate_limited")
        ok_resp = MagicMock(status_code=200)
        ok_resp.json.return_value = {"id": "page-429", "url": "https://notion.so/page429"}

        with patch.object(na, "get_notion_api_key", return_value="secret_test"), patch(
            "bot_utils.resolve_proxy", return_value=(None, "")
        ), patch("requests.Session.request", side_effect=[query_empty, rate_limited, ok_resp]) as mock_req, patch(
            "time.sleep"
        ) as mock_sleep:
            ok, url = na.archive_to_notion("正文", "🤖 AI 产业日报", date_str="2026-11-14")

        self.assertTrue(ok)
        self.assertEqual(url, "https://notion.so/page429")
        self.assertEqual(mock_req.call_count, 3)
        mock_sleep.assert_called_once_with(2.0)

    def test_append_chunk_failure_returns_false_and_preserves_old_blocks_on_update(self):
        draft_120 = "\n\n".join(f"第 {n} 段测试内容" for n in range(1, 121))

        # Case 1: Create path where chunk 2 (>90) hits persistent 500 -> returns False
        create_calls = []

        def fake_create_fail(method, url, **kwargs):
            create_calls.append((method, url))
            if url.endswith("/query"):
                r = MagicMock(status_code=200)
                r.json.return_value = {"results": []}
                return r
            if method == "POST" and url.endswith("/v1/pages"):
                r = MagicMock(status_code=200)
                r.json.return_value = {"id": "page-create", "url": "https://notion.so/pagecreate"}
                return r
            return MagicMock(status_code=500, text="server error")

        with patch.object(na, "get_notion_api_key", return_value="secret_test"), patch(
            "bot_utils.resolve_proxy", return_value=(None, "")
        ), patch("requests.Session.request", side_effect=fake_create_fail), patch("time.sleep"):
            ok_c, msg_c = na.archive_to_notion(draft_120, "🤖 AI 产业日报", date_str="2026-11-14")
        self.assertFalse(ok_c)
        self.assertIn("后续区块追加失败", msg_c)
        # Chunk 2 retried 4 times
        self.assertEqual(sum(1 for m, u in create_calls if m == "PATCH" and "/blocks/" in u), 4)

        # Case 2: Update path where chunk 1 succeeds and chunk 2 returns 400 -> rolls back chunk 1, keeps old-1
        update_calls = []
        chunk_idx = 0

        def fake_update_fail(method, url, **kwargs):
            nonlocal chunk_idx
            update_calls.append((method, url))
            r = MagicMock(status_code=200)
            if url.endswith("/query"):
                r.json.return_value = {"results": [{"id": "page-upd", "url": "https://notion.so/pageupd"}]}
                return r
            if method == "GET":
                r.json.return_value = {"results": [{"id": "old-keep-1"}], "has_more": False}
                return r
            if method == "PATCH" and url.endswith("/v1/pages/page-upd"):
                r.json.return_value = {"id": "page-upd"}
                return r
            if method == "PATCH" and url.endswith("/v1/blocks/page-upd/children"):
                chunk_idx += 1
                if chunk_idx == 1:
                    r.json.return_value = {"results": [{"id": "new-partial-1"}]}
                    return r
                return MagicMock(status_code=400, text="invalid block")
            r.json.return_value = {}
            return r

        with patch.object(na, "get_notion_api_key", return_value="secret_test"), patch(
            "bot_utils.resolve_proxy", return_value=(None, "")
        ), patch("requests.Session.request", side_effect=fake_update_fail), patch("time.sleep"):
            ok_u, msg_u = na.archive_to_notion(draft_120, "🤖 AI 产业日报", date_str="2026-11-14")
        self.assertFalse(ok_u)
        self.assertIn("更新追加区块失败", msg_u)
        self.assertIn(("DELETE", "https://api.notion.com/v1/blocks/new-partial-1"), update_calls)
        self.assertNotIn(("DELETE", "https://api.notion.com/v1/blocks/old-keep-1"), update_calls)

    def test_curl_fallback_parses_headers_for_bodyless_get_and_delete(self):
        curl_steps = []

        def fake_curl(cmd, input=None, text=None, capture_output=None):
            method = cmd[cmd.index("-X") + 1]
            url = cmd[cmd.index("-X") + 2]
            hdr_file = Path(cmd[cmd.index("-D") + 1])
            has_body = "--data-binary" in cmd
            curl_steps.append((method, url, has_body))

            # Query: return 1 existing page
            if url.endswith("/query"):
                hdr_file.write_text("HTTP/1.1 200 Connection established\r\n\r\nHTTP/2 200\r\n\r\n", encoding="utf-8")
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps({"results": [{"id": "p-curl", "url": "https://notion.so/pcurl"}]}) + "\n200",
                    stderr="",
                )
            # First GET returns proxy CONNECT + 429 Retry-After: 1; second GET succeeds bodyless
            if method == "GET":
                get_count = sum(1 for m, _, _ in curl_steps if m == "GET")
                if get_count == 1:
                    hdr_file.write_text(
                        "HTTP/1.1 200 Connection established\r\n\r\nHTTP/2 429 \r\nretry-after: 1\r\n\r\n",
                        encoding="utf-8",
                    )
                    return MagicMock(returncode=0, stdout='{"message":"rate_limited"}\n429', stderr="")
                hdr_file.write_text("HTTP/2 200\r\n\r\n", encoding="utf-8")
                return MagicMock(
                    returncode=0,
                    stdout=json.dumps({"results": [{"id": "old-c1"}], "has_more": False}) + "\n200",
                    stderr="",
                )
            hdr_file.write_text("HTTP/2 200\r\n\r\n", encoding="utf-8")
            return MagicMock(returncode=0, stdout=json.dumps({"results": [{"id": "new-c1"}]}) + "\n200", stderr="")

        with patch.object(na, "get_notion_api_key", return_value="secret_test"), patch(
            "bot_utils.resolve_proxy", return_value=("http://127.0.0.1:1082", "")
        ), patch("os.path.exists", return_value=True), patch(
            "requests.Session.request", side_effect=na.requests.RequestException("LibreSSL EOF")
        ), patch("subprocess.run", side_effect=fake_curl), patch("time.sleep") as mock_sleep:
            ok, url = na.archive_to_notion("正文", "🤖 AI 产业日报", date_str="2026-11-14")

        self.assertTrue(ok)
        self.assertEqual(url, "https://notion.so/pcurl")
        # Both GET and DELETE ran bodyless via curl, and GET 429 slept 1.0s
        self.assertIn(("GET", "https://api.notion.com/v1/blocks/p-curl/children?page_size=100", False), curl_steps)
        self.assertIn(("DELETE", "https://api.notion.com/v1/blocks/old-c1", False), curl_steps)
        mock_sleep.assert_any_call(1.0)


if __name__ == "__main__":
    unittest.main()
