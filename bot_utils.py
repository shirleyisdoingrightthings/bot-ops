"""
bot_utils.py — 三个 Bot（AI Daily News / Crypto Daily / US Stock）共用的工具库。

⚠️ 说明：本文件曾因游离在版本控制之外、换电脑后丢失，故由 Claude 依据各 bot 主脚本
的实际调用契约重建。现已纳入独立 git 仓库（remote: github.com/shirleyisdoingrightthings/bot-ops）
——改动请务必 commit 并 push，勿再让它游离在仓库外。

三个 bot 通过 `sys.path.insert(Path(__file__).resolve().parent.parent / "shared")`
从脚本自身位置推导本目录，因此整个 bots 文件夹搬到任何位置都不需要改路径。

导出函数：
  基础
  - sanitize_html(text)            把 AI 输出清洗为受控的 HTML 中间格式
  - with_retry(...)                带退避的重试装饰器工厂
  - fetch_rss(feed_url, limit)     抓取并解析 RSS，返回 entries 列表（失败返回 []）
  - parse_entry_date(entry)        解析 RSS 条目时间，返回 UTC tz-aware datetime 或 None
  - already_ran_today(log_file)    今天是否已成功跑过（日志含当天 [OK] 记录）
  取材
  - fetch_article_text(url)        best-effort 抓文章正文全文（零依赖），失败/过短返回 ""
  跨天去重
  - url_key(url)                   URL 归一化（去 query/fragment/尾斜杠、转小写）
  - load_sent_urls(path)           读出最近 N 天已推送过的 URL 键集合
  - record_sent_urls(path, urls)   记录本次实际推送的 URL 并按保留期裁剪
  - extract_hrefs(html_text)       从稿件里抽出 <a href="..."> 的 URL
  选题过滤（泛源闸门，垂直源不过闸）
  - is_ai_relevant(title, summary)      AI 相关性（AI Daily News Bot 用）
  - is_market_relevant(title, summary)  美股/宏观相关性（US Stock Bot 用）
  推送与监控（飞书自定义机器人 webhook）
  - html_to_lark_md(text)          HTML 稿件 → 飞书卡片 markdown 行列表
  - paginate_feishu(lines)         按 20KB 请求体上限切分 + (n/N) 页码
  - send_feishu(text, ...)         整套推送：转换 → 分页 → 带签名 POST（直连不走代理）
  - update_zero_streak(...)        RSS 源连续零产追踪，达阈值返回建议淘汰的源
  - resolve_proxy(configured)      代理端口自愈，返回 (可用代理, 是否切换)
  主脚本公共构件（三个 bot 曾各抄一份）
  - make_logger(log, jsonl)        返回该 bot 的 write_log(status, msg, metrics)
  - make_pending_saver(cache)      返回该 bot 的 save_pending(messages)
  - proxy_ok(configured, session)  代理预检 + 端口自愈，返回 (是否放行, 生效代理)
  - emit_fetch_output(lines, path) fetch 的 stdout 一次性输出并落盘一份
"""

from __future__ import annotations

import os
import re
import sys
import html
import json
import time
import hmac
import base64
import hashlib
import functools
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser


# ───────────────────────────────────────────────
# 1) sanitize_html — HTML 中间格式的安全清洗
# ───────────────────────────────────────────────
# 稿件用一小撮 HTML 标签（实际只有 <b> 和 <a href>）承载格式，正文里出现的裸
# < > & 必须转义，否则会被后面的标签解析吃掉——"市值 < 10 亿" 这种写法会连着
# 后面一大段一起被当成标签。策略：先把白名单标签原样暂存，转义其余文本，
# 再把标签还原回去。send_feishu 那边做的 unescape 正好是本函数的逆运算。

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


