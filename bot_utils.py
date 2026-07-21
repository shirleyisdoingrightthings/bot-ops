"""
bot_utils.py — 两个 Bot（Crypto Daily Bot / AI Daily News Bot）共用的工具库。

⚠️ 说明：本文件曾因游离在版本控制之外、换电脑后丢失，故由 Claude 依据 crypto_report.py
与 daily_report.py 的实际调用契约重建。现已纳入 git 仓库
（~/Desktop/bot_ops，remote: github.com/shirleyisdoingrightthings/bot-ops）——
改动请务必 commit 并 push，勿再让它游离在仓库外。两个 bot 通过
sys.path.insert(~/Desktop/bot_ops/shared) 共用本文件。

导出函数：
  - sanitize_html(text)            把 AI 输出清洗为 Telegram 可接受的 HTML
  - with_retry(...)                带退避的重试装饰器工厂
  - fetch_rss(feed_url, limit)     抓取并解析 RSS，返回 entries 列表（失败返回 []）
  - parse_entry_date(entry)        解析 RSS 条目时间，返回 UTC tz-aware datetime 或 None
  - already_ran_today(log_file)    今天是否已成功跑过（日志含当天 [OK] 记录）
  - fetch_article_text(url)        best-effort 抓文章正文全文（零依赖），失败/过短返回 ""
"""

from __future__ import annotations

import os
import re
import html
import json
import time
import functools
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser


# ───────────────────────────────────────────────
# 1) sanitize_html — Telegram HTML 安全清洗
# ───────────────────────────────────────────────
# Telegram 的 parse_mode=HTML 只接受有限的标签白名单，其余的 < > & 必须转义，
# 否则整条消息会因 "can't parse entities" 被拒。策略：先把白名单标签原样暂存，
# 转义其余文本，再把标签还原回去。

_ALLOWED_TAGS = r"(?:b|strong|i|em|u|ins|s|strike|del|code|pre|a|tg-spoiler|blockquote)"
# 匹配白名单的开/闭标签（属性中不含尖括号，足以覆盖 <a href="...">）
_TAG_RE = re.compile(rf"</?\s*{_ALLOWED_TAGS}(?:\s+[^<>]*?)?>", re.IGNORECASE)
_SENTINEL_RE = re.compile("\x00(\\d+)\x00")


def sanitize_html(text: str) -> str:
    if not text:
        return ""

    stash: list[str] = []

    def _hold(m: re.Match) -> str:
        stash.append(m.group(0))
        return f"\x00{len(stash) - 1}\x00"

    # 1. 暂存白名单标签
    tmp = _TAG_RE.sub(_hold, text)
    # 2. 转义剩余文本中的 & < >（保留引号）
    tmp = html.escape(tmp, quote=False)
    # 3. 还原标签
    tmp = _SENTINEL_RE.sub(lambda m: stash[int(m.group(1))], tmp)
    return tmp


# ───────────────────────────────────────────────
# 2) with_retry — 重试装饰器工厂
# ───────────────────────────────────────────────
# 用法：@with_retry(max_retries=2, base_delay=5, exceptions=(Exception,))
# 首次调用失败后最多再重试 max_retries 次，第 n 次重试前 sleep(base_delay * n)。
# 全部失败则抛出最后一次异常。

def with_retry(max_retries: int = 3, base_delay: float = 5,
               exceptions: tuple = (Exception,)):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            attempt = 0
            while True:
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:  # noqa: F841
                    attempt += 1
                    if attempt > max_retries:
                        raise
                    time.sleep(base_delay * attempt)
        return wrapper
    return decorator


# ───────────────────────────────────────────────
# 3) fetch_rss — 抓取并解析 RSS
# ───────────────────────────────────────────────
# requests 默认 trust_env=True，会自动读取 HTTP_PROXY / HTTPS_PROXY 环境变量，
# 因此代理由调用方（脚本/launchd plist）通过环境变量注入即可。
# 单个源失败时返回 []，避免一个坏源拖垮整次运行。

_RSS_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def fetch_rss(feed_url: str, limit: int = 10, timeout: int = 30,
              retries: int = 2) -> list:
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(feed_url, headers={"User-Agent": _RSS_UA},
                                timeout=timeout)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            entries = list(parsed.entries or [])
            return entries[:limit] if limit else entries
        except Exception as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
    print(f"[bot_utils] fetch_rss 失败：{feed_url} → {last_exc}")
    return []


