# 开发与部署

## 仓库结构

当前仓库的有效结构可以按职责理解为：

- `.github/workflows/`
  根目录示例站点的实际部署流程
- `scripts/`
  Notion 拉取、Markdown 转换、翻译、摘要、缓存等核心 Python 逻辑
- `modules/`
  Hugo 侧的可复用模块
- `examples/trainsh-blog/`
  当前维护的参考站点
- `docs/`
  面向维护者的详细文档

`templates/workflows/` 已经移除，因为当前项目本身就是模板仓库，不再额外维护一份 workflow 模板副本。

## 同步管线

实际同步流程如下：

1. `scripts/notion_sync.py` 解析参数与 Hugo 配置。
2. `scripts/notion_service.py` 拉取 Notion 页面与 block。
3. `scripts/hugo_converter.py` 生成 Hugo front matter 与正文。
4. `scripts/media_handler.py` 下载并缓存媒体。
5. `scripts/translation_service.py` 处理标题与正文翻译。
6. `scripts/summary_service.py` 生成摘要。
7. `scripts/cache_manager.py` 持久化同步缓存。

## 当前缓存策略

### 本地缓存

目标站点根目录中的 `.notion_cache.json` 保存：

- 帖子时间戳
- 媒体映射
- 翻译结果
- 摘要结果
- 已生成内容路径

同步过程中每成功转换一篇文章就会立即落盘，异常退出时也会尽力再保存一次，以减少中途中断造成的 AI 结果丢失。

### GitHub Actions 缓存

根目录 workflow 现在使用滚动 cache key：

- restore：`site-<branch>-media-v2-<run_id>-<run_attempt>`
- restore prefix：`site-<branch>-media-v2-`
- save：当前 run 的完整 key

这样可以保证：

- 每次运行都会从最近一次成功缓存恢复
- 新结果会写入新的 cache entry
- 不再回退到旧的固定 `v1` key

## 示例站点部署流程

`.github/workflows/deploy-cloudflare.yml` 当前流程：

1. Checkout 仓库与子模块
2. 安装 Python / Go / Hugo / uv
3. 安装根目录 `notion-autoblog`
4. 恢复示例站点缓存
5. 同步 `examples/trainsh-blog/`
6. 构建 Hugo 站点
7. 保存新的站点缓存
8. 生成 Wrangler 配置
9. 部署 Cloudflare Worker
10. 清理 Cloudflare 边缘缓存

## 清理策略

仓库中不应保留这些生成物：

- `build/`
- `__pycache__/`
- `*.egg-info/`
- `examples/trainsh-blog/.notion_cache.json`
- `examples/trainsh-blog/.hugo_build.lock`
- 示例站点 `public/` 与 `static/*` 生成资源

GitHub Actions 的旧 cache 也应定期清理，只保留最近可用的 `v2` 结果。

## 测试与验证

当前推荐的基础验证命令：

```bash
uv run python -m unittest discover -s tests
```

如果修改了 workflow，额外需要检查：

- YAML 能被解析
- `gh cache list` 中的 cache key 是否符合 `v2` 规则
- 最近一次 Actions run 是否恢复了预期的 `v2` cache
