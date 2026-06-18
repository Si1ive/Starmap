# Starmap LLM 选型清单

> 用途：本系统所有 LLM 触点的选型指南。照此清单去找模型，拿到 `base_url` + `api_key` + `model` 后填到「系统设置」对应配置块即可。
> 关键前提：**全系统走 OpenAI 兼容接口**（`openai.ChatCompletion.create` + 可配 `api_base`）。任何提供 OpenAI 兼容端点的厂商（DeepSeek / 通义 / Kimi / 智谱 / 豆包 / OpenAI / 代理）都能直接接入，无需改代码。

---

## 一、系统里的 5 个 LLM 触点

| # | 触点 | 配置块 | 调用特征 | 难度 |
|---|------|--------|---------|------|
| 1 | 大纲拆分 | `outline_llm`（系统设置） | 离线批处理、长文本（单次喂 ≤6 万字）、要稳定吐多层嵌套 JSON、区分考察目标/标题/考点 | ★★★★★ 最难 |
| 2 | 复习指导生成 | 复用 `outline_llm` | 离线批处理、要 408 学科知识 + 中文写作、按 15 节点/批 | ★★★★ |
| 3 | 学生问答 | `llm`（系统设置，`chat_service` 读取） | 在线、面向学生、RAG 增强答案 + 建议问题、低延迟、量大 | ★★★ |
| 4 | 题目结构兜底 | `pdf_structure_llm`（系统设置） | 离线批处理、判断跨页/跨列拆题、temperature=0.1、要 JSON | ★★ |
| 5 | 文本向量化 | **代码写死** `embedding_service.py` | 章节/题目文本转向量供检索（非对话模型） | 独立品类 |

---

## 二、分档选型建议

### A. 大纲拆分 + 复习指导（`outline_llm`）— 挑能负担的最强的
全系统最吃能力的一环：文本脏（MinerU 混排 markdown）、要长上下文、要严格 JSON、要 408 学科理解。
**这里最不该省钱**：一次性离线批处理，一份大纲只拆一次，调用次数极少，质量差一点就得人工返工。

- **必须满足**：上下文 ≥ 32K（最好 128K+）、强指令遵循、可靠结构化 JSON 输出、中文好
- **推荐档位**：旗舰 / 次旗舰
  - DeepSeek-V3/V4 系列（性价比之王，JSON 稳，长上下文，API 极便宜）
  - 通义千问 Qwen-Max / 智谱 GLM-4-Plus（GLM-5）/ Kimi（长文本传统强项）
  - 预算充足：Claude / GPT-5 系列（中文 + 推理天花板，但贵）
- **配置提示**：`temperature` 已设 0.2，合理；若厂商支持 JSON mode / 结构化输出，开启可进一步降低解析失败率

### B. 学生问答（`llm`）— 中端，均衡延迟和成本
面向学生、在线、量随用户增长放大。要中文流畅 + 基本 408 推理，**不需要旗舰**。

- **必须满足**：中文对话自然、响应快（秒级）、单价低
- **推荐档位**：中端
  - DeepSeek-V3 / Qwen-Plus / GLM-4-Air / 豆包-pro（中文多轮响应快）
- **可选优化**：RAG 答案用稍强的，"建议问题"（生成 3 个追问）用最便宜的小模型即可

### C. 题目结构兜底（`pdf_structure_llm`）— 中端偏低即可
只判断"这题是否被跨页拆了/选项缺没缺"，离线跑、temperature=0.1、要 JSON。判断类任务，不需强推理。

- **推荐档位**：中端
  - DeepSeek-V3 / Qwen2.5-32B 级别 / GLM-4-Flash
- 量可能不小（题库逐题过），**更该看单价**

### D. 文本向量化（`embedding_service`）— 单独品类，且有代码约束 ⚠️
检索质量的地基，中文检索效果直接决定 RAG 答得准不准。

- **推荐**：
  - bge-m3（BAAI，中文检索口碑标杆，稠密+稀疏+多向量，8192 token，可自托管免费）
  - 通义 text-embedding-v3 / 智谱 embedding-3（API 形式，省运维）
  - OpenAI text-embedding-3-small/large（若已有 OpenAI 通道）
- ⚠️ **代码约束**：当前写死 `text-embedding-ada-002` + `1536` 维（`backend/app/services/embedding_service.py:21-22`）。换模型前先确认维度：
  - ada-002 / text-embedding-3-small = **1536** → 可无痛替换
  - bge-m3 / 多数国产 = **1024** → 必须改 `EMBEDDING_DIMENSION` + 向量库列定义 + **重新生成全部历史向量**

---

## 三、最省心的推荐组合

- **A + B + C** 全部用 **DeepSeek**（一个 key 通吃，OpenAI 兼容，JSON 稳，单价极低，长上下文）。先用一家跑通，后续再按需把"问答"换成更快的豆包、把"大纲"换成更强的 Claude。
- **D 向量化**：维持 `text-embedding-3-small`（1536 维，零改码）；或自托管 bge-m3 换中文检索效果（要改维度 + 重灌向量，建议二期再做）。

---

## 四、配置落地位置

| 配置块 | 在哪填 | 关键字段 |
|--------|--------|---------|
| `outline_llm` | 系统设置页 → 大纲拆分 LLM | `enabled=true`、`base_url`、`api_key`、`model` |
| `pdf_structure_llm` | 系统设置页 → PDF 文档结构解析 LLM | 同上 |
| `llm` | 系统设置页 → LLM 参数 | `model`、`temperature`、`max_tokens`（key 走全局 `OPENAI_API_KEY`） |
| embedding | `backend/app/services/embedding_service.py` | 改模型名 + 维度（需改代码，非配置） |

> 默认 `enabled=false`：`outline_llm` 和 `pdf_structure_llm` 未配置时不会静默走空，会返回明确错误（400/503）。

---

## 五、2026 年市场参考

- DeepSeek V4 系列：1M 上下文，MIT 开源，API 输入价低至约 1 元/百万 token，结构化输出稳定，国产性价比标杆。
- Qwen / GLM / Kimi / 豆包：均提供 OpenAI 兼容端点，中文场景成熟；豆包中文多轮对话响应速度口碑好。
- bge-m3：中文 embedding 检索效果标杆，支持 100+ 语言、8192 token、稠密/稀疏/多向量三合一，可本地部署。

参考来源：
- 中国 LLM API 价格对比 2026：http://apidog.com/blog/chinese-llm-price-war-2026
- Qwen vs DeepSeek vs GLM 横评：https://blog.easecloud.io/en/ai-cloud/qwen-vs-deepseek-vs-glm/
- DeepSeek V4 深度解析：https://www.cnblogs.com/qiniushanghai/p/19925642
- BAAI/bge-m3：https://huggingface.co/BAAI/bge-m3
- bge-m3 模型指南：https://zilliz.com/ai-models/bge-m3
