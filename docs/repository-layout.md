# 仓库结构

## 当前结构
当前仓库以产品仓库为主，示例站点放在 `examples/`：

```text
.
├── modules/
├── scripts/
├── templates/
├── docs/
└── examples/
    └── trainsh-blog/
```

## 根目录职责
- 根目录提供 `notion-autoblog` Python 包
- `modules/` 保存可复用的 Hugo Modules（目前包含 `translation` 和 `upvote`）
- `scripts/` 保存同步与转换逻辑
- `templates/` 保存可复用的 CI/CD 模板
- `docs/` 保存详细开发文档

## example 站点
`examples/trainsh-blog/` 是当前用于发布 `https://blog.train.sh/` 的 Hugo 示例站点。

它包含：
- Hugo 配置
- Cloudflare Worker 配置
- `hugo-trainsh` 主题 submodule
- 站点首页与分区内容骨架

## 仓库内发布链路
根目录的 `.github/workflows/deploy-cloudflare.yml` 会：

1. 从根目录安装 `notion-autoblog`
2. 对 `examples/trainsh-blog/` 执行 Notion 同步
3. 构建该 example 站点
4. 将结果发布到 `blog.train.sh`

这样仓库名、产品代码和实际发布链路统一由 `notion-autoblog` 管理。
