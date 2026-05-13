# Vibe Coding 内容聚合站

每天自动从多个平台抓取 **vibe coding / AI 编程** 相关内容，以时间线形式展示，精华文章单独推荐。

## 数据来源

| 来源 | 方式 | 状态 |
|------|------|------|
| 哔哩哔哩 | 搜索 API | ✅ 每次约 50+ 条 |
| GitHub | 仓库搜索 API | ✅ 每次约 24 条 |
| Hacker News | Algolia 搜索 API | ✅ 每次约 24 条 |
| RSS（少数派/36氪/量子位/机器之心） | RSS feed | ⚠️ 偶有相关文章 |
| Reddit | 搜索 API | ❌ 国内需代理 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行抓取

```bash
python3 aggregator.py
```

抓取结果保存在 `data/articles.json`。

### 3. 查看网站

用任意 HTTP 服务打开 `web/` 目录：

```bash
cd web && python3 -m http.server 8080
```

浏览器打开 `http://localhost:8080` 即可查看。

## 部署到 GitHub Pages（免费，每日自动更新）

### 步骤 1：推送到 GitHub

在 GitHub 新建仓库，然后：

```bash
cd vibe-coding-agg
git init
git add -A
git commit -m "init: vibe coding 内容聚合站"
git branch -M main
git remote add origin git@github.com:你的用户名/你的仓库名.git
git push -u origin main
```

### 步骤 2：开启 GitHub Pages

在仓库 Settings → Pages → Source 选择 `GitHub Actions`。

### 步骤 3：添加 GitHub Pages 部署

创建 `.github/workflows/deploy.yml`（已包含在项目中），每次抓取后自动部署网页。

或者直接用默认的 GitHub Pages workflow 从 `web/` 目录部署。

**抓取默认每天 UTC 0:00（北京时间 8:00）自动执行。**

### 可选：配置代理访问 Reddit

在 `aggregator.py` 的 `SESSION` 初始化后添加：

```python
SESSION.proxies = {
    "https": "http://127.0.0.1:7890"  # 替换为你的代理地址
}
```

## 自定义

### 添加更多关键词

编辑 `aggregator.py` 中的 `KEYWORDS` 列表。

### 添加更多 RSS 源

编辑 `aggregator.py` 中 `fetch_rss()` 函数的 `feeds` 列表。

### 调整精华判断标准

各数据源的 `is_featured` 逻辑：
- B站：播放量 > 50000
- GitHub：Star > 1000
- HN：点数 > 200
- Reddit：分数 > 500

## 项目结构

```
vibe-coding-agg/
├── aggregator.py          # 核心抓取脚本
├── data/
│   └── articles.json      # 抓取结果（自动生成）
├── web/
│   └── index.html          # 前端展示页
├── .github/workflows/
│   └── daily-fetch.yml     # 每日自动抓取
└── requirements.txt
```

## 许可

MIT
