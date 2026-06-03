# 环境搭建问题排查指南

## 原则

**遇到环境搭建问题时，AI必须：**
1. **立即停止当前操作**
2. **明确告知用户问题**
3. **说明需要什么配合**
4. **提供替代方案**

**禁止：**
- ❌ 反复重试同一操作超过3次
- ❌ 静默失败继续执行
- ❌ 跳过问题继续后续步骤
- ❌ 假设问题已解决

---

## 常见问题分类

### 1. Docker相关问题

#### 问题：Docker未安装
```
症状：docker: command not found
AI应告知：
- 问题：Docker未安装
- 需要你：安装Docker Desktop（Mac/Windows）或docker-ce（Linux）
- 参考：https://docs.docker.com/get-docker/
- 替代方案：本地安装依赖（npm/pip）
```

#### 问题：Docker Compose版本不兼容
```
症状：docker-compose: command not found 或版本错误
AI应告知：
- 问题：Docker Compose版本不兼容
- 需要你：
  1. 检查docker compose版本（docker compose version）
  2. 如使用旧版docker-compose，请升级到v2
  3. 或修改docker-compose.yml格式适配旧版
- 替代方案：手动启动各个服务
```

#### 问题：端口冲突
```
症状：Bind for 0.0.0.0:XXXX failed: port is already allocated
AI应告知：
- 问题：端口XXXX被占用
- 需要你：
  1. 检查占用端口的进程（lsof -i :XXXX）
  2. 停止占用进程，或
  3. 修改docker-compose.yml中的端口映射
- 我可以：帮你修改端口配置
```

#### 问题：镜像拉取失败
```
症状：Error pulling image... connection refused / timeout
AI应告知：
- 问题：无法拉取Docker镜像
- 需要你：
  1. 检查网络连接
  2. 配置Docker镜像加速器（国内）
  3. 或手动下载镜像
- 替代方案：使用本地构建（build instead of pull）
```

---

### 2. Node.js/npm相关问题

#### 问题：Node版本不兼容
```
症状：npm ERR! notsup Required: {"node":">=18.0.0"}
AI应告知：
- 问题：Node.js版本过低
- 需要你：
  1. 检查当前版本（node -v）
  2. 升级到Node 18+（推荐20）
  3. 使用nvm管理多版本
- 我可以：提供nvm安装命令
```

#### 问题：npm install失败
```
症状：npm ERR! ERESOLVE unable to resolve dependency tree
AI应告知：
- 问题：依赖冲突
- 需要你：
  1. 删除node_modules和package-lock.json
  2. 使用npm install --legacy-peer-deps
  3. 或切换到yarn/pnpm
- 我可以：修改package.json解决冲突
```

#### 问题：权限错误
```
症状：EACCES: permission denied
AI应告知：
- 问题：npm权限不足
- 需要你：
  1. 不要sudo运行npm
  2. 修改npm全局目录权限
  3. 或使用nvm安装的node
- 我可以：提供权限修复命令
```

---

### 3. Python相关问题

#### 问题：Python版本不兼容
```
症状：SyntaxError 或 requires-python
AI应告知：
- 问题：Python版本不匹配
- 需要你：
  1. 检查当前版本（python --version）
  2. 安装Python 3.11
  3. 使用pyenv管理多版本
- 我可以：提供pyenv安装命令
```

#### 问题：pip install失败
```
症状：Could not find a version that satisfies the requirement
AI应告知：
- 问题：依赖安装失败
- 需要你：
  1. 检查网络连接
  2. 使用国内镜像（清华/阿里）
  3. 升级pip（pip install --upgrade pip）
- 我可以：修改requirements.txt使用兼容版本
```

#### 问题：虚拟环境未激活
```
症状：ModuleNotFoundError: No module named 'xxx'
AI应告知：
- 问题：依赖未安装或未激活虚拟环境
- 需要你：
  1. 创建虚拟环境（python -m venv venv）
  2. 激活虚拟环境（source venv/bin/activate）
  3. 安装依赖（pip install -r requirements.txt）
- 我可以：提供完整的命令
```

---

### 4. 数据库相关问题

#### 问题：Neo4j连接失败
```
症状：Failed to establish connection to Neo4j
AI应告知：
- 问题：无法连接Neo4j
- 需要你：
  1. 检查Neo4j是否运行（docker ps）
  2. 检查端口是否正确（7474/7687）
  3. 检查认证信息（用户名/密码）
- 我可以：检查配置并修复
```

#### 问题：Redis连接失败
```
症状：Connection refused to Redis
AI应告知：
- 问题：无法连接Redis
- 需要你：
  1. 检查Redis是否运行
  2. 检查端口（6379）
  3. 检查密码配置
- 替代方案：使用内存缓存（开发环境）
```

---

### 5. API/网络相关问题

#### 问题：OpenAI API Key未配置
```
症状：AuthenticationError: No API key provided
AI应告知：
- 问题：OpenAI API Key未配置
- 需要你：
  1. 获取OpenAI API Key（https://platform.openai.com/）
  2. 配置到.env文件（OPENAI_API_KEY=sk-...）
  3. 确保账户有余额
- 注意：API Key不要提交到Git
```

#### 问题：CORS错误
```
症状：CORS policy: No 'Access-Control-Allow-Origin'
AI应告知：
- 问题：跨域请求被阻止
- 需要你：
  1. 检查后端CORS配置
  2. 确认前端请求地址正确
  3. 开发环境可临时允许所有域
- 我可以：修复后端CORS配置
```

---

## AI自检清单

在继续执行前，AI必须确认：

- [ ] 上一步操作是否成功？
- [ ] 是否有错误输出？
- [ ] 是否验证了结果？
- [ ] 是否需要用户配合？

如果任一问题为"是"，必须停止并告知用户。

---

## 用户配合事项模板

当需要用户配合时，使用以下格式：

```markdown
## ⚠️ 需要你的配合

**问题**：简要描述问题

**需要你做的**：
1. 具体步骤1
2. 具体步骤2
3. 具体步骤3

**验证方法**：如何确认问题已解决

**替代方案**：如果不方便操作，可以...

**参考链接**：相关文档
```

---

## 快速修复命令

### 重置环境
```bash
# 前端
rm -rf node_modules package-lock.json
npm install

# 后端
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Docker
docker-compose down -v
docker-compose up -d
```

### 检查状态
```bash
# 检查端口占用
lsof -i :8000
lsof -i :5173
lsof -i :7474
lsof -i :6379

# 检查Docker
docker ps
docker-compose ps

# 检查版本
node -v
python --version
docker --version
```
