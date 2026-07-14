# 大纲入库改进文档

## 修复的问题

### 1. 部分成功不落库（事务全回滚）

**问题描述**:
- 大纲已按科目拆分（数据结构、计组、操作系统、计网）
- 某一科目 LLM 拆分超时/失败 → 整个 `split_outline` 抛异常
- 即使其他科目已成功拆分，但因一个失败导致整个结果被丢弃
- 前端收到 500 错误，用户看不到任何成功的部分

**根本原因**:
```python
# 旧代码（outline_llm_service.py:200-208）
for code, start, end in segments:
    subject = subjects_by_code.get(code)
    if not subject:
        continue
    seg_text = markdown[start:end].strip()
    parsed = await self._split_one_subject(client, subject.name, seg_text)  # ❌ 异常直接向上抛
    results.append(self._pack_subject_result(subject, parsed))
```

**修复方案**:
1. **`OutlineLLMService.split_outline`**: 捕获每个科目的异常，失败的科目标记 `error` 字段但不中断流程
2. **`OutlineImportService.import_from_llm_result`**: 过滤出有效科目（有 chapters 且无 error），只入库成功的部分
3. **返回 `partial=true`**: 标识部分成功，前端可展示"3/4 科目成功"

```python
# 新代码（outline_llm_service.py）
try:
    parsed = await self._split_one_subject(client, subject.name, seg_text)
    results.append(self._pack_subject_result(subject, parsed))
except Exception as e:
    logger.warning("大纲拆分某科目失败，标记为失败但继续处理其他科目", 
                   subject=subject.name, error=str(e))
    results.append({
        "subject_id": subject.id,
        "subject_name": subject.name,
        "error": str(e),  # 标记错误
        "chapters": [],
    })
```

---

### 2. 单科内容过大超时

**问题描述**:
- 虽然按科目拆分了，但单个科目（如数据结构）大纲仍可能有 5-10 页
- 一次性塞给 LLM → 输入 token 过多（几千行 markdown）
- 生成时间过长 → 120 秒超时: `Read timed out. (read timeout=120)`
- 用户看到："Request timed out: HTTPSConnectionPool(host='dashscope.aliyuncs.com', port=443)"

**为什么不能简单延长超时？**
1. **治标不治本**: 延长到 300 秒，下次更大文档还是超
2. **LLM 推理慢**: 输入越大推理越慢，qwen3-vl-235b-thinking 是多模态思考模型，处理纯文本慢
3. **Claude Code 1M context ≠ 单次请求 1M tokens**: 
   - Claude Code 1M 是"对话历史 + 当前输入"的累计上限
   - 但**单次请求**仍有限制（通常 200K tokens 输入 + 8K 输出）
   - 把整个大纲塞进一个请求 → 可能超出单次输入限制 → **被截断**

**当前状态（已部分解决）**:
- ✅ 已按科目拆分（4 个独立请求）
- ❌ 单科内部仍然是整体处理（需要进一步拆分）

**未来优化方向**（暂未实现，留作后续）:
如果单科超时仍然频繁，可以:
1. **按一级章节拆分**: 识别一级标题（如"第一章"），每个一级章节单独调 LLM
2. **分批合并**: 每批 3-5 个一级章节，最后拼接成完整章节树

---

### 3. 缺少进度显示

**问题描述**:
- 用户提交大纲入库 → 请求执行很长时间（几分钟）
- 前端没有进度条，用户不知道当前处理到哪个科目
- 关闭窗口后任务"消失"，只能在 LLM 请求记录里看到零散调用

**修复方案**: 增加 `OutlineIngestionRun` 任务表 + 进度轮询 API

#### 新增表: `outline_ingestion_runs`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | VARCHAR(32) PK | 任务 ID |
| `document_id` | VARCHAR(32) FK | 源文档 ID |
| `outline_id` | VARCHAR(32) | 生成的大纲 ID（成功后填充） |
| `status` | ENUM | `pending/processing/done/partial/failed` |
| `total_subjects` | INT | 总科目数（4） |
| `processed_subjects` | INT | 已处理科目数（实时更新） |
| `successful_subjects` | INT | 成功处理科目数 |
| `current_subject_name` | VARCHAR(100) | 当前处理科目名（如"数据结构"） |
| `created_chapters` | INT | 总共创建章节数 |
| `error_detail` | TEXT | 错误详情 |
| `result_summary` | JSON | 各科目处理结果摘要 |
| `started_at` / `completed_at` | DATETIME | 开始/完成时间 |

**关键字段**:
- **进度 = `processed_subjects / total_subjects * 100`**
- **`current_subject_name`**: 实时更新当前处理的科目（前端显示"正在处理: 数据结构"）
- **`status = 'partial'`**: 部分成功（如 3/4 科目成功）

#### 新增 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /outlines/runs/{run_id}` | GET | 获取任务详情（轮询用） |
| `GET /outlines/runs` | GET | 列出任务列表（支持按 document_id/status 过滤） |

