# 完整意图重排与搜索提速

## 为什么更换实现

旧版用 qwen-flash 分批逐页生成档位、分数、解释及引用。真实库一次搜索耗时 51.451 秒，其中重排 46.912 秒。串行批次和重试放大等待；“字符覆盖率 ≥75%”不能证明引用的业务关系正确。专用排序模型直接处理口语原句也会混淆“无人机作为工具”和“作为监管对象”，因此本次同时调整查询、排序和文本质量。

## 当前管线

1. 本地分词 + 向量召回，从向量序和关键词序选取最多 60 页。关键词只用于候选选择，不覆盖最终业务关系评分。查询向量缓存 15 分钟；查询调用不执行应用层重试，批量入库向量化保留原有重试策略。
2. qwen-flash 只提取原句中的执行方、动作、作用对象及工具，非空角色必须能在用户原句中逐字找到。必要的对象概念可带少量同义写法。“片子”按应用场景解释为 PPT 页面，不能被扩写为视频、宣传培训材料或实际案例要求。角色理解有 2.5 秒时限，失败时保留完整原句继续排序。
3. qwen3.7-text-rerank 一次对整批候选评分，不逐页生成解释和引用。完整原句始终传入，角色摘要仅补充关系，避免丢失排除条件、案例和封面要求。业务角色理解和排序共享 10 秒总预算；超时取消 HTTP 请求，不追加长时间重试。
4. 核对必要的作用对象内容，避免“只有无人机、没有黑飞治理”的页继续靠前。对象复合词按完整词匹配，允许“无人机”和“黑飞”出现在不同句子，不能用散字拼接证明“黑飞”。缺少关键概念时乘性降权，保留各候选间的语义次序。客户名称不作硬性门槛，技术支撑材料仍可入选。该检查是辅助启发式，不是形式化语义证明。
5. 校验返回的文档索引、完整性、重复项、数值范围后，才应用整批结果。失败时恢复召回排序。评分缓存 5 分钟，内容、标题、模型、提示词或 API Key 改变即失效；返回元数据始终来自当前数据库，不缓存整个搜索响应。

缓存为每进程有界内存缓存，各容量 128；重启后自动清空。重复查询依然执行数据库检索，删除素材或修改内容不会被旧结果缓存遮蔽。

## 原文提取

PPTX 优先按完整文本框和表格读取文本，避免 PDF 多栏逐行交叉。跳过隐藏页后，必须与 PDF 可见页数一致；文本覆盖不足或格式不支持则保留 PDF 提取。PNG、文件、页 ID 和页码不变。

已有数据可运行下列命令。默认仅预览；应用前必须指定不存在的备份文件，工具以 0600 权限写入备份。只有原生标题与当前页对应、可见页数一致且文本覆盖足够的记录才更新；提交时再次核对原文本，避免覆盖并发修改。更新的是同一页的文字提取顺序和全文索引，不改变向量或素材内容。

```bash
cd backend
venv/bin/python scripts/refresh_page_text.py
venv/bin/python scripts/refresh_page_text.py --apply --backup /secure/path/page-text-before.json
```

## API 与分数

`rerank_status` 仍为 `applied / failed / disabled / unavailable / skipped`。`timings_ms` 提供 `recall / rerank / total` 供验收和诊断，日志不包含查询正文或 Key。`rerank_reason` 只在关键对象内容不完整时返回本地说明，`rerank_evidence` 保留兼容字段但为 null，不再伪造引用。

`score` 与 `display_score` 一致，均为排序相关性值。专用模型的分数不等于准确率，不能直接与旧版人工分档的 95% 对比，也不会人为把第一名拉满。前端无需构建或改版。

## 配置、发布与回滚

```dotenv
RERANK_ENABLED=true
RERANK_MODEL=qwen3.7-text-rerank
RERANK_CANDIDATE_LIMIT=60
RERANK_TEXT_CHARS=1800
RERANK_TIMEOUT_SECONDS=10
SEARCH_INTENT_MODEL=qwen-flash
SEARCH_INTENT_TIMEOUT_SECONDS=2.5
SEARCH_EMBEDDING_TIMEOUT_SECONDS=5
SEARCH_MODEL_API_BASE=https://dashscope.aliyuncs.com
```

复用当前百炼 Key。服务必须能调用配置的模型，参数参考[百炼文本排序 API](https://help.aliyun.com/zh/model-studio/text-rerank-api)。从旧版升级必须将 `.env` 中的 `RERANK_MODEL=qwen-flash` 改为上述专用排序模型，同时将旧 60 秒超时改为 10 秒。新增依赖 `httpx`。更新依赖及代码后重启后端；解析逻辑也变化，需要一并重启 worker。没有数据库结构迁移。

发布前备份旧代码、`.env` 和需要更新的文本。可通过还原备份及重启服务回滚完整发布；仅临时关闭重排可设置 `RERANK_ENABLED=false`。文本回滚应按备份中的 `id/file_id/page_no` 匹配，且仅在当前文字仍等于 `new_text` 时恢复 `text`，避免覆盖后续用户修改。

## 验证

```bash
cd backend
venv/bin/python -m pytest tests/test_intent_reranker.py tests/test_intent_reranker_transport.py tests/test_native_text.py tests/test_display_score.py -q
# 真实模型评测会产生百炼用量，只发送合成素材：
RUN_LIVE_RERANK=1 venv/bin/python -m pytest tests/test_intent_reranker_live.py -q
```

2026-09-09 在真实库的候选版本上验证 6 个查询，全部完成重排并通过事先指定的正反例排序检查，首次查询范围 2.861–5.336 秒，重复同一查询 0.007 秒。原问题“找一个公安打击无人机黑飞的片子”由 51.451 秒降至 4.988 秒，目标态势感知、违规飞行告警和黑飞管控内容领先公安使用无人机的应用页与飞控封面。反向查询公安使用无人机时，应用页回到首位；摄像机巡查、秸秆焚烧、飞行审批和封面检索也通过检查。

这些是有限样本的实测值，不代表所有查询准确率或稳定延迟保证。上线验收应刷新页面清空前端旧查询缓存，并查看真实接口状态、前几页内容和分阶段耗时。角色/同义词提取仍可能失误，召回外的页面也无法由重排找回。
