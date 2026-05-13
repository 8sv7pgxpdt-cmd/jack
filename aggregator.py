#!/usr/bin/env python3
"""
Vibe Coding 内容聚合器 v2
- 多平台抓取（B站、个人博客、科技媒体、Hacker News）
- 链接有效性验证
- 自动分类标签（教程 / 资讯 / 精华）
- 商业洞察内容覆盖
"""

import json
import re
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import feedparser

# ---------- 配置 ----------
DATA_DIR = Path(__file__).parent / "data"
OUTPUT_FILE = DATA_DIR / "articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

BILIBILI_HEADERS = {
    **HEADERS,
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

# ---------- 工具 ----------

def fetch_json(url, params=None, **kwargs):
    try:
        r = SESSION.get(url, params=params, timeout=15, **kwargs)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] {url}: {e}")
        return None


def make_id(source, raw_id):
    return hashlib.md5(f"{source}:{raw_id}".encode()).hexdigest()[:12]


def clean_html(html):
    return re.sub(r"<[^>]+>", "", html or "")


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def parse_date_loose(s):
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


# ---------- 分类标签 ----------

TUTORIAL_KW = [
    "教程", "tutorial", "guide", "入门", "指南", "怎么", "如何",
    "上手", "使用教程", "配置", "安装", "设置", "实战", "手把手",
    "教学", "详解", "技巧", "攻略", "步骤", "demo", "示例",
    "新手", "零基础", "保姆级", "从零", "跟我做", "操作",
    "walkthrough", "how to", "上手教程", "学习", "笔记",
]

NEWS_KW = [
    "发布", "更新", "融资", "上线", "新品", "动态", "宣布", "最新",
    "news", "release", "launch", "收购", "投资", "趋势", "报告",
    "预测", "分析", "展望", "行业", "市场", "商业化", "商业模式",
    "估值", "融资额", "赛道", "布局", "战略", "财报", "上市",
    "突破", "里程碑", "首次", "重磅", "独家",
]

def categorize(title, summary, is_featured):
    """
    根据标题和摘要自动分类:
    - 教程: 含教学、指南类关键词
    - 资讯: 含行业动态、产品更新类关键词
    - 精华: 高互动/高播放量内容（is_featured=True）
    """
    if is_featured:
        return "精华"
    text = f"{title} {summary}".lower()
    t_score = sum(1 for kw in TUTORIAL_KW if kw in text)
    n_score = sum(1 for kw in NEWS_KW if kw in text)
    if t_score > n_score:
        return "教程"
    return "资讯"


# ---------- 链接验证 ----------

def check_bilibili_video(aid):
    """验证 B 站视频是否仍存在"""
    try:
        data = fetch_json(
            f"https://api.bilibili.com/x/web-interface/view?aid={aid}",
            headers=BILIBILI_HEADERS,
        )
        return data and data.get("code") == 0
    except Exception:
        return False


def check_link_ok(url, source):
    """快速检查链接是否可达（仅用于非 B 站链接）"""
    if "bilibili" in source:
        return True  # B 站链接在抓取时已验证
    try:
        r = SESSION.head(url, timeout=8, allow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


# ===================== 数据源 =====================

def fetch_bilibili():
    """哔哩哔哩 - 搜索 AI 编程相关视频（含链接验证）"""
    items = []
    try:
        SESSION.get("https://www.bilibili.com/", timeout=10)
    except Exception:
        pass

    keywords = [
        "AI编程", "vibe coding", "Cursor编辑器", "Windsurf AI",
        "Claude Code", "Copilot编程", "AI写代码", "AI 编程工具",
        "AI编程教程", "AI辅助编程",
    ]
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
            if not check_bilibili_video(aid):
                continue  # 视频已失效，跳过

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


def fetch_hackernews():
    """Hacker News - AI 编程相关讨论"""
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


def fetch_rss():
    """RSS 源 - 科技媒体 + 个人技术博客"""
    feeds = [
        # 科技媒体
        ("少数派", "https://sspai.com/feed"),
        ("量子位", "https://www.qbitai.com/feed"),
        ("36氪", "https://36kr.com/feed"),
        ("虎嗅", "https://www.huxiu.com/rss/0.xml"),
        # 个人博客/技术大佬
        ("阮一峰的网络日志", "https://feeds.feedburner.com/ruanyifeng"),
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
                    # AI 编程
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
                ]
                if not any(kw in text for kw in match_kw):
                    continue

                is_featured = False
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
                    "is_featured": is_featured,
                    "category": categorize(title, summary, is_featured),
                })
        except Exception as e:
            print(f"  [WARN] RSS {source_name}: {e}")
        time.sleep(0.5)
    return items


def fetch_github_chinese():
    """GitHub - 搜索中文 AI 编程工具（中文 README 优先）"""
    items = []
    queries = ["vibe coding", "AI编程工具", "cursor", "AI写代码"]
    for q in queries[:3]:
        data = fetch_json(
            "https://api.github.com/search/repositories",
            params={
                "q": q,
                "sort": "updated",
                "per_page": 8,
                "language": "zh",
            },
        )
        if not data:
            # 降级：不限语言
            data = fetch_json(
                "https://api.github.com/search/repositories",
                params={"q": q, "sort": "stars", "per_page": 5},
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


# ===================== 主流程 =====================

def fetch_all():
    all_items = []

    print("=" * 50)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] 开始抓取...")
    print("=" * 50)

    sources = [
        ("哔哩哔哩", fetch_bilibili),
        ("Hacker News", fetch_hackernews),
        ("RSS + 博客", fetch_rss),
        ("GitHub", fetch_github_chinese),
    ]

    for name, func in sources:
        print(f"\n📡 抓取 {name} ...")
        try:
            items = func()
            print(f"   ✅ {name}: {len(items)} 条")
            all_items.extend(items)
        except Exception as e:
            print(f"   ❌ {name}: {e}")

    # 去重
    seen = set()
    unique = []
    for item in all_items:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)

    # 链接验证（跳过已在抓取时验证的 B 站）
    print("\n🔗 验证链接有效性...")
    valid = [i for i in unique if check_link_ok(i["url"], i["source"])]
    dead_count = len(unique) - len(valid)
    if dead_count:
        print(f"   已过滤 {dead_count} 条失效链接")

    # 按时间倒序
    valid.sort(key=lambda x: x["published_at"], reverse=True)

    # 统计
    cats = {"教程": 0, "资讯": 0, "精华": 0}
    for i in valid:
        cats[i["category"]] = cats.get(i["category"], 0) + 1
    print(f"\n📊 总计: {len(valid)} 条 | 教程: {cats['教程']} | 资讯: {cats['资讯']} | 精华: {cats['精华']}")

    result = {
        "updated_at": now_iso(),
        "total": len(valid),
        "categories": cats,
        "articles": valid,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    json_str = json.dumps(result, ensure_ascii=False, indent=2)
    OUTPUT_FILE.write_text(json_str)
    (DATA_DIR.parent / "web" / "articles.json").write_text(json_str)

    print(f"\n💾 已保存到 {OUTPUT_FILE}")
    return result


if __name__ == "__main__":
    fetch_all()
