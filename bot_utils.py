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
  - url_key(url)                   URL 归一化（去 query/fragment/尾斜杠、转小写），用作去重键
  - load_sent_urls(path)           读出最近 N 天已推送过的 URL 键集合（跨天去重用）
  - record_sent_urls(path, urls)   记录本次实际推送的 URL 并按保留期裁剪
  - extract_hrefs(html_text)       从稿件里抽出 <a href="..."> 的 URL（记录"真正播出去的"）
  - is_ai_relevant(title, summary) 泛科技源的 AI 相关性闸门（垂直源不需要）
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


# ───────────────────────────────────────────────
# 7) 跨天去重 — 记住"真正推送过"的 URL
# ───────────────────────────────────────────────
# 背景：两个 bot 的时间窗口（AI 24h / Crypto 3 天）都可能让同一条新闻在连续
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
# 9) paginate_telegram — 按段落切分 + 页码
# ───────────────────────────────────────────────
# Telegram 单条上限 4096。原先两个 bot 各自实现同一套切分逻辑且不带页码，
# 读者收到第 2 条时开头直接是半截正文，不知道它接的是上一条。
# 这里统一实现并给多块结果加 (n/N) 页码。
#
# 注意：页码用 <b>，必须在 sanitize_html 之后再加，否则尖括号会被转义成实体。
# 两个 bot 的调用点都保证了"进入本函数时文本已清洗"。

_PAGE_MARKER_BUDGET = 24   # "<b>（10/10）</b>\n\n" 的宽裕上限，先从预算里扣掉


def paginate_telegram(text: str, max_len: int = 4096) -> list[str]:
    """把稿件切成若干条 Telegram 消息；超过一条时每条顶部加 (n/N) 页码。

    切分点只落在段落边界（\\n\\n），保证单条新闻不会被腰斩。"""
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    limit = max_len - _PAGE_MARKER_BUDGET
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in text.split("\n\n"):
        needed = len(para) + (2 if current else 0)   # 2 = '\n\n' 分隔符
        if current_len + needed > limit and current:
            chunks.append("\n\n".join(current))
            current, current_len = [para], len(para)
        else:
            current.append(para)
            current_len += needed
    if current:
        chunks.append("\n\n".join(current))

    if len(chunks) <= 1:
        return chunks
    total = len(chunks)
    return [f"<b>（{i}/{total}）</b>\n\n{c}" for i, c in enumerate(chunks, 1)]


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

# 探测顺序即优先级：先 1082（当前 Shadowrocket），不通再试 7892（上一代配置）。
# 历史上还用过 7897，如需再加回来直接补进这个元组即可，每多一个候选最多多花
# 一个 timeout（默认 5 秒），且只在配置端口已经不通时才会走到。
PROXY_CANDIDATES = ("1082", "7892")
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