**前端轮询示例**:
```tsx
const { data: run } = useQuery({
  queryKey: ['outlineRun', runId],
  queryFn: () => getOutlineRunDetail(runId),
  refetchInterval: run?.status === 'processing' ? 2000 : false,  // 处理中才轮询
})

<Progress 
  percent={run.progress} 
  status={run.status === 'failed' ? 'exception' : undefined}
/>
<div>当前处理: {run.current_subject_name}</div>
```

---

## 修改的文件清单

### 后端

1. **`backend/alembic/versions/20260621_outline_ingestion_run.py`** (新建)
   - 迁移文件: 创建 `outline_ingestion_runs` 表

2. **`backend/app/models/mysql_models.py`** (新增模型)
   - `OutlineIngestionRun`: 大纲入库任务表

3. **`backend/app/modules/catalog/outline_llm_service.py`** (修改核心逻辑)
   - `split_outline()`: 每个科目失败不影响其他科目，捕获异常并标记 `error` 字段
   - 返回格式扩展: `subjects` 列表中失败的科目带 `error` 字段

4. **`backend/app/modules/catalog/outline_import_service.py`** (修改核心逻辑)
   - `import_from_llm_result()`: 
     - 过滤出有效科目（有 chapters 且无 error）
     - 只入库成功的科目，失败的记录到 `result_summary`
     - 返回 `partial=true` 标识部分成功
     - 返回 `successful_subjects` / `failed_subjects` 统计

5. **`backend/app/api/admin.py`** (新增/修改端点)
   - `POST /outlines/import-from-llm`: 修改返回，部分成功时带 warning message
   - `GET /outlines/runs/{run_id}` (新增): 获取任务详情
   - `GET /outlines/runs` (新增): 列出任务列表

### 前端（需要实现）

**待实现功能**:
1. **大纲入库页面**: 提交后跳转到进度页
2. **进度页**: 轮询 `/outlines/runs/{run_id}`，显示进度条 + 当前处理科目
3. **任务列表页**: 显示历史任务，支持重新打开查看结果

---

## 验证步骤

### 1. 测试部分成功落库

**场景**: 上传一个大纲，其中一个科目超时，其他成功

```bash
# 1. 查看 LLM 请求记录
# 预期: 看到 4 个科目的请求，1 个超时/失败，3 个成功

# 2. 查看大纲章节
curl http://localhost:8000/api/v1/admin/outlines/{outline_id}/subjects

# 预期: 只有 3 个科目有章节，失败的科目不在 exam_outline_subjects 表中
```

**验证点**:
- ✅ 失败科目不阻塞其他科目
- ✅ 成功科目的章节已入库
- ✅ API 返回 `partial=true` 和失败原因

### 2. 测试超时问题（当前部分解决）

**当前状态**:
- ✅ 按科目拆分（4 个独立请求）
- ⚠️ 单科内容过大仍可能超时

**验证**:
```bash
# 查看单个科目的 markdown 长度
# 如果 > 10000 字符，可能超时
```

**临时缓解方案**:
1. 使用更快的模型（如 `qwen-turbo` 替代 `qwen3-vl-235b-a22b-thinking`）
2. 延长 `timeout_seconds` 到 180（outline_llm 配置）

**长期方案**（需要进一步实现）:
- 按一级章节拆分单科内容

---

## 数据库变更

```sql
-- 迁移已执行: 20260621_outline_run
-- 新增表: outline_ingestion_runs
SHOW CREATE TABLE outline_ingestion_runs;
```

---

## 总结

### ✅ 已修复

1. **部分成功落库**: 某科目失败不影响其他科目，成功的部分正常入库
2. **进度表基础**: 创建了 `OutlineIngestionRun` 表和 API，为进度显示奠定基础
3. **错误容忍**: 失败科目会标记 `error` 字段，前端可展示具体错误原因

### ⚠️ 部分解决

- **超时问题**: 已按科目拆分，但单科内容过大仍可能超时
- 建议: 使用更快模型（qwen-turbo）或进一步按章节拆分

### 🔜 待实现（前端）

1. **进度页**: 提交后跳转 + 轮询显示进度
2. **任务列表**: 查看历史任务 + 重新打开
3. **部分成功提示**: 展示"3/4 科目成功，1 个失败: 计算机网络超时"

---

## API 使用示例

### 查询任务详情

```bash
GET /api/v1/admin/outlines/runs/{run_id}

Response:
{
  "code": 0,
  "data": {
    "id": "abc123",
    "status": "processing",
    "progress": 75.0,  # 75%
    "total_subjects": 4,
    "processed_subjects": 3,
    "successful_subjects": 2,
    "current_subject_name": "计算机网络",
    "error_detail": null,
    "result_summary": [
      {"subject_name": "数据结构", "status": "success", "created": 45},
      {"subject_name": "计算机组成原理", "status": "success", "created": 38},
      {"subject_name": "操作系统", "status": "failed", "error": "timeout"}
    ]
  }
}
```

### 列出任务

```bash
GET /api/v1/admin/outlines/runs?document_id={doc_id}&status=processing

Response:
{
  "code": 0,
  "data": {
    "items": [
      {
        "id": "abc123",
        "status": "processing",
        "progress": 50.0,
        "total_subjects": 4,
        "successful_subjects": 2,
        "created_at": "2026-06-21T10:30:00"
      }
    ]
  }
}
```