# ───────────────────────────────────────────────
# 7) 跨天去重 — 记住"真正推送过"的 URL
# ───────────────────────────────────────────────
# 背景：三个 bot 的时间窗口（AI 24h / Crypto 3 天 / 美股 48h）都可能让同一条新闻在连续
# 多天进入 context——各脚本内的 seen_urls 只在单次运行内有效，拦不住跨天重复。
# 策略：send 成功后，从稿件里抽出实际用到的 <a href> 记进 logs/sent_urls.json；
# 下次 fetch 时据此排除。记录点选在 send 成功之后而不是 fetch 时，这样发送失败
# 的那一批不会被误标成"已播"。

SENT_URLS_KEEP_DAYS = 7

_HREF_RE = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def url_key(url: str) -> str:
    """归一化 URL 作为去重键：小写、去 query/fragment、去尾斜杠。

    RSS 里同一篇文章的链接常带 utm_* 参数，且不同源指向同一文章时参数各异，
    所以只用 scheme+host+path 作为身份。"""
    if not url:
        return ""
    u = url.strip().split("#", 1)[0].split("?", 1)[0]
    return u.rstrip("/").lower()


def load_sent_urls(path, keep_days: int = SENT_URLS_KEEP_DAYS) -> set[str]:
    """读出保留期内已推送的 URL 键集合；文件不存在/损坏一律返回空集（不阻断出稿）。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    cutoff = _days_ago_str(keep_days)
    return {k for k, d in data.items() if isinstance(d, str) and d >= cutoff}


def record_sent_urls(path, urls, keep_days: int = SENT_URLS_KEEP_DAYS) -> int:
    """把本次实际推送的 URL 记入档案并裁掉过期条目，返回归档总量。

    写档失败只告警不抛错——去重是增强项，不能让它把已经发成功的流程带崩。"""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    today = datetime.now().strftime("%Y-%m-%d")
    for u in urls:
        k = url_key(u)
        if k:
            data[k] = today

    cutoff = _days_ago_str(keep_days)
    data = {k: d for k, d in data.items() if isinstance(d, str) and d >= cutoff}

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] sent_urls 写入失败: {e}")
    return len(data)


def _days_ago_str(days: int) -> str:
    from datetime import timedelta
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")


def extract_hrefs(html_text: str) -> list[str]:
    """从稿件中抽出所有 <a href="..."> 的 URL（只要 http/https）。"""
    if not html_text:
        return []
    return [u for u in _HREF_RE.findall(html_text) if u.lower().startswith("http")]


# ───────────────────────────────────────────────
# 8) AI 相关性闸门 — 只给泛科技源用
# ───────────────────────────────────────────────
# 背景：engadget.com/rss.xml 这类全站源里大量条目与 AI 无关（游戏机 demo、
# Steam 功能更新、影视并购），白白占掉抓取额度并污染写稿素材。垂直 AI 源
# （theverge AI 频道、the-decoder 等）不过这道闸，避免误伤不含关键词的正当选题。

_AI_KEYWORDS = (
    "ai", "a.i.", "artificial intelligence", "machine learning", "deep learning",
    "neural", "llm", "large language model", "chatbot", "generative",
    "openai", "chatgpt", "gpt", "anthropic", "claude", "gemini", "deepmind",
    "llama", "mistral", "moonshot", "deepseek", "qwen", "copilot", "midjourney",
    "stable diffusion", "hugging face", "nvidia", "gpu", "tpu", "data center",
    "datacenter", "robot", "humanoid", "autonomous", "self-driving",
    "transformer model", "inference", "training run", "agentic",
)

# 单独成词才算命中的短词，避免 "ai" 匹配到 "said/certain"、"gpu" 之外的噪音
_AI_WORD_RE = re.compile(
    r"\b(?:ai|a\.i\.|llm|gpt|gpu|tpu|robot|robots|robotics|humanoid|neural|agentic)\b",
    re.IGNORECASE,
)


def is_ai_relevant(title: str, summary: str = "") -> bool:
    """判断一条泛科技源新闻是否与 AI 相关。标题或摘要命中即通过。"""
    blob = f"{title or ''} {summary or ''}".lower()
    if not blob.strip():
        return False
    if _AI_WORD_RE.search(blob):
        return True
    return any(kw in blob for kw in _AI_KEYWORDS if " " in kw or len(kw) > 4)


# ───────────────────────────────────────────────
# 9) 飞书推送 — HTML 稿件 → 卡片 markdown → 自定义机器人 webhook
# ───────────────────────────────────────────────
# 2026-08 从 Telegram 迁过来时踩的坑，按顺序记下来，别再走回头路：
#
#   ① 先选了「富文本 post」，理由是文档写着 text/a 标签支持 style:["bold"]，
#      正好对上稿件里 <a href><b>标题</b></a> 的加粗超链接。真机一发就被拒：
#      code=19002 "unknown content value"。style 那套是**应用发消息 API** 的能力，
#      自定义机器人 webhook 不认。post 里的 md 标签同样不认（code=10002）。
#   ② post 发得出去，但只能出纯文本 + 不加粗的链接，章节标题会全部失去层次。
#   ③ 最终用「卡片 2.0 + markdown 元素」。真机实测两种嵌套写法只有一种有效：
#        **[文字](url)**  → 又蓝又粗 ✅   ← 加粗超链接只能这么写
#        [**文字**](url)  → 不生效 ❌
#      顺序反了就白写，改这里之前先在真群里发一条对照消息确认。
#
# 关于转义：飞书文档说命中 markdown 语法的字符要转成 &#42; 这类实体。真机实测裸
# 星号、下划线、尖括号、& 全都原样显示；又扫了 14 份真实存档共 8 万字正文，唯一
# 命中的是 5 处 [#159] 这种方括号（CommonMark 里不跟 (url) 的方括号是字面量，无害）。
# 加上 prompt 本来就禁止稿件出现 Markdown 符号，所以这里**不做转义**——盲目转义有
# 反向风险：万一实体不被解码，群里就会出现一串字面的 &#42;。哪天稿件风格真变了，
# 在 _md_plain 里加一层即可。

# 自定义机器人 webhook 的请求体上限 20KB（比应用发消息的 30KB 更严）。
# 按 UTF-8 字节算，且 body 用 ensure_ascii=False 序列化后手动编码发送：
# requests 的 json= 参数默认 ensure_ascii=True，一个汉字会膨胀成 \uXXXX 六个 ASCII
# 字节，同一份稿子要多切一倍的消息。
FEISHU_BODY_LIMIT = 20 * 1024
# 给卡片外壳、timestamp+sign、页码行和 JSON 转义留的余量
_FEISHU_ENVELOPE_BUDGET = 2048

FEISHU_WEBHOOK_ENV = "FEISHU_WEBHOOK"
FEISHU_SECRET_ENV  = "FEISHU_SECRET"
# 飞书限频 5 次/秒；页与页之间歇一下，顺便躲开整点前后突发的 11232 限流
_FEISHU_PAGE_GAP_S = 0.5

_A_RE          = re.compile(r'<a\s+[^>]*?href\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a\s*>', re.I | re.S)
_B_RE          = re.compile(r'<\s*(b|strong)\s*>(.*?)</\s*\1\s*>', re.I | re.S)
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")


def _md_plain(fragment: str) -> str:
    """去掉残留标签、还原实体，得到可直接进 markdown 的文本。

    sanitize_html 把白名单之外的裸 < > & 转成了实体，这里 unescape 回来，
    二者互为逆运算——"市值 < 10 亿" 这类正文不会被当成标签吃掉。"""
    return html.unescape(_STRIP_TAGS_RE.sub("", fragment))


def _md_wrap(inner: str, left: str, right: str) -> str:
    """用 markdown 标记包住文本，但把首尾空白留在标记外面。

    CommonMark 要求标记必须紧贴非空白字符：`** 文字 **` 不会加粗，`**文字**` 才会。
    稿件里出现 <b> 文字 </b> 这种带空格的写法时，靠这一步救回来。"""
    core = inner.strip()
    if not core:
        return inner
    lead  = inner[:len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()):]
    return f"{lead}{left}{core}{right}{trail}"


def _md_bold_runs(fragment: str) -> str:
    """把不含链接的片段转成 markdown：<b>x</b> → **x**，其余原样。"""
    out, pos = [], 0
    for m in _B_RE.finditer(fragment):
        if m.start() > pos:
            out.append(_md_plain(fragment[pos:m.start()]))
        out.append(_md_wrap(_md_plain(m.group(2)), "**", "**"))
        pos = m.end()
    if pos < len(fragment):
        out.append(_md_plain(fragment[pos:]))
    return "".join(out)


def html_to_lark_md(text: str) -> list:
    """把 <b>/<a href> 方言的稿件转成飞书卡片 markdown 的行列表（一行一个元素）。

    href 只认 http/https，其余（javascript: 之类）连同标签一起降级成纯文本。"""
    lines = []
    for line in (text or "").split("\n"):
        buf, pos = [], 0
        for m in _A_RE.finditer(line):
            if m.start() > pos:
                buf.append(_md_bold_runs(line[pos:m.start()]))
            href  = html.unescape(m.group(1)).strip()
            inner = m.group(2)
            label = _md_plain(inner).strip()
            if label and href.lower().startswith(("http://", "https://")):
                link = f"[{label}]({href})"
                # 加粗超链接只有 **[文字](url)** 这一种写法有效，见本节开头
                buf.append(f"**{link}**" if _B_RE.search(inner) else link)
            elif label:
                buf.append(_md_bold_runs(inner))
            pos = m.end()
        if pos < len(line):
            buf.append(_md_bold_runs(line[pos:]))
        lines.append("".join(buf))
    return lines


def _card_payload(md: str, secret=None) -> dict:
    payload = {"msg_type": "interactive",
               "card": {"schema": "2.0",
                        "config": {"update_multi": True},
                        "body": {"elements": [{"tag": "markdown", "content": md}]}}}
    if secret:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _feishu_sign(ts, secret)
    return payload


def _payload_bytes(md: str) -> int:
    """整条请求体的实际字节数（签名字段按最长情形预留在 ENVELOPE 里）。"""
    return len(json.dumps(_card_payload(md), ensure_ascii=False).encode("utf-8"))


def _line_cost(line: str) -> int:
    """单行进 JSON 后的字节数。json.dumps 带的两个引号正好抵掉换行转义成 \\n 的开销。"""
    return len(json.dumps(line, ensure_ascii=False).encode("utf-8"))


def _greedy_pages(lines: list, budget: int) -> list:
    """按预算顺序塞行；切分点只落在行边界，保证单条新闻不会被腰斩。

    单行本身就超预算时不再细分，让它单独成页——宁可让飞书退这一条，
    也不要把一条新闻从中间劈开。"""
    pages, current, size = [], [], 0
    for line in lines:
        cost = _line_cost(line)
        if current and size + cost > budget:
            pages.append(current)
            current, size = [line], cost
        else:
            current.append(line)
            size += cost
    if current:
        pages.append(current)
    return pages


def paginate_feishu(lines: list, max_bytes: int = 0) -> list:
    """把 markdown 行切成若干条消息，返回每条的 markdown 正文。

    超过一条时每条顶部加加粗的 (n/N) 页码。分页做二次均衡：直接贪心塞满会留下一个
    很短的尾页（实测某天的 AI 日报切成 18.8KB + 0.5KB，第二条只有两行），所以先用
    上限求出最少页数 n，再从 总量/n 起步收紧预算，找出仍能装进 n 页的最小预算。
    最后按真实请求体大小复核一遍，超了就收紧重切——估算口径出偏差也不会发到飞书才发现。"""
    if not lines:
        return []
    if max_bytes <= 0:
        max_bytes = FEISHU_BODY_LIMIT - _FEISHU_ENVELOPE_BUDGET

    for _ in range(6):
        pages = _greedy_pages(lines, max_bytes)

        if len(pages) > 1:
            target = -(-sum(_line_cost(x) for x in lines) // len(pages))   # 向上取整
            while target <= max_bytes:
                balanced = _greedy_pages(lines, target)
                if len(balanced) <= len(pages):
                    pages = balanced
                    break
                target = int(target * 1.05) + 1   # 均分装不下（长行挤兑），放宽再试

        total = len(pages)
        out = ["\n".join(pg) for pg in pages] if total == 1 else \
              [f"**（{i}/{total}）**\n\n" + "\n".join(pg) for i, pg in enumerate(pages, 1)]

        if all(_payload_bytes(md) <= FEISHU_BODY_LIMIT for md in out):
            return out
        max_bytes = int(max_bytes * 0.9)          # 复核没过，收紧 10% 重来

    raise ValueError("分页失败：单行内容超出飞书 20KB 请求体上限，无法再切分")


# 发送走独立 Session 并显式关掉 trust_env：三个 bot 为了抓墙外 RSS 会把
# HTTP_PROXY/HTTPS_PROXY 写进 os.environ，而飞书本来就直连可达，绕代理只是
# 平白多一个故障点——代理挂掉的日子不该连播报一起停摆。
_FEISHU_SESSION = requests.Session()
_FEISHU_SESSION.trust_env = False
_FEISHU_SESSION.proxies = {}


def _feishu_sign(timestamp: str, secret: str) -> str:
    """签名 = HMAC-SHA256(key = "timestamp\n密钥", msg = 空) 再 base64。

    注意被签的是空消息体、密钥反而当 key 用，这是飞书的规定，不是笔误。"""
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


@with_retry(max_retries=3, base_delay=5, exceptions=(requests.RequestException,))
def _feishu_send_card(webhook: str, secret, md: str) -> None:
    # 手动序列化：ensure_ascii=False 让汉字按 UTF-8 占 3 字节而不是 \uXXXX 的 6 字节，
    # 与分页的字节预算保持同一口径
    body = json.dumps(_card_payload(md, secret), ensure_ascii=False).encode("utf-8")
    resp = _FEISHU_SESSION.post(
        webhook, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    )
    if not resp.ok:
        raise requests.RequestException(f"飞书 HTTP {resp.status_code}: {resp.text[:300]}")
    # 飞书失败时照样返回 HTTP 200，成败只看响应体里的 code/StatusCode
    try:
        data = resp.json()
    except Exception:
        raise requests.RequestException(f"飞书返回非 JSON：{resp.text[:300]}")
    code = data.get("code", data.get("StatusCode", 0))
    if code not in (0, "0"):
        msg = data.get("msg") or data.get("StatusMessage") or resp.text[:300]
        raise requests.RequestException(f"飞书返回错误 code={code}：{msg}")


def send_feishu(text: str, webhook: str = "", secret=None) -> int:
    """把一份（已 sanitize_html 的）稿件推送到飞书自定义机器人，返回实际发出的条数。

    webhook/secret 缺省从环境变量 FEISHU_WEBHOOK / FEISHU_SECRET 读取。
    没配 webhook 直接抛错、绝不静默吞掉——静默成功会让 health_check 也看不出问题。"""
    # 空稿直接返回：三个 bot 的 run_send 都已挡过一道，这里是兜底——
    # 宁可不发，也不要推一条空白消息出去。
    if not (text or "").strip():
        return 0

    hook = webhook or os.getenv(FEISHU_WEBHOOK_ENV, "")
    if not hook.startswith("http"):
        raise ValueError(
            f"未配置飞书 webhook（环境变量 {FEISHU_WEBHOOK_ENV}）——"
            "请在飞书群「设置 → 群机器人 → 添加机器人 → 自定义机器人」里取得地址")
    sec = secret if secret is not None else os.getenv(FEISHU_SECRET_ENV, "")

    pages = paginate_feishu(html_to_lark_md(text))
    for i, md in enumerate(pages):
        if i:
            time.sleep(_FEISHU_PAGE_GAP_S)
        _feishu_send_card(hook, sec or None, md)
    return len(pages)


# ───────────────────────────────────────────────
# 10) update_zero_streak — RSS 源连续零产追踪
# ───────────────────────────────────────────────
# "零产" = 该源当天抓到了条目、但过滤后一条都没进正文（过期/重复/已播/不相关）。
# 单日零产是慢更新源的常态，连续多日零产才说明这个源该换掉了。
# 本函数是 .zero_streak.json 的唯一写入方（fetch 阶段调用），health_check 只读不写，
# 避免两处各加一次导致天数翻倍。

def update_zero_streak(path, zero_sources, all_sources, threshold: int = 3) -> dict:
    """更新各源连续零产天数，返回达到阈值的 {源: 天数}（建议移除的源）。

    zero_sources 里的源天数 +1；本次有产出的源清零并移出档案。"""
    p = Path(path)
    try:
        streak = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(streak, dict):
            streak = {}
    except Exception:
        streak = {}

    zero = set(zero_sources)
    for s in zero:
        streak[s] = int(streak.get(s, 0)) + 1
    # 只保留本次仍然零产的源：有产出的清零，已从配置里删掉的也随之消失
    # （zero_sources 必然是 all_sources 的子集，故一个判断就够）
    streak = {s: n for s, n in streak.items() if s in zero}

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(streak, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] zero_streak 写入失败: {e}")

    return {s: n for s, n in sorted(streak.items()) if n >= threshold}


# ───────────────────────────────────────────────
# 11) resolve_proxy — 代理端口自愈
# ───────────────────────────────────────────────
# 背景：代理端口写死在 plist 里，用户换代理软件（Shadowrocket / Clash 等）
# 端口就变。历史上发生过两次（7897 → 7892 → 1082），最近一次让两个 bot
# 静默停摆 3 天——脚本只知道"配置的端口不通"，不会尝试任何替代。
#
# 策略：先试配置端口；不通则依次探测候选端口，命中即改用并告警。
# 探测用 gstatic 的 204 端点（轻量、无内容、境外可达性可靠）。

# 探测顺序即优先级：先 1082（当前 Shadowrocket），不通再试 7897。
# 每多一个候选最多多花一个 timeout（默认 5 秒），且只在配置端口已经不通时才走到。
PROXY_CANDIDATES = ("1082", "7897")
_PROBE_URL = "https://www.gstatic.com/generate_204"


def _probe(proxy_url: str, timeout: int = 5) -> bool:
    try:
        requests.get(_PROBE_URL, proxies={"http": proxy_url, "https": proxy_url},
                     timeout=timeout)
        return True
    except Exception:
        return False


def resolve_proxy(configured: str | None, candidates=PROXY_CANDIDATES,
                  timeout: int = 5) -> tuple[str | None, bool]:
    """返回 (可用代理 URL, 是否发生了端口切换)。

    - configured 为空 → (None, False)，调用方视为直连放行
    - configured 可用 → (configured, False)
    - configured 不通但某候选端口可用 → (该候选, True)
    - 全都不通 → (None, False)，调用方按代理不可用处理

    候选端口探测失败每个只花 timeout 秒上限，默认两个候选最多 10 秒。"""
    if not configured:
        return None, False

    if _probe(configured, timeout):
        return configured, False

    # 从配置值里拆出 scheme 与 host，只替换端口
    m = re.match(r"^(https?://)([^:/]+)(?::(\d+))?", configured.strip())
    scheme = m.group(1) if m else "http://"
    host = m.group(2) if m else "127.0.0.1"
    cur_port = m.group(3) if m else None

    for port in candidates:
        if port == cur_port:
            continue          # 已经试过配置端口了
        alt = f"{scheme}{host}:{port}"
        if _probe(alt, timeout):
            print(f"[bot_utils] 配置的代理 {configured} 不通，已自动改用 {alt}")
            return alt, True

    return None, False


# ───────────────────────────────────────────────
# 12) 美股相关性闸门 — 只给泛财经源用
# ───────────────────────────────────────────────
# 背景：Fortune 这类综合商业媒体的 feed 里，美股内容与英国政治、名人创业、
# 海外就业市场混在一起。垂直财经源（CNBC 财报线、MarketWatch 市场线）不过闸，
# 避免误伤标题不含关键词的正当选题。与 is_ai_relevant 是同一套设计。

_MKT_KEYWORDS = (
    # 市场与指数
    "stock", "stocks", "shares", "equity", "equities", "market", "markets",
    "s&p", "nasdaq", "dow jones", "russell", "index", "indices", "wall street",
    "bull market", "bear market", "rally", "selloff", "sell-off", "correction",
    # 公司财务
    "earnings", "revenue", "profit", "guidance", "outlook", "quarter",
    "dividend", "buyback", "valuation", "ipo", "merger", "acquisition",
    "takeover", "spinoff", "downgrade", "upgrade", "price target",
    # 宏观与货币
    "federal reserve", "fed ", "interest rate", "rate cut", "rate hike",
    "inflation", "cpi", "jobs report", "payrolls", "gdp", "recession",
    "treasury", "yield", "bond", "dollar", "tariff",
    # 汇率与大宗（日元干预、油价这类宏观题材常不含"stock/market"字样）
    "yen", "euro", "currency", "currencies", "forex", "exchange rate",
    "central bank", "intervention", "devalua",
    "oil price", "crude", "brent", "opec", "commodity", "commodities",
    "gold price", "barrel",
    # 投资主体
    "investor", "investors", "hedge fund", "etf", "portfolio", "analyst",
    "nyse", "sec filing", "shareholder", "ceo", "cfo",
)

# 单独成词才算命中的短词，避免 "fed" 匹配到 "federal/feed"
_MKT_WORD_RE = re.compile(
    r"\b(?:fed|ipo|etf|sec|nyse|cpi|gdp|eps|ceo|cfo|q[1-4]|oil|gas|yen)\b",
    re.IGNORECASE)
# 连续 2-5 个大写字母且独立成词 —— 股票代码的形态（NVDA、AAPL、TSLA）
_TICKER_RE = re.compile(r"(?<![A-Za-z])[A-Z]{2,5}(?![A-Za-z])")


def is_market_relevant(title: str, summary: str = "") -> bool:
    """判断一条泛财经源新闻是否与美股/宏观市场相关。标题或摘要命中即通过。"""
    blob = f"{title or ''} {summary or ''}"
    if not blob.strip():
        return False
    low = blob.lower()
    if _MKT_WORD_RE.search(low):
        return True
    if any(kw in low for kw in _MKT_KEYWORDS):
        return True
    # 标题里出现股票代码形态的全大写词也算（排除常见非代码缩写）
    _NOT_TICKER = {"US", "UK", "EU", "AI", "UN", "TV", "PM", "AM", "CEO", "CFO", "NEW"}
    return any(t not in _NOT_TICKER for t in _TICKER_RE.findall(title or ""))


# ───────────────────────────────────────────────
# 13) 主脚本公共构件 — 三个 bot 逐字重复的那几块
# ───────────────────────────────────────────────
# 背景：write_log / save_pending / _proxy_ok 三份逐字相同（_proxy_ok 已经开始漂移：
# us stock 版与另两份不一致），run_fetch 的收尾也是同构的。每加一个 bot 就再抄一遍，
# 且抄完各自演化。这里把它们收进共享层，各 bot 只留一行绑定。
#
# 用工厂函数而不是"多传两个路径参数"，是为了让各 bot 的调用点一个字都不用改
# ——write_log("WARN", ...) 在三个脚本里共有 22 处。

def make_logger(log_file, jsonl_file):
    """返回绑定到指定路径的 write_log(status, message, metrics=None)。

    行格式 "{%Y-%m-%d %H:%M}  [{status}]  {message}"，与 already_ran_today 的
    当天幂等判断相互约定，不要改。metrics 非空时额外追加一行 JSONL 供 health_check 读。
    注意 print(line) 走 stdout：fetch 模式下这会混进 marker 流，属既有行为，
    routine 靠 marker 解析不受影响，这里保持原样不动。"""
    log_file, jsonl_file = Path(log_file), Path(jsonl_file)

    def write_log(status: str, message: str, metrics: dict = None) -> None:
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"{ts}  [{status}]  {message}\n"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(line)
        print(line, end="")
        if metrics:
            record = {"ts": ts, "status": status, "msg": message, **metrics}
            with open(jsonl_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return write_log


def make_pending_saver(cache_file):
    """返回绑定到指定路径的 save_pending(messages)。

    推送失败时的兜底副本，**不做自动重发**——跨天重发旧稿比丢一次更糟，
    当天补救由 health_check → claude_catchup 重走完整流程负责。"""
    cache_file = Path(cache_file)

    def save_pending(messages: list) -> None:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump({"ts": datetime.now().isoformat(), "messages": messages},
                      f, ensure_ascii=False)

    return save_pending


def proxy_ok(configured: str | None, session=None) -> tuple[bool, str | None]:
    """代理预检 + 端口自愈，返回 (是否放行, 此后应使用的代理)。

    - 没配代理 → (True, None)，视为直连放行
    - 配了且通 → (True, 该代理)
    - 配了不通但候选端口通 → 就地改写环境变量与 session.proxies，返回 (True, 新代理)
    - 全都不通 → (False, 原配置值)，保留原值是为了让调用方能打进 SKIP_PROXY 的报错里

    session 传 requests.Session 时一并改其 proxies；AI bot 不持有自己的 Session，
    传 None 即可（抓取侧走 bot_utils 的 requests + feedparser，两者都只认环境变量）。

    ⚠️ 未来若加国内数据源的 bot（如 A 股），不要照抄这个前置闸门：
    国内接口不需要代理，代理挂了反而会让 bot 误判为"不可用"而整体跳过。"""
    resolved, switched = resolve_proxy(configured)
    if resolved is None:
        return (not configured), configured
    if switched:
        if session is not None:
            session.proxies = {"http": resolved, "https": resolved}
        # feedparser 走 urllib，必须同步环境变量（用赋值而非 setdefault）
        os.environ["HTTP_PROXY"]  = resolved
        os.environ["HTTPS_PROXY"] = resolved
    return True, resolved


def emit_fetch_output(lines, save_to=None) -> str:
    """把 fetch 阶段要给 routine 的全部 stdout 一次性打出去，同时落盘一份。

    起因：fetch 的 context 此前只走 stdout，调用方一旦截断（tail/head）或进程
    中途断掉，这一轮抓来的素材就没了，只能重打一遍外部 API。落盘之后，写稿失败
    重写、auto_repair 复现、事后复盘都能直接读文件。

    落盘失败只在 stderr 抱怨一句，绝不影响正常输出——它是附带品，不是主路径。"""
    payload = "\n".join(str(x) for x in lines)
    print(payload)
    if save_to:
        try:
            path = Path(save_to)
            path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            path.write_text(f"# fetch 生成于 {stamp}\n{payload}\n", encoding="utf-8")
        except Exception as e:
            print(f"  ⚠️ context 落盘失败（不影响本次输出）：{e}", file=sys.stderr)
    return payload
