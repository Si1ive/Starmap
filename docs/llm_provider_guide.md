# LLM 提供商接入指南

## 问题诊断

你遇到的错误原因是:
1. **enrich_llm 未启用**: `enabled: False`(默认关闭)
2. **base_url 和 api_key 为空**: 未配置阿里百炼的端点

---

## 一、什么是"OpenAI 兼容接口"?

### 1.1 定义

**OpenAI 兼容接口**指遵循 OpenAI API 规范的 HTTP 接口,核心特征:

- **请求格式**: `POST /v1/chat/completions`,JSON body:
  ```json
  {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "你好"}],
    "temperature": 0.7
  }
  ```
- **响应格式**: 
  ```json
  {
    "choices": [{"message": {"role": "assistant", "content": "你好！"}}]
  }
  ```
- **认证**: Header `Authorization: Bearer sk-xxx`

### 1.2 为什么要兼容 OpenAI 格式?

**行业标准化**: OpenAI API 是事实标准,大部分 LLM 提供商(阿里百炼/智谱/Moonshot/DeepSeek)都提供兼容接口,避免每家单独适配。

---

## 二、阿里百炼能用吗?

### 2.1 结论

**✅ 可以用**,但需要确认百炼是否提供 OpenAI 兼容端点。

### 2.2 百炼 API 两种模式

阿里百炼(DashScope)提供两种调用方式:

#### 模式 A: 原生 DashScope API(不兼容 OpenAI)

- **端点**: `https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation`
- **认证**: Header `Authorization: Bearer YOUR_API_KEY`
- **请求格式**: 
  ```json
  {
    "model": "qwen-turbo",
    "input": {"messages": [...]},
    "parameters": {"temperature": 0.7}
  }
  ```
- **🚫 不能直接用**: 字段名不同(`input` vs `messages`)

#### 模式 B: OpenAI 兼容端点(可用)

