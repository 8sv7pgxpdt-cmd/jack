#!/usr/bin/env python3
"""
Vibe Coding 内容聚合器 v3
- 从 sources.json 读取订阅源配置，无需改代码即可增减源
- 支持: B站、V2EX、掘金、GitHub、Hacker News、RSS 多源
- 自动分类: 教程 / 资讯 / 精华
- B站视频有效性验证
"""

import json
import re
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser

# ========== 基础配置 ==========

# 项目根目录
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = DATA_DIR / "articles.json"
CONFIG_FILE = ROOT / "sources.json"
MANUAL_FILE = ROOT / "manual.json"

# HTTP 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# B站专用请求头（缺少 Referer 会返回 412）
BILIBILI_HEADERS = {
    **HEADERS,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

# 全局会话
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


# ========== 加载配置 ==========

def load_config():
    """加载 sources.json 配置文件"""
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] 无法加载 sources.json: {e}，使用默认配置")
        return {
            "搜索关键词": ["vibe coding", "AI编程"],
            "RSS订阅源": [],
            "V2EX节点": [],
            "掘金": {"启用": False},
            "知乎": {"启用": False},
            "链接验证": {"验证B站视频": True, "验证其他链接": False},
        }


# ========== 手动投稿 ==========

def load_manual_articles():
    """加载 manual.json 中手动添加的文章"""
    if not MANUAL_FILE.exists():
        return []
    try:
        raw = json.loads(MANUAL_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [WARN] manual.json 解析失败: {e}")
        return []

    items = []
    for entry in raw:
        # 跳过说明和示例条目（key 以下划线开头）
        if any(k.startswith("_") for k in entry.keys()):
            continue
        title = (entry.get("title") or "").strip()
        url = (entry.get("url") or "").strip()
        if not title or not url:
            continue

        is_featured = entry.get("category") == "精华"
        summary = (entry.get("summary") or "")[:200]
        items.append({
            "id": make_id("manual", url),
            "title": title,
            "url": url,
            "summary": summary,
            "source": entry.get("source", "手动收录"),
            "source_icon": entry.get("source_icon", "📌"),
            "author": entry.get("author", ""),
            "published_at": entry.get("published_at", now_iso()),
            "fetched_at": now_iso(),
            "tags": entry.get("tags", []),
            "is_featured": is_featured,
            "category": categorize(title, summary, is_featured),
        })
    return items


# ========== 工具函数 ==========

def fetch_json(url, params=None, method="GET", json_data=None, **kwargs):
    """安全请求 JSON API，失败返回 None（支持 GET/POST）"""
    try:
        if method == "POST":
            r = SESSION.post(url, json=json_data, timeout=15, **kwargs)
        else:
            r = SESSION.get(url, params=params, timeout=15, **kwargs)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] {url}: {e}")
        return None


def make_id(source, raw_id):
    """生成唯一文章 ID"""
    return hashlib.md5(f"{source}:{raw_id}".encode()).hexdigest()[:12]


def clean_html(html):
    """去除 HTML 标签"""
    return re.sub(r"<[^>]+>", "", html or "")


def now_iso():
    """当前时间 ISO 格式"""
    return datetime.now(timezone.utc).isoformat()


def parse_date_loose(s):
    """兼容多种日期格式"""
    if not s:
        return now_iso()
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]:
        try:
            return datetime.strptime(s, fmt).isoformat()
        except (ValueError, TypeError):
            continue
    if hasattr(s, "tm_year"):
        try:
            return datetime(
                s.tm_year, s.tm_mon, s.tm_mday,
                s.tm_hour, s.tm_min, s.tm_sec,
                tzinfo=timezone.utc,
            ).isoformat()
        except Exception:
            pass
    return now_iso()


# ========== 分类系统 ==========

# 教程类关键词
TUTORIAL_KW = [
    "教程", "tutorial", "guide", "入门", "指南", "怎么", "如何",
    "上手", "使用教程", "配置", "安装", "设置", "实战", "手把手",
    "教学", "详解", "技巧", "攻略", "步骤", "demo", "示例",
    "新手", "零基础", "保姆级", "从零", "跟我做", "操作",
    "walkthrough", "how to", "上手教程", "学习", "笔记",
]

# 资讯类关键词
NEWS_KW = [
    "发布", "更新", "融资", "上线", "新品", "动态", "宣布", "最新",
    "news", "release", "launch", "收购", "投资", "趋势", "报告",
    "预测", "分析", "展望", "行业", "市场", "商业化", "商业模式",
    "估值", "融资额", "赛道", "布局", "战略", "财报", "上市",
    "突破", "里程碑", "首次", "重磅", "独家",
    # 工具推荐类也归入资讯
    "推荐", "新工具", "利器", "神器", "测评", "效率工具",
    "产品", "应用", "app", "插件", "扩展",
]


