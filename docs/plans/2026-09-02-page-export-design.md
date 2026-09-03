# 页面勾选合并下载（Page Export）设计文档

日期：2026-09-02
状态：已批准（用户确认：PPTX 输出，不加来源标注）

## 需求

搜索结果出来后，每个页面卡片可单独勾选；勾选后点击下载，将所有选中页面的 PNG
合成为**一份 .pptx 文件**，即使页面来自不同源文件。

## 方案

### 后端：`POST /api/pages/export`

- 请求体：`{"page_ids": [4, 5, 9]}`（按勾选顺序）
- 逻辑：
  1. 校验 page_ids 非空（空 → 400）
  2. 按传入顺序查 `ppt_pages`，取 `png_path`（缺失/文件不存在 → 跳过，全部缺失 → 404）
  3. 用 python-pptx 新建演示文稿，每页插入整幅 PNG：
     - Slide 尺寸：4:3（10 × 7.5 英寸）——页面 PNG 为 1300×975（4:3），等比铺满不变形
     - 图片以原始宽高比居中铺满 slide
  4. 返回 `FileResponse`，文件名：`页面合集_YYYYMMDD_HHMMSS.pptx`
- 认证：需要 token（与现有接口一致）

### 前端

- `api.ts`：新增 `exportPages(pageIds: number[]): Promise<Blob>`（fetch blob，带 token）
- `SearchView.vue`：
  - 每个卡片左上角加勾选框（点击勾选不触发预览）
  - 底部固定操作栏：显示「已选 N 页」+ 「下载合并 PPTX」按钮 + 「清空」
  - 下载：调 exportPages → 创建 objectURL → a 标签触发下载

## 不做的事（YAGNI）

- 不加来源标注（用户明确不要）
- 不做 PDF 输出（用户明确要 PPTX）
- 不做跨页重新排版（整页图片合成，保持原版式）

## 验收标准

1. 搜索 → 勾选 2 个来自不同文件的页面 → 下载 → 得到 1 个 .pptx
2. pptx 页数 = 勾选页数，每页为对应页面图片，顺序与勾选顺序一致
3. 未勾选时下载按钮禁用
4. 后端接口测试通过（pytest）