# ───────────────────────────────────────────────
# 4) parse_entry_date — 解析条目时间为 UTC datetime
# ───────────────────────────────────────────────
# feedparser 的 *_parsed 字段是 UTC 的 time.struct_time。调用方用
# datetime.now(timezone.utc) 做比较，故这里返回 tz-aware（UTC）datetime。

def parse_entry_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return None


# ───────────────────────────────────────────────
# 5) already_ran_today — 当天幂等检查
# ───────────────────────────────────────────────
# write_log 写入格式为 "{%Y-%m-%d %H:%M}  [{status}]  {message}"，
# 因此「今天已成功」= 日志中存在以今天日期开头且含 [OK] 的行。
# 环境变量 FORCE_RUN=1 可强制绕过（始终返回 False）。

def already_ran_today(log_file, ok_marker: str = "[OK]") -> bool:
    if os.getenv("FORCE_RUN") == "1":
        return False
    try:
        path = Path(log_file)
        if not path.exists():
            return False
        today = datetime.now().strftime("%Y-%m-%d")
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(today) and ok_marker in line:
                    return True
    except Exception:
        return False
    return False


# ───────────────────────────────────────────────
# 6) fetch_article_text — best-effort 抓正文全文（零依赖）
# ───────────────────────────────────────────────
# 供 build context 用：给写稿提供比 RSS 摘要更丰富的原料。
# 策略：requests 抓 HTML（trust_env 自动走代理 + 浏览器 UA）→ 优先取 JSON-LD 的
# articleBody（最干净），退而用 <p> 标签启发式。任何失败/正文过短都返回 ""，
# 由调用方回退到 RSS 摘要。纯标准库 + requests，不引入 lxml/bs4/trafilatura
# （系统 python 3.9 装不动，且会增加维护面）。

_ARTICLE_UA = _RSS_UA  # 复用上面的浏览器 UA

_ARTICLE_BLOCK_RE  = re.compile(r"(?is)<(script|style|noscript|nav|header|footer|aside|form)\b.*?</\1>")
_ARTICLE_P_RE      = re.compile(r"(?is)<p[ >].*?</p>")
_ARTICLE_TAG_RE    = re.compile(r"(?s)<[^>]+>")
_ARTICLE_WS_RE     = re.compile(r"\s+")
_ARTICLE_JSONLD_RE = re.compile(
    r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
)


def _article_norm(text: str) -> str:
    return _ARTICLE_WS_RE.sub(" ", html.unescape(text)).strip()


def _article_from_jsonld(raw_html: str) -> str:
    """从所有 JSON-LD 块里挖出最长的 articleBody。"""
    best = ""
    for block in _ARTICLE_JSONLD_RE.findall(raw_html):
        try:
            data = json.loads(block.strip())
        except Exception:
            continue
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                body = node.get("articleBody")
                if isinstance(body, str) and len(body) > len(best):
                    best = body
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return _article_norm(best)


def _article_from_paragraphs(raw_html: str) -> str:
    """去掉脚本/导航等噪声后，拼接有实质长度的 <p> 文本。"""
    body = _ARTICLE_BLOCK_RE.sub(" ", raw_html)
    paras = []
    for p in _ARTICLE_P_RE.findall(body):
        t = _article_norm(_ARTICLE_TAG_RE.sub(" ", p))
        if len(t) >= 40:          # 滤掉导航/版权行等短碎片
            paras.append(t)
    return " ".join(paras).strip()


def fetch_article_text(url: str, timeout: int = 10,
                       max_chars: int = 1800, min_chars: int = 300) -> str:
    """best-effort 抓文章正文；失败/被墙/正文过短一律返回 ""（调用方回退 RSS 摘要）。"""
    if not url:
        return ""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": _ARTICLE_UA,
                     "Accept-Language": "en-US,en;q=0.9"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return ""
        raw = resp.text
    except Exception:
        return ""

    text = _article_from_jsonld(raw)
    if len(text) < min_chars:
        alt = _article_from_paragraphs(raw)
        if len(alt) > len(text):
            text = alt
    if len(text) < min_chars:
        return ""
    return text[:max_chars]
