# 文件解析卡住问题 - 分析与解决方案

## 📊 问题诊断结果

### 发现的问题
1. **2 个文件卡在 parsing 状态**
   - `2022新大纲变化--408统考、数学、英语、政治.pdf` (1.06 MB, 44页)
   - `试卷2.pdf` (0.32 MB)

2. **5 个解析任务卡在 running 状态**
   - 最长的运行了 **889.8 分钟**（近15小时）
   - 明显已经超时或崩溃

### 根本原因分析

#### 原因 1：前端关闭导致状态未更新 ✅
- **现象**：用户关闭解析弹窗后，后端解析任务继续运行但前端无法获取结果
- **问题**：没有心跳检测或超时自动失败机制
- **影响**：即使解析失败或超时，状态仍然是 `running`

#### 原因 2：解析服务超时/崩溃 ✅
- **现象**：44页的PDF解析超过600秒（10分钟）超时
- **当前配置**：`request_timeout_seconds = 600`
- **问题**：
  - 大文件或复杂PDF可能需要更长时间
  - 解析服务可能崩溃但没有正确报错
  - 没有自动重试机制

#### 原因 3：缺少超时保护机制 ❌
- 没有后台任务监控
- 没有自动标记超时任务为失败
- 没有清理机制

---

## ✅ 已执行的修复

### 修复脚本：`fix_stuck_parsing.py`

**执行结果：**
```
✓ 标记 5 个超时任务为 failed
✓ 重置 2 个文件状态为 pending
✓ 可以重新触发解析
```

**修复后状态：**
- `2022新大纲变化--408统考、数学、英语、政治.pdf`：失败 2 次，需要重新解析
- `试卷2.pdf`：**之前成功解析过 1 次**，可能不需要重新解析

---

## 🔧 长期解决方案

### 方案 1：添加自动超时检测（推荐）

**实现：后台定时任务**

```python
# scripts/cleanup_stuck_tasks.py
async def cleanup_stuck_parsing_tasks():
    """定期清理超时的解析任务"""
    timeout_minutes = 30  # 30分钟超时
    timeout_threshold = datetime.utcnow() - timedelta(minutes=timeout_minutes)
    
    # 查找超时的 running 任务
    stuck_runs = await db.execute(
        select(ParseRun)
        .where(
            ParseRun.status == 'running',
            ParseRun.started_at < timeout_threshold
        )
    )
    
    for run in stuck_runs.scalars():
        # 标记为失败
        run.status = 'failed'
        run.completed_at = datetime.utcnow()
        run.error_detail = f"解析超时（超过 {timeout_minutes} 分钟）"
        
        # 重置文件状态
        corpus_file = await db.get(CorpusFile, run.corpus_file_id)
        if corpus_file and corpus_file.status == 'parsing':
            corpus_file.status = 'pending'
    
    await db.commit()
```

**部署方式：**
- 使用 cron 或 systemd timer 每 10 分钟运行一次
- 或者集成到现有的后台任务调度系统

### 方案 2：增加超时时间（针对大文件）

**当前配置：** 600 秒（10 分钟）

**建议调整：**
```python
# 根据文件大小动态设置超时时间
def calculate_timeout(file_size_mb):
    """
    动态计算超时时间
    - 小文件 (<1MB): 5 分钟
    - 中文件 (1-10MB): 10 分钟
    - 大文件 (10-50MB): 20 分钟
    - 特大文件 (>50MB): 30 分钟
    """
    if file_size_mb < 1:
        return 300  # 5分钟
    elif file_size_mb < 10:
        return 600  # 10分钟
    elif file_size_mb < 50:
        return 1200  # 20分钟
    else:
        return 1800  # 30分钟
```

### 方案 3：改进解析服务健壮性

**问题：** 解析服务可能崩溃但没有正确报错

**改进点：**
1. **添加健康检查**
   ```python
   async def check_parser_service_health():
       try:
           response = await http_client.get(
               f"{service_endpoint}/health",
               timeout=5
           )
           return response.status_code == 200
       except:
           return False
   ```

2. **添加重试机制**
   ```python
   max_retries = 3
   for attempt in range(max_retries):
       try:
           result = await parse_document(file_path)
           break
       except TimeoutError:
           if attempt < max_retries - 1:
               await asyncio.sleep(60)  # 等待1分钟后重试
               continue
           else:
               raise
   ```

3. **添加心跳检测**
   ```python
   # 解析过程中定期更新 updated_at
   async def parse_with_heartbeat(file_id):
       while parsing:
           # 每30秒更新一次
           await db.execute(
               update(ParseRun)
               .where(ParseRun.id == run_id)
               .values(updated_at=datetime.utcnow())
           )
           await asyncio.sleep(30)
   ```

### 方案 4：前端改进

**问题：** 用户关闭弹窗后无法看到解析结果

**改进：**
1. **后台解析**
   - 解析在后台进行，不依赖弹窗
   - 完成后发送通知

2. **进度查询**
   - 提供独立的"解析历史"页面
   - 显示所有解析任务的状态
   - 支持查看失败原因

3. **自动重试**
   - 失败后提示用户是否重试
   - 对于超时任务，建议增加超时时间后重试

---

## 🎯 立即行动建议

### 短期（本周）

1. **✅ 已完成：修复当前卡住的任务**
   - 运行 `fix_stuck_parsing.py` ✓

2. **部署自动清理脚本**
   ```bash
   # 添加 cron 任务，每10分钟运行一次
   */10 * * * * cd /path/to/backend && python3 scripts/cleanup_stuck_tasks.py
   ```

3. **针对44页大纲文件**
   - 检查解析服务是否正常：`curl http://localhost:8090/health`
   - 如果服务正常，增加超时时间到 1200 秒（20分钟）
   - 重新触发解析

### 中期（本月）

4. **实现动态超时**
   - 根据文件大小自动调整超时时间
   - 在系统设置中添加配置项

5. **添加解析监控页面**
   - 显示当前正在解析的任务
   - 显示历史解析记录
   - 支持手动终止/重试

6. **改进解析服务**
   - 添加健康检查端点
   - 添加重试机制
   - 优化大文件处理

---

## 💡 使用建议

### 对于44页的大纲文件

**选项 A：增加超时时间后重试**
```python
# 在系统设置中修改
"request_timeout_seconds": 1200  # 20分钟
```

**选项 B：分批处理**
- 将44页PDF拆分为多个小文件
- 分别解析后合并

**选项 C：使用更快的解析器**
- 尝试切换到 docling 解析器
- 或优化 mineru 配置

### 日常操作

1. **解析前检查服务状态**
   ```bash
   curl http://localhost:8090/health
   ```

2. **监控解析进度**
   - 不要关闭弹窗
   - 或者使用后台解析模式

3. **遇到卡住时**
   - 运行 `fix_stuck_parsing.py`
   - 检查解析服务日志
   - 考虑增加超时时间

---

## 📝 相关文件

- `backend/scripts/fix_stuck_parsing.py` - 修复卡住任务的脚本
- `backend/scripts/cleanup_stuck_tasks.py` - 待实现：自动清理脚本
- `backend/app/services/document_parse_service.py` - 解析服务主逻辑

---

**总结：** 问题已修复，文件状态已重置。建议部署自动清理脚本，并针对大文件增加超时时间。
