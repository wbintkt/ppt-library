# PPT 素材智能检索系统

面向企业内部的 PPT 素材智能管理、语义检索和复用系统。PPT 统一存储并按「页」解析索引，通过多模态 Embedding 模型（qwen3-vl-embedding，512 维）将页面文字、图片、图表及整体视觉语义映射到统一向量空间，实现基于自然语言的跨模态检索。

## 访问

- 前端：https://wbin.space/ppt/
- API：https://wbin.space/ppt/api/（反向代理至 127.0.0.1:8000）
- 默认账号：`admin` / `PptLib2026`（修改：backend/.env）

## 架构

```
浏览器 → nginx(/ppt/) → Vue3 前端
                      └ /ppt/api/ → FastAPI(8000)
                                      ├── PostgreSQL 14 + pgvector（向量库）
                                      ├── Redis + Celery（后台任务）
                                      └── 文件系统 /data/ppt-library
                                            ├── originals/  原文件
                                            ├── pages/      页面 PNG
                                            └── temp/       临时文件
```

检索管线：用户文本 → qwen3-vl-embedding + 本地关键词候选 → 原句业务角色提取 → qwen3.7-text-rerank → 关键对象完整性检查 → Top K。查询向量和评分使用有界内容缓存，重排共享 10 秒总预算。
降级模式：未配置 API Key 时自动使用 jieba 分词 + ILIKE 关键词检索（中文友好）。

完整意图重排保留原始问题，区分主体、动作、作用对象与工具，优先修正“公安用无人机巡查”与“公安查处无人机黑飞”等业务关系错配。默认启用并复用百炼 Key；不再逐页生成长解释和引用。PPTX 文本优先按完整文本框提取，正确跳过隐藏页。无需迁移数据库；旧部署需更新模型与超时配置，配置、验证及回滚见 [完整意图重排说明](docs/intent-reranking.md)。

## 部署位置

| 组件 | 位置 |
|---|---|
| 后端代码 | /home/admin/ppt-library/backend/ |
| 前端代码 | /home/admin/ppt-library/frontend/ |
| 前端产物 | /var/www/wbintkt-home/ppt/ |
| 数据目录 | /data/ppt-library/ |
| systemd | ppt-backend.service / ppt-worker.service |

## 运维命令

```bash
# 服务状态
systemctl status ppt-backend ppt-worker postgresql-14 redis

# 重启
systemctl restart ppt-backend ppt-worker

# 日志
journalctl -u ppt-backend -f
journalctl -u ppt-worker -f
tail -f /tmp/ppt_backend.log /tmp/ppt_worker.log

# 前端重新构建
cd /home/admin/ppt-library/frontend && npm run build

# 数据库
PGPASSWORD='<见 backend/.env>' /usr/pgsql-14/bin/psql -h 127.0.0.1 -U ppt_user -d ppt_library
```

## 配置 API Key（启用语义检索）

1. 登录系统 → 系统设置 → 输入阿里云百炼 DashScope API Key（`sk-...`）→ 保存
2. 素材库 → 对已有文件点「重索引」，自动向量化
3. 新上传文件自动向量化

Key 保存在数据库 app_settings 表，运行时可改，立即生效。

## 关键设计

- **查重**：文件 SHA-256 查重，重复上传直接返回已有记录
- **增量索引**：页面 PNG Hash 未变则跳过重新向量化
- **页面融合向量**：每页文本向量与图片向量取平均，一页一个 512 维向量
- **中文检索**：jieba 分词 + 停用词过滤 + 加权评分（标题 3 分 / 正文 1 分）
- **进度反馈**：上传 → parsing(0-55) → embedding(60-95) → ready，前端 6s 轮询
- **媒体鉴权**：页面 PNG 与下载均需 token（支持 ?token= 直链，便于 <img> 加载）

## 数据库

- ppt_files：文件记录（分类/标签/来源/Hash/状态/进度）
- ppt_pages：页面记录（页码/标题/文本/PNG 路径/向量/向量状态）
- app_settings：运行时配置（DASHSCOPE_API_KEY）

索引：`embedding` 列 HNSW 余弦索引、`text_tsv` GIN 索引、分类/状态索引。

## Docker Compose 部署（备选，架构文档第十一节）

当前服务器采用原生 systemd 部署（更省内存，1.8G 机器跑 Docker 全家桶较吃力）。
如需迁移至 Docker：`docker-compose.yml` + `backend/Dockerfile` + `deploy/nginx.conf` 已备好，
`docker compose up -d --build` 即可（含 pgvector/pg14、redis、FastAPI、Celery worker、Nginx）。
前端需另行构建至 nginx 挂载目录（或改用多阶段构建）。

## 环境备忘

- Python 3.11（/usr/bin/python3.11，venv 于 backend/venv）
- LibreOffice 7.1（需 libreoffice-impress 组件）
- poppler-utils（pdftoppm / pdftotext）
- PostgreSQL 14 + pgvector 0.8.6（PGDG 源，路径 /usr/pgsql-14）
- Redis 6.2
- 内存仅 1.8G：Celery worker 并发 1，worker_max_tasks_per_child=10 防泄漏

## 前端开发与发布

前端现采用「朱红 · 留白」内容搜索界面：首页只展示搜索入口，结果页显示页面标题、页码和后端提供的匹配度，不显示分类和来源。支持大图/紧凑视图、取消搜索、失败重试、跨查询选页、调整导出顺序及键盘预览。已选页面保存在当前标签页会话，退出或登录失效会清空；搜索结果仅在内存中缓存，查询词随页面 URL 保存。

```bash
cd frontend
npm ci
npm run dev
npm run check
```

`npm run check` 包括 Vue/TypeScript 检查、交互测试和生产构建。测试使用模拟 API，不调用线上模型或修改素材。

构建结果现在输出至 `frontend/dist/`，不再直接清空服务器网站目录。正式发布时，应先备份 `/var/www/wbintkt-home/ppt/index.html`，将 `dist/assets/` 与图标文件复制到网站目录，最后更新 `index.html`。保留旧版本带哈希的 assets，避免已打开的页面加载失败；回滚时恢复备份的 `index.html`。也可以通过 Vite 的 `--outDir` 参数显式指定其他构建目录。

本次前端改造不改变搜索排序、分数校准或导出后端。匹配度来自 `display_score`，缺失时显示「—」，不是经标注验证的准确率。上线后仍需使用真实素材检查搜索、预览、单页与多页导出。