def categorize(title, summary, is_featured):
    """
    根据标题和摘要自动分类:
    - 精华: 高互动/高播放量
    - 教程: 含教学关键词
    - 资讯: 含行业动态关键词
    """
    if is_featured:
        return "精华"
    text = f"{title} {summary}".lower()
    t_score = sum(1 for kw in TUTORIAL_KW if kw in text)
    n_score = sum(1 for kw in NEWS_KW if kw in text)
    return "教程" if t_score > n_score else "资讯"


# ========== 链接验证 ==========

def check_bilibili_video(aid):
    """验证 B 站视频是否仍然存在"""
    try:
        data = fetch_json(
            f"https://api.bilibili.com/x/web-interface/view?aid={aid}",
            headers=BILIBILI_HEADERS,
        )
        return data is not None and data.get("code") == 0
    except Exception:
        return False


def check_link_ok(url, source, config):
    """根据配置决定是否验证链接"""
    val_cfg = config.get("链接验证", {})
    if "bilibili" in source.lower():
        return True  # B 站在抓取时已验证
    if not val_cfg.get("验证其他链接", False):
        return True  # 不验证其他链接（国内网络外网超时）
    try:
        r = SESSION.head(url, timeout=8, allow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


# ==================== 数据源 ====================

def fetch_bilibili(config):
    """哔哩哔哩 - 搜索 AI 编程视频（含链接验证）"""
    items = []
    # 先访问首页获取 cookie（否则 API 返回 412）
    try:
        SESSION.get("https://www.bilibili.com/", timeout=10)
    except Exception:
        pass

    keywords = config.get("搜索关键词", [])[:10]
    for kw in keywords:
        data = fetch_json(
            "https://api.bilibili.com/x/web-interface/search/type",
            params={"search_type": "video", "keyword": kw, "page": 1},
            headers=BILIBILI_HEADERS,
        )
        if not data or data.get("code") != 0:
            continue

        for v in data.get("data", {}).get("result", [])[:8]:
            aid = v.get("aid")
            # 验证视频是否仍有效
            if not check_bilibili_video(aid):
                continue

            pub_ts = v.get("pubdate")
            pub_date = (
                datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat()
                if pub_ts else now_iso()
            )
            play_count = v.get("play") or 0
            is_featured = play_count > 50000
            title = clean_html(v.get("title", "")).strip()

            items.append({
                "id": make_id("bilibili", aid),
                "title": title,
                "url": f"https://www.bilibili.com/video/av{aid}",
                "summary": clean_html(v.get("description", "")).strip()[:200],
                "source": "哔哩哔哩",
                "source_icon": "📺",
                "author": v.get("author", ""),
                "published_at": pub_date,
                "fetched_at": now_iso(),
                "tags": [kw],
                "is_featured": is_featured,
                "category": categorize(title, v.get("description", ""), is_featured),
            })
        time.sleep(0.8)
    return items


def fetch_v2ex(config):
    """V2EX - 抓取 AI/编程 节点的话题"""
    items = []
    nodes = [n for n in config.get("V2EX节点", []) if n.get("启用", True)]
    for node in nodes:
        node_name = node.get("节点名", "")
        data = fetch_json(
            "https://www.v2ex.com/api/topics/show.json",
            params={"node_name": node_name, "p": 1},
        )
        if not data or not isinstance(data, list):
            continue

        for topic in data[:8]:
            tid = topic.get("id")
            title = topic.get("title", "")
            # 只保留 AI/编程 相关内容
            text = title.lower()
            match_kw = [
                "ai", "编程", "cursor", "vibe", "coding", "code", "copilot",
                "claude", "gpt", "windsurf", "开发", "程序", "代码",
                "工具", "agent", "自动化", "模型", "prompt",
            ]
            if not any(kw in text for kw in match_kw):
                continue

            created = topic.get("created")
            pub_date = (
                datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
                if created else now_iso()
            )
            is_featured = topic.get("replies", 0) > 50

            items.append({
                "id": make_id("v2ex", tid),
                "title": title,
                "url": f"https://www.v2ex.com/t/{tid}",
                "summary": (topic.get("content", "") or "")[:200],
                "source": f"V2EX · {node_name}",
                "source_icon": "💬",
                "author": topic.get("member", {}).get("username", "") if isinstance(topic.get("member"), dict) else "",
                "published_at": pub_date,
                "fetched_at": now_iso(),
                "tags": [node_name],
                "is_featured": is_featured,
                "category": categorize(title, "", is_featured),
            })
        time.sleep(0.5)
    return items


def fetch_juejin(config):
    """掘金 - 搜索 AI 编程相关文章"""
    items = []
    juejin_cfg = config.get("掘金", {})
    if not juejin_cfg.get("启用", False):
        return items

    keywords = juejin_cfg.get("搜索关键词", [])[:5]
    limit = juejin_cfg.get("每次抓取条数", 8)

    for kw in keywords:
        data = fetch_json(
            "https://api.juejin.cn/search_api/v1/search",
            method="POST",
            json_data={
                "query": kw,
                "limit": limit,
                "sort_type": 0,
            },
        )
        if not data or data.get("err_no") != 0:
            continue

        for item in data.get("data", [])[:limit]:
            article = item.get("article_info") or item.get("article") or {}
            article_id = article.get("article_id", "")
            title = article.get("title", "")
            summary = article.get("brief_content", "")
            author_info = item.get("author_user_info", {}) or {}
            ctime = article.get("ctime")
            pub_date = (
                datetime.fromtimestamp(int(ctime), tz=timezone.utc).isoformat()
                if ctime else now_iso()
            )
            digg = article.get("digg_count", 0)
            is_featured = digg > 200

            items.append({
                "id": make_id("juejin", article_id),
                "title": title,
                "url": f"https://juejin.cn/post/{article_id}",
                "summary": (summary or "")[:200],
                "source": "掘金",
                "source_icon": "🥇",
                "author": author_info.get("user_name", ""),
                "published_at": pub_date,
                "fetched_at": now_iso(),
                "tags": [kw],
                "is_featured": is_featured,
                "category": categorize(title, summary or "", is_featured),
            })
        time.sleep(0.6)
    return items


def fetch_hackernews():
    """Hacker News - AI 编程相关外网讨论"""
    items = []
    for kw in ["vibe coding", "AI coding tool", "cursor IDE", "Claude Code",
               "Windsurf AI", "Copilot"]:
        data = fetch_json(
            "https://hn.algolia.com/api/v1/search",
            params={"query": kw, "tags": "story", "hitsPerPage": 8},
        )
        if not data:
            continue
        for hit in data.get("hits", [])[:6]:
            oid = hit.get("objectID")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={oid}"
            title = hit.get("title", "")
            is_featured = hit.get("points", 0) > 200

            items.append({
                "id": make_id("hn", oid),
                "title": title,
                "url": url,
                "summary": "",
                "source": "Hacker News",
                "source_icon": "🔶",
                "author": hit.get("author", ""),
                "published_at": hit.get("created_at", now_iso()),
                "fetched_at": now_iso(),
                "tags": [kw],
                "is_featured": is_featured,
                "category": categorize(title, "", is_featured),
            })
        time.sleep(0.3)
    return items


def fetch_rss(config):
    """RSS 多源抓取 - 从 sources.json 读取订阅列表"""
    feeds = [
        (f["名称"], f["地址"])
        for f in config.get("RSS订阅源", [])
        if f.get("启用", True)
    ]
    items = []
    for source_name, url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                link = entry.get("link", "")

                # 筛选 AI 编程 / 商业洞察相关内容
                text = f"{title} {summary}".lower()
                match_kw = [
                    # AI 编程工具
                    "vibe cod", "ai cod", "cursor", "windsurf", "claude code",
                    "copilot", "ai编程", "ai写代码", "ai ide", "ai 编程",
                    "ai coding", "自然语言编程", "ai程序员", "ai开发工具",
                    "编程助手", "代码生成", "ai developer", "ai写前端",
                    "ai agent", "ai 开发", "智能编程", "ai 程序员",
                    "ai辅助编程", "ai写项目", "ai 写代码",
                    "github copilot", "trae", "aixcoder", "codeium",
                    "通义灵码", "文心快码", "comate", "marscode",
                    "tabnine", "codex", "devin",
                    # 商业洞察
                    "ai软件", "ai 工具", "ai coding 市场", "ai编程 融资",
                    "编程工具 融资", "ai开发 投资", "ai 编程 趋势",
                    "ai 编程 商业", "大模型 编程", "ai coding 创业",
                    "ai 程序员 市场", "ai 开发平台",
                    # AI 新应用/工具推荐
                    "ai新工具", "ai工具推荐", "ai应用推荐", "ai产品",
                    "ai效率工具", "新工具", "效率工具", "ai 推荐",
                    "ai 新品", "ai 应用", "ai app", "ai神器",
                    "ai 好物", "ai 插件", "ai 扩展", "ai 浏览器",
                    "ai 设计", "ai 写作", "ai 画图", "ai 视频",
                    "ai 音乐", "ai 办公", "ai 笔记", "ai 搜索",
                    "product hunt", "新产品", "利器", "测评",
                    "ai 自动化", "ai 工作流",
                ]
                if not any(kw in text for kw in match_kw):
                    continue

                items.append({
                    "id": make_id("rss", entry.get("id", link)),
                    "title": title,
                    "url": link,
                    "summary": clean_html(summary)[:200],
                    "source": source_name,
                    "source_icon": "📰",
                    "author": entry.get("author", source_name),
                    "published_at": parse_date_loose(
                        entry.get("published", entry.get("updated"))
                    ),
                    "fetched_at": now_iso(),
                    "tags": [],
                    "is_featured": False,
                    "category": categorize(title, summary, False),
                })
        except Exception as e:
            print(f"  [WARN] RSS {source_name}: {e}")
        time.sleep(0.5)
    return items


def fetch_github():
    """GitHub - 搜索中文 AI 编程工具仓库"""
    items = []
    for q in ["vibe coding", "AI编程工具", "AI写代码"]:
        # 优先搜中文
        data = fetch_json(
            "https://api.github.com/search/repositories",
            params={"q": q, "sort": "updated", "per_page": 6},
        )
        if not data:
            continue
        for repo in data.get("items", [])[:6]:
            fid = repo.get("id")
            desc = repo.get("description") or ""
            fullname = repo.get("full_name", "")
            is_featured = repo.get("stargazers_count", 0) > 1000

            items.append({
                "id": make_id("github", fid),
                "title": fullname,
                "url": repo.get("html_url", ""),
                "summary": desc[:200],
                "source": "GitHub",
                "source_icon": "🐙",
                "author": repo.get("owner", {}).get("login", ""),
                "published_at": repo.get("updated_at", now_iso()),
                "fetched_at": now_iso(),
                "tags": repo.get("topics", [])[:5] + [q],
                "is_featured": is_featured,
                "category": categorize(fullname, desc, is_featured),
            })
        time.sleep(2)
    return items


# ==================== 主流程 ====================

def fetch_all():
    """执行所有数据源的抓取"""
    config = load_config()
    all_items = []

    print("=" * 50)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 开始抓取...")
    print(f"配置文件: {CONFIG_FILE}")
    print("=" * 50)

    # 定义所有数据源（名称, 函数, 是否传 config）
    sources = [
        ("哔哩哔哩", lambda: fetch_bilibili(config)),
        ("V2EX", lambda: fetch_v2ex(config)),
        ("掘金", lambda: fetch_juejin(config)),
        ("Hacker News", fetch_hackernews),
        ("RSS 订阅", lambda: fetch_rss(config)),
        ("GitHub", fetch_github),
    ]

    for name, func in sources:
        print(f"\n📡 抓取 {name} ...")
        try:
            items = func()
            print(f"   ✅ {name}: {len(items)} 条")
            all_items.extend(items)
        except Exception as e:
            print(f"   ❌ {name}: {e}")

    # 合并手动投稿
    manual = load_manual_articles()
    if manual:
        print(f"\n📌 手动投稿: {len(manual)} 条")
        all_items.extend(manual)

    # 去重
    seen = set()
    unique = []
    for item in all_items:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    # 链接验证
    val_cfg = config.get("链接验证", {})
    if val_cfg.get("验证B站视频", True) or val_cfg.get("验证其他链接", False):
        print("\n🔗 验证链接有效性...")
        valid = [i for i in unique if check_link_ok(i["url"], i["source"], config)]
        dead_count = len(unique) - len(valid)
        if dead_count:
            print(f"   已过滤 {dead_count} 条失效链接")
    else:
        valid = unique
        print("\n⏭️  跳过链接验证（见 sources.json 配置）")

    # 按时间倒序
    valid.sort(key=lambda x: x["published_at"], reverse=True)

    # 统计
    cats = {"教程": 0, "资讯": 0, "精华": 0}
    sources_count = {}
    for i in valid:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
        src = i["source"]
        sources_count[src] = sources_count.get(src, 0) + 1

    print(f"\n📊 总计: {len(valid)} 条 | 教程: {cats['教程']} | 资讯: {cats['资讯']} | 精华: {cats['精华']}")
    for src, cnt in sorted(sources_count.items(), key=lambda x: -x[1]):
        print(f"   {src}: {cnt} 条")

    result = {
        "updated_at": now_iso(),
        "total": len(valid),
        "categories": cats,
        "sources": sources_count,
        "articles": valid,
    }

    # 输出到 data/ 和 web/ 两个位置
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_str = json.dumps(result, ensure_ascii=False, indent=2)
    OUTPUT_FILE.write_text(json_str)
    (ROOT / "web" / "articles.json").write_text(json_str)

    print(f"\n💾 已保存到 {OUTPUT_FILE}")
    return result


if __name__ == "__main__":
    fetch_all()
