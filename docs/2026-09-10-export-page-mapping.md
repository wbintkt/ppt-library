# 下载页面与勾选页面不一致：修复说明

## 原因

入库时的 PDF 预览跳过隐藏幻灯片，`PPTPage.page_no` 因此是从 1 开始的可见页码。
原导出器却把它当作原始演示文稿中包含隐藏页的序号。隐藏页之后的选中页会取错。
原接口还将选中页按文件分组，使 A2、B1、A1 变成 A2、A1、B1。

## 修复

- 导出器按演示文稿关系表中的真实顺序读取页面，并跳过 `show="0"` 或 `show="false"` 的隐藏页。
- 原生文本提取与导出共用隐藏页判断；既有可见页码与预览无需重建。
- 接口逐页传递选中顺序，导出器每份源文件只读取、搬迁一次，再恢复完整选中顺序。
- 单页预览下载与搜索结果批量下载共用此接口，两者同时修复。
- 缺失页面/源文件拒绝整次导出，不再静默漏页；可见页数不符时提示重新解析。
- 保留原生页面内容、样式及可编辑性；不同页面尺寸仍按现有规则拒绝合并。

页数检查只能检测数量变化，不能识别原文件在页数不变时被外部替换。
本次不修改数据库结构或现有页面记录。

## 验证

新增合成素材验证覆盖：首部/中间/末尾隐藏页、两种隐藏标记、单页下载、乱序选择、
跨文件交错选择、重复编号、缺失记录/文件、过期页数及非法请求。
检查下载 PPTX 中的真实可编辑文字和页面顺序，不仅检查返回状态和页数。

本地回归：79 项通过，2 项因缺少真实素材跳过，2 项 IDF 相关测试未运行。

```sh
cd backend
PYTHONPATH=. venv/bin/python -m pytest -q \
  tests/test_slide_merger.py tests/test_export_selection.py tests/test_native_text.py \
  tests/test_intent_reranker.py tests/test_intent_reranker_transport.py \
  tests/test_display_score.py tests/test_hybrid_search.py tests/test_query_analyzer.py \
  -k 'not idf'
```

当前环境禁止连接服务器，尚未完成线上素材验证、推送与部署。
部署时应先核对并备份当前版本，更新后重启后端及工作进程；下载一张隐藏页之后的
预览页，再按 A、B、A 交错勾选同尺寸素材，逐页核对预览内容和下载内容。