百炼在 2024 年后提供了兼容层(文档: https://help.aliyun.com/zh/model-studio/getting-started/openai-compatibility):

- **端点**: `https://dashscope.aliyuncs.com/compatible-mode/v1`
- **认证**: Header `Authorization: Bearer YOUR_API_KEY`
- **完全兼容 OpenAI 格式**: 可直接用

### 2.3 验证百炼是否支持兼容模式

运行以下命令测试(替换你的 API Key):

```bash
curl https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions \
  -H "Authorization: Bearer YOUR_DASHSCOPE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-turbo",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

**预期响应**: 返回 `{"choices": [{"message": {"content": "..."}}]}`

**若失败**: 说明你的百炼账号未开通兼容模式,需要:
- 升级到新版 DashScope API(2024 年后版本)
- 或联系阿里技术支持开通

---

## 三、差异对比:OpenAI 官方 vs 百炼兼容 vs 百炼原生

| 项目 | OpenAI 官方 | 百炼兼容模式 | 百炼原生 API |
|------|------------|------------|-------------|
| **base_url** | `https://api.openai.com/v1` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `https://dashscope.aliyuncs.com/api/v1/...` |
| **model 名称** | `gpt-4`, `gpt-3.5-turbo` | `qwen-turbo`, `qwen-plus`, `qwen-max` | 同左 |
| **请求格式** | OpenAI 标准 | OpenAI 标准 | DashScope 专有格式 |
| **Starmap 支持** | ✅ 直接用 | ✅ 直接用 | ❌ 需改代码 |

---

## 四、如何配置百炼到 Starmap

### 4.1 前置条件

1. 百炼账号已开通 OpenAI 兼容模式(2024+ 版本)。
2. 获取 API Key(在百炼控制台"API-KEY 管理"页面)。

### 4.2 配置步骤

#### 方式 1: 前端配置页(推荐)

1. 打开 `http://localhost:5173/admin/settings`(前端管理后台)。
2. 切换到 **"富化 LLM"** Tab。
3. 填写:
   - **启用**: 勾选 ✅
   - **服务类型**: 选择 `openai_compatible`
   - **Base URL**: `https://dashscope.aliyuncs.com/compatible-mode/v1`
   - **API Key**: 粘贴你的百炼 API Key(如 `sk-xxxxx`)
   - **模型**: `qwen-turbo`(或 `qwen-plus`/`qwen-max`)
   - **Temperature**: `0.3`(默认)
4. 点击"保存配置"。

#### 方式 2: 直接写数据库(调试用)

```sql
INSERT INTO system_configs (config_key, config_value, description)
VALUES ('enrich_llm', '{
  "enabled": true,
  "provider": "openai_compatible",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "api_key": "YOUR_DASHSCOPE_API_KEY",
  "model": "qwen-turbo",
  "temperature": 0.3,
  "max_tokens": 2000,
  "timeout_seconds": 90
}', '富化 LLM 配置')
ON DUPLICATE KEY UPDATE config_value = VALUES(config_value);
```

### 4.3 测试配置

```bash
# 后端测试脚本
cd backend
venv/bin/python -c "
import asyncio
from app.db.mysql import mysql_client
from app.services.enrichment_service import EnrichmentService

async def test():
    async with mysql_client.session() as db:
        es = EnrichmentService(db)
        client = await es._get_client()
        if not client.is_available:
            print('❌ enrich_llm 未配置或未启用')
            return
        print('✅ enrich_llm 可用')
        try:
            resp = await client.chat('你好，请用一句话介绍二叉树', purpose='test')
            print(f'✅ LLM 调用成功: {resp[:100]}...')
        except Exception as e:
            print(f'❌ LLM 调用失败: {e}')

asyncio.run(test())
"
```

---

## 五、常见错误与排查

### 错误 1: "enrich_llm_unavailable"

**原因**: `enabled: False` 或 `api_key` 为空。  
**解决**: 前端配置页启用 + 填写 API Key。

### 错误 2: "Connection refused" / "404 Not Found"

**原因**: `base_url` 错误或百炼未开通兼容模式。  
**解决**: 
1. 确认 base_url 为 `https://dashscope.aliyuncs.com/compatible-mode/v1`(注意 `/v1` 结尾)。
2. 用 curl 测试端点是否可达(见 2.3 节)。

### 错误 3: "Invalid API Key"

**原因**: API Key 过期或权限不足。  
**解决**: 百炼控制台重新生成 API Key,确保有"模型调用"权限。

### 错误 4: "Model not found: gpt-4"

**原因**: 配置了 OpenAI 模型名,但连的是百炼端点。  
**解决**: `model` 改为 `qwen-turbo` / `qwen-plus` / `qwen-max`。

---

## 六、其他国内 LLM 提供商配置

| 提供商 | Base URL | Model 示例 | 兼容性 |
|--------|----------|-----------|-------|
| **智谱 AI** | `https://open.bigmodel.cn/api/paas/v4` | `glm-4`, `glm-3-turbo` | ✅ OpenAI 兼容 |
| **Moonshot** | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | ✅ OpenAI 兼容 |
| **DeepSeek** | `https://api.deepseek.com/v1` | `deepseek-chat` | ✅ OpenAI 兼容 |
| **百川智能** | `https://api.baichuan-ai.com/v1` | `Baichuan2-Turbo` | ✅ OpenAI 兼容 |

**配置方法同上**,只需替换 `base_url` 和 `model`。

---

## 七、总结

1. **"OpenAI 兼容接口"是行业标准**: 大部分国内 LLM 都提供,避免重复适配。
2. **阿里百炼可以用**: 前提是开通了兼容模式(2024+ 版本),base_url 用 `compatible-mode/v1`。
3. **差异主要在端点和模型名**: OpenAI 用 `gpt-4`,百炼用 `qwen-turbo`,但请求格式完全一致。
4. **Starmap 当前只支持兼容接口**: 若你的 LLM 不兼容 OpenAI 格式,需改 `EnrichLLMClient` 代码适配。
