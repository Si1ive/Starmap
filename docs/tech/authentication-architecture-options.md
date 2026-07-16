# 用户认证技术方案与数据模型

> 状态：技术评审稿
> 最后更新：2026-07-16
> 调研基线：2026-07
> 对应 PRD：`docs/product/authentication-and-user-account-prd.md`

## 1. 现状审计

### 1.1 用户端

当前 `frontend/src/auth.ts` 只检查浏览器是否存在：

```text
starmap.authenticated=true
```

该值可由任何人修改，不是认证凭据，也没有服务端用户。`RequireAuth` 只能隐藏页面，
不能保护 API。

### 1.2 后端

- `/api/v1/chat` 匿名可调用。
- `/api/v1/chat/{session_id}/history` 匿名可读取。
- `chat_sessions.user_id` 可空，当前写入时没有真实用户。
- `user_question_records` 只有 `session_id`，没有 `user_id` 外键。
- Redis 会话是聊天缓存，不是登录会话。

这意味着当前系统存在对象级授权缺失：知道会话 ID 的人可能读取或续写不属于自己的
对话。

### 1.3 管理端

管理端已有：

- `admin_users`。
- PBKDF2/bcrypt 密码兼容。
- JWT access token。
- FastAPI 管理路由依赖。

但管理端 token 保存在 Zustand 持久化存储中，本质上落入 localStorage；登出也没有
服务端撤销状态。该实现可以继续服务当前开发环境，但不建议复制到用户端。

## 2. 不可破坏的技术原则

1. `users.id` 是用户数据归属的唯一稳定标识。
2. 邮箱、昵称、GitHub username 和 session ID 不能作为业务外键。
3. 所有用户私有 API 默认拒绝匿名访问。
4. 每次访问具体资源都执行对象级授权。
5. 浏览器 JavaScript 不持有长期 access token 或 refresh token。
6. GitHub OAuth 使用服务端 Authorization Code Flow、PKCE 和 state。
7. 密码使用 Argon2id；验证、重置和会话令牌只保存摘要。
8. MySQL 是身份和业务事实源，Redis 只做限流、短状态和缓存。
9. Qdrant、Redis、对象存储也必须执行用户隔离。
10. 管理员与普通用户保持独立安全域。

## 3. 推荐结论

结合当前单体 FastAPI、MySQL、Redis 和 React 架构，推荐：

> **方案 A：FastAPI 自建身份域 + MySQL 服务端不透明会话 + Redis 限流/OAuth
> 临时状态 + Authlib 接入 GitHub + Argon2id 密码 + 可替换邮件适配器。**

理由：

- 当前只有一个主要 API，不需要 JWT 跨服务传播。
- 产品要求退出全部设备、密码重置后全部失效、账号停用、会话列表和精细绑定流程，
  服务端会话比无状态 JWT 更直接。
- 用户学习数据已经在 MySQL，内部 `user_id` 和业务事务更容易保持一致。
- 现阶段身份需求明确，尚未达到必须运行独立 IdP 的组织和 SSO 复杂度。
- 可以完整控制 GitHub 同邮箱冲突、游客数据认领和学习领域用户生命周期。

不推荐：

- 用户端复用当前管理端“JWT + localStorage”。
- 仅依赖前端路由守卫。
- 直接把 GitHub 用户 ID 当作全系统用户 ID。
- 直接采用维护模式中的框架作为长期核心边界。

## 4. 总体架构

```text
React SPA
  │
  │ same-origin HTTPS
  │ HttpOnly session cookie + CSRF header
  ▼
FastAPI /api/v1/auth/*
  ├─ IdentityService
  ├─ PasswordService (Argon2id)
  ├─ SessionService
  ├─ OAuthService (GitHub)
  ├─ EmailService adapter
  ├─ Authorization dependencies
  └─ AuthEvent recorder
       │
       ├─ MySQL: users / identities / credentials / sessions
       ├─ Redis: rate limits / OAuth state / short cache
       ├─ Mail provider
       └─ GitHub OAuth + REST API

Authenticated user dependency
  └─ user-scoped query
       ├─ MySQL business tables
       ├─ Redis user namespace
       ├─ Qdrant mandatory user_id filter
       └─ object storage authorization
```

生产环境建议由同一站点提供 SPA 和 `/api`。前后端同源可以显著降低 CORS、Cookie
和 OAuth 回调复杂度。开发环境再显式允许固定的本地 Origin。

### 4.1 用户 API 与管理 API 的服务边界结论

推荐采用以下组合，而不是简单选择“全部合并”或“立即拆成两个微服务”：

| 维度 | 首发结论 |
|------|----------|
| 代码仓库 | 同一个仓库 |
| 后端架构 | 同一个 FastAPI 模块化单体 |
| 初期部署 | 同一个后端部署单元 |
| 用户前端 | 独立 React 应用和站点 |
| 管理前端 | 独立 React 应用和管理站点 |
| 身份主体 | `users` 与 `admin_users` 分离 |
| 登录入口 | `/api/v1/auth/*` 与 `/api/v1/admin/auth/*` 分离 |
| 会话 | 用户会话与管理员会话分离 |
| 授权依赖 | `require_current_user` 与 `require_current_admin` 分离 |
| 后续扩展 | 必要时用同一代码镜像拆为 public/admin 两个部署池 |

这意味着“一个服务”只表示共享部署、数据库事务和基础设施，不表示用户和管理员共享
同一身份或同一登录状态。

当前仓库已经接近这个方向：

- `backend/app/main.py` 同时注册用户路由和 `/api/v1/admin/*` 路由。
- 后台业务 Router 在注册时统一附加 `require_current_admin`。
- 管理员使用独立的 `admin_users` 表。
- 用户端认证尚未实现，本轮应新增独立的用户身份模块，而不是复用管理员登录端点。

### 4.2 同一个后端部署的优缺点

优点：

- 只有一套 FastAPI、SQLAlchemy、Alembic、日志和部署流水线。
- 用户、学习记录和管理操作可以使用本地数据库事务。
- 不需要维护服务间认证、网络调用、消息一致性和重复 DTO。
- 当前团队和系统规模下开发、测试和排障成本最低。
- 管理端可以直接复用内容、语料、检索等领域服务，不必复制业务逻辑。

缺点：

- 公网用户流量或攻击可能耗尽进程、连接池和数据库资源，连带影响管理端。
- 用户模块故障、依赖升级和发布会同时影响后台。
- 如果模块依赖约束失效，管理端能力可能被意外暴露给用户路由。
- 管理端无法仅靠部署边界进入内网或使用独立主机权限。
- 公共 API 和高权限 API 的安全爆炸半径仍在同一进程内。

适用条件：

- 单一团队维护。
- 当前是模块化单体。
- 业务量和管理端流量有限。
- 可以通过 Router 依赖测试、WAF、限流和数据库配额保证边界。

### 4.3 两个独立后端服务的优缺点

优点：

- 管理 API 可以部署在私网、VPN、身份感知代理或独立访问控制之后。
- 用户端遭受流量攻击时，不会直接占满管理 API 的 Worker 和连接池。
- 两端可以独立扩容、发布、回滚和设置数据库权限。
- 管理端高权限代码和密钥不会加载进公共 API 进程。
- 安全事件和故障爆炸半径更小。

缺点：

- 需要两套部署、监控、配置、健康检查和发布协调。
- 内容、语料、检索等领域逻辑容易被复制，或被迫增加内部 RPC。
- 跨服务事务、缓存失效和审计一致性更复杂。
- 数据库迁移和共享模型版本需要严格协调。
- 当前应用生命周期中还启动调度器、爬虫监听和监控任务，直接启动两份相同进程可能
  重复执行后台任务，必须先拆出 Worker 生命周期或增加部署 profile。

现阶段直接拆成两个独立业务服务，成本高于收益。

### 4.4 推荐演进路线

#### 阶段 A：当前开发和邀请制内测

- 一个 FastAPI 部署。
- 用户和管理员使用两个 Router 命名空间。
- 两个前端站点通过反向代理访问同一后端。
- 所有 `/admin/*` 路由注册时强制附加管理员依赖，并增加路由契约测试。
- 公共流量使用 WAF、限流和并发上限，避免拖垮后台。

#### 阶段 B：公开上线

至少做到：

- `app.example.com` 和 `admin.example.com` 分离。
- 管理站点增加 MFA、短会话和敏感操作再认证。
- 管理域名可以增加 IP allowlist、VPN 或身份感知代理。
- 用户和管理员使用不同 Cookie 名称，且 Cookie 不设置父域 `Domain`。

如果公网流量、攻击风险或管理可用性要求明显上升，再使用同一代码镜像部署：

```text
public-api deployment
  └─ 只注册用户和公共业务路由

admin-api deployment
  └─ 只注册管理员和运营路由
```

这仍然可以保持一个代码仓库和共享领域模块，不等同于立即拆微服务。实现前需要增加
`APP_PROFILE=public|admin|all`，并把调度器、爬虫监听和后台任务从 API 生命周期中
独立出来，避免重复运行。

#### 阶段 C：满足拆服务条件后

出现以下任一情况再评估真正拆分：

- 管理 API 必须运行在独立网络或合规边界。
- 公网攻击已经影响管理端可用性。
- 用户和管理端需要明显不同的发布节奏或扩容策略。
- 管理端开始持有公共 API 不应接触的高权限云凭据。
- 两端由不同团队负责，并有清晰的领域 API 契约。

### 4.5 登录逻辑：共享基础能力，不共享安全域

可以共享：

- Argon2id 密码哈希库和参数升级逻辑。
- 随机会话令牌生成器。
- Cookie、CSRF、限流、人机校验和审计基础组件。
- 时间、IP、User-Agent 和安全事件的规范化工具。

必须分开：

| 项目 | 学习用户 | 管理员 |
|------|----------|--------|
| 账号表 | `users` | `admin_users` |
| 登录入口 | `/auth/login` | `/admin/auth/login` |
| 会话表 | `auth_sessions` | `admin_auth_sessions` |
| Cookie | `__Host-starmap_session` | `__Host-starmap_admin_session` |
| 当前主体依赖 | `require_current_user` | `require_current_admin` |
| 注册方式 | 邮箱注册、GitHub | 仅管理员邀请或受控创建 |
| MFA | 后续用户可选 | 生产环境管理员强制 |
| 保持登录 | 最长 30 天 | 不提供 |
| 建议会话 | 空闲 12 小时/绝对 7 天 | 空闲 30 分钟/绝对 8 小时 |
| 权限 | 只能管理本人资源 | RBAC/权限点 + 对象范围 |

管理员登录成功后只创建管理员会话，普通用户登录成功后只创建用户会话。后端不能使用
一个登录端点先查询邮箱，再根据命中的表或 `role` 决定进入哪个系统。

不推荐“这个邮箱是管理员，所以普通登录后自动跳后台”，原因：

1. 会暴露哪些账号属于管理员。
2. 普通用户认证漏洞可能直接升级为后台权限。
3. 管理员无法以普通学习用户身份正常使用产品。
4. 用户端 XSS、Cookie 范围错误或账号绑定错误更容易波及后台。
5. 管理员应执行更严格的 MFA、会话期限和再认证流程。

推荐交互：

```text
app.example.com/login
  └─ 只认证 users，成功后进入学习工作台

admin.example.com/login
  └─ 只认证 admin_users，完成 MFA 后进入管理后台
```

同一邮箱可以分别存在于两张表中，不自动合并。管理员需要使用学习产品时创建独立普通
用户账号。未来如需客服或运营“以用户视角查看”，应实现短时、只读优先、明确提示且
完整审计的 impersonation 流程，不得通过修改前端角色或复用用户 Cookie 实现。

### 4.6 当前管理员认证的迁移结论

当前管理端使用签名 JWT，但前端通过 Zustand persist 把 token 保存到
localStorage，`logout` 也没有服务端撤销。该方案不复制到用户端，并在生产上线前升级：

1. 新增独立 `admin_auth_sessions`，使用可撤销的服务端会话。
2. 使用独立 `HttpOnly; Secure; SameSite` 管理员 Cookie。
3. 管理员会话和用户会话使用不同摘要、Cookie 和认证版本。
4. 管理员密码成功验证时迁移到统一 Argon2id 基础组件。
5. 管理员强制 MFA，敏感操作要求近期重新认证。
6. 保留现有 `AuditLog`，并记录管理员会话 ID、目标用户 ID、权限点和结果。

## 5. 方案对比

### 5.1 方案 A：当前栈内自建服务端会话

#### 实现逻辑

- FastAPI 新建 `identity` 或 `accounts` 领域模块。
- MySQL 保存用户、身份、密码凭据和可撤销会话。
- Cookie 中放高强度随机会话令牌，数据库只保存 SHA-256 摘要。
- Redis 保存限流计数、OAuth `state`/PKCE 和短期会话缓存。
- `pwdlib[argon2]` 或直接使用 `argon2-cffi` 处理 Argon2id。
- Authlib 处理 Starlette/FastAPI OAuth 客户端流程。
- 邮件通过统一 `EmailSender` 接口接 SES、Resend、Postmark 或 SMTP。

#### 优点

- 最符合现有 FastAPI + MySQL + Redis。
- 用户和学习数据事务边界清晰。
- 会话撤销、退出全部设备和账号停用简单。
- GitHub 账号冲突和绑定策略完全可控。
- 无按月活用户计费和供应商登录页依赖。
- 用户主数据可留在现有部署区域。

#### 缺点

- 团队承担认证代码、邮件投递和安全运维责任。
- 需要系统性测试密码、令牌、CSRF、OAuth、限流和对象授权。
- 未来接企业 SSO、复杂 MFA 时开发量会上升。

#### 适用判断

当前最合适。前提是把认证当作独立安全模块，而不是在现有登录页里临时拼接接口。

### 5.2 方案 B：自建 JWT access + rotating refresh token

#### 实现逻辑

- 短期 access JWT 用于 API。
- refresh token 使用 HttpOnly Cookie，服务端保存 refresh token family。
- 每次刷新旋转 refresh token，检测旧 token 重用时撤销整个 family。
- 密码修改和账号停用通过 `auth_version` 或撤销表使 token 失效。

#### 优点

- 多个资源服务可以本地验证 access token。
- API 网关、移动端和多服务架构更常见。
- 短 access token 减少每次请求查会话库的需要。

#### 缺点

- refresh rotation、并发刷新和重放检测复杂。
- access token 在过期前通常难以立即撤销，仍需 denylist 或版本查询。
- 对当前单体 API 没有明显收益。
- 浏览器 token 存储处理不当时风险高。

#### 适用判断

当系统拆成多个独立资源服务、移动客户端成为主入口或需要对外 API 时再考虑。
即使采用 JWT，也应通过 BFF/HttpOnly Cookie 避免把 refresh token 暴露给 SPA。

### 5.3 方案 C：FastAPI Users

#### 实现逻辑

- 使用框架提供的注册、登录、邮箱验证、重置密码、OAuth 和 current user 依赖。
- 接 SQLAlchemy 异步适配和 Cookie/数据库策略。
- 在框架生命周期钩子中接用户档案和学习数据。

#### 优点

- 功能覆盖面大，初始路由开发快。
- FastAPI 集成和类型支持较好。
- 支持 Cookie、数据库、Redis 和 OAuth。

#### 缺点

- 项目目前处于 maintenance mode，只做安全和依赖维护，不再增加新功能。
- 账号绑定、邮箱变更和本项目的用户状态需要较多定制。
- 核心模型和路由容易被框架约束。
- 后续迁移到其继任工具存在不确定性。

#### 适用判断

可用于参考实现和快速原型，不建议作为本系统未来数年的核心身份边界。

### 5.4 方案 D：托管 IdP，Clerk 或 Auth0

#### 实现逻辑

- React 使用官方 SDK 和托管/嵌入式登录组件。
- IdP 处理邮箱密码、验证、GitHub、MFA、会话和邮件。
- FastAPI 验证 IdP 签发的 token 或使用同源 Cookie。
- MySQL 仍保留本地 `users`，通过 `(provider, external_subject)` 映射。
- 所有学习数据继续绑定本地 `users.id`，不能直接绑定供应商 user ID。

#### Clerk 优点

- React 集成速度快。
- 现成用户资料、会话和社交登录体验。
- 自动处理多种账号绑定场景。

#### Auth0 优点

- OIDC/OAuth 能力成熟。
- 企业连接、Actions、MFA 和审计能力更完整。
- 适合后续多应用和企业客户。

#### 共同缺点

- 供应商锁定和持续费用。
- 登录事件、用户主数据和业务数据分散。
- 自定义账号合并和异常流程受供应商模型限制。
- 需评估个人信息跨境、数据处理协议和服务可用性。
- 故障和配额会直接阻断全部用户登录。

#### 适用判断

若目标是极快上线，且可以接受供应商成本与数据处理边界，这是最省开发时间的路线。
Clerk 更偏 React 产品团队，Auth0 更偏复杂身份和企业扩展。

### 5.5 方案 E：Supabase Auth、Firebase Auth 或云平台认证

#### 实现逻辑

- 使用云平台 SDK 完成邮箱密码、社交登录和 session。
- FastAPI 验证平台 token。
- MySQL 建本地用户映射。

#### 优点

- 社交登录和邮件流程开箱较快。
- 与各自云平台的数据、函数和监控集成较深。
- Supabase 支持 GitHub、密码、OTP 和 JWT；Firebase 前端生态成熟。

#### 缺点

- Supabase Auth 的最佳体验与 PostgreSQL/RLS 绑定，本项目主库是 MySQL，会引入第二套
  数据平台。
- Firebase 更适合深度使用 Google/Firebase 生态的项目。
- 账号生命周期和本地学习数据仍需自行映射。
- 同样存在供应商、合规、跨境和可用性依赖。

#### 适用判断

只有决定整体迁移到相应云平台时才优先。单独为了登录引入，不如方案 A 或 D 清晰。

### 5.6 方案 F：自托管 Keycloak

#### 实现逻辑

- 独立部署 Keycloak，应用通过 OIDC Authorization Code + PKCE 登录。
- Keycloak 管理邮箱验证、密码、会话、MFA 和 GitHub identity broker。
- FastAPI 作为 OIDC client/resource server。
- MySQL 业务库保留本地 `users`，映射 Keycloak `sub`。

#### 优点

- 标准 OIDC/SAML，支持 GitHub identity brokering。
- 支持会话、MFA、账号管理、企业 SSO 和管理员控制。
- 身份数据可自托管，减少 SaaS 锁定。
- 多个应用共享登录时价值明显。

#### 缺点

- 需要独立服务、数据库、升级、备份和高可用。
- 登录页面主题和用户流程定制成本较高。
- 对当前单产品和少量身份方式明显偏重。
- Keycloak 自身配置错误也会成为安全风险。

#### 适用判断

当系统出现多个产品、企业 SSO、学校组织或强 MFA 管理需求时采用。当前阶段不推荐。

### 5.7 快速比较

| 方案 | 上线速度 | 当前栈匹配 | 控制力 | 运维成本 | 锁定 | 当前建议 |
|------|----------|------------|--------|----------|------|----------|
| A 自建服务端会话 | 中 | 高 | 高 | 中 | 低 | 推荐 |
| B 自建 JWT/refresh | 中低 | 中 | 高 | 中高 | 低 | 暂缓 |
| C FastAPI Users | 高 | 高 | 中 | 中 | 中 | 不作长期核心 |
| D Clerk/Auth0 | 很高 | 中 | 中 | 低 | 高 | 快速上线备选 |
| E Supabase/Firebase | 高 | 低到中 | 中 | 低 | 高 | 生态迁移时选 |
| F Keycloak | 低 | 中 | 高 | 高 | 低 | 多应用/企业阶段 |

## 6. 推荐物理数据模型

### 6.1 ID、时间和状态约定

- 新身份域与新用户聚合根使用 UUIDv7。
- MySQL 存储为 `BINARY(16)`，API 展示标准 UUID 字符串。
- 高吞吐追加表使用 `BIGINT AUTO_INCREMENT` 主键。
- 时间统一为 UTC `DATETIME(6)`。
- 状态字段使用受应用枚举约束的 `VARCHAR`，避免数据库 Enum 扩展迁移困难。
- 所有用户范围索引把 `user_id` 放在前面。

UUIDv7 按时间排序，较随机 UUID 更有利于 B-tree 索引局部性。当前 Python 运行环境
已经是 3.14，可使用标准库 `uuid.uuid7()`。为了控制迁移风险，应先实现统一的
SQLAlchemy UUID 类型，不允许每个模块各自转换。

### 6.2 `users`

职责：稳定账户主体和生命周期，不存学习业务字段。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `BINARY(16)` | PK | UUIDv7，不可变 |
| `email_normalized` | `VARCHAR(320)` | UNIQUE，可空 | 比较和登录使用 |
| `email_display` | `VARCHAR(320)` | 可空 | 用户展示值 |
| `email_verified_at` | `DATETIME(6)` | 可空 | 主邮箱验证时间 |
| `status` | `VARCHAR(24)` | NOT NULL | `pending_email/active/suspended/deletion_pending/deleted` |
| `auth_version` | `INT UNSIGNED` | NOT NULL DEFAULT 1 | 提升后使旧认证状态失效 |
| `last_login_at` | `DATETIME(6)` | 可空 | 最近成功登录 |
| `last_login_method` | `VARCHAR(32)` | 可空 | `password/github/passkey` |
| `activated_at` | `DATETIME(6)` | 可空 | 首次激活 |
| `suspended_at` | `DATETIME(6)` | 可空 | 停用时间 |
| `deleted_at` | `DATETIME(6)` | 可空 | 删除完成时间 |
| `created_at` | `DATETIME(6)` | NOT NULL | 创建时间 |
| `updated_at` | `DATETIME(6)` | NOT NULL | 更新时间 |
| `row_version` | `INT UNSIGNED` | NOT NULL DEFAULT 1 | 乐观锁 |

索引：

- `UNIQUE uq_users_email_normalized(email_normalized)`。
- `INDEX idx_users_status_created(status, created_at)`。
- `INDEX idx_users_deleted(deleted_at)`。

规则：

- 活跃用户必须有已验证主邮箱。
- GitHub 暂时没有可信邮箱时，可创建短期 `pending_email` 用户，但不能进入业务系统。
- 删除完成后清空邮箱字段或替换为无个人含义的墓碑值，并确保同邮箱重新注册得到新 ID。
- 不使用多个 `is_active/is_deleted/is_verified` 布尔值表达互相矛盾状态。

### 6.3 `user_profiles`

职责：非敏感、可变的展示资料。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `user_id` | `BINARY(16)` | PK, FK users | 一对一 |
| `display_name` | `VARCHAR(64)` | NOT NULL | 昵称 |
| `avatar_object_key` | `VARCHAR(512)` | 可空 | 受控对象存储 key |
| `avatar_source` | `VARCHAR(24)` | 可空 | `upload/github/generated` |
| `locale` | `VARCHAR(16)` | NOT NULL DEFAULT `zh-CN` | 语言 |
| `timezone` | `VARCHAR(64)` | NOT NULL DEFAULT `Asia/Shanghai` | IANA 时区 |
| `created_at` | `DATETIME(6)` | NOT NULL |  |
| `updated_at` | `DATETIME(6)` | NOT NULL |  |

不建议直接长期保存 GitHub 头像 URL。可在用户允许时抓取到受控对象存储，避免远程
跟踪、链接失效和任意 URL 风险。

### 6.4 `auth_identities`

职责：一个内部用户可以绑定多个登录提供方。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `BINARY(16)` | PK | UUIDv7 |
| `user_id` | `BINARY(16)` | FK users, NOT NULL | 内部用户 |
| `provider` | `VARCHAR(32)` | NOT NULL | `github`，未来扩展 |
| `provider_subject` | `VARCHAR(191)` | NOT NULL | GitHub 稳定用户 ID |
| `provider_username` | `VARCHAR(191)` | 可空 | 仅展示快照 |
| `provider_email` | `VARCHAR(320)` | 可空 | 登录时快照 |
| `provider_email_verified` | `BOOLEAN` | NOT NULL DEFAULT 0 | 提供方当次声明 |
| `linked_at` | `DATETIME(6)` | NOT NULL | 绑定时间 |
| `last_login_at` | `DATETIME(6)` | 可空 |  |
| `updated_at` | `DATETIME(6)` | NOT NULL |  |

索引：

- `UNIQUE uq_identity_provider_subject(provider, provider_subject)`。
- `UNIQUE uq_identity_user_provider(user_id, provider)`，首发每个用户每种提供方一个身份。
- `INDEX idx_identity_user(user_id)`。

规则：

- 业务表永远不引用 `auth_identities.id` 或 `provider_subject`。
- 不将完整 GitHub payload 放进 JSON。
- 登录用途无需持续访问 GitHub 时不存 access token。

若未来需要 GitHub 仓库集成，新增独立 `oauth_grants` 表，token 使用 KMS/密钥服务
信封加密，记录 scope、过期和撤销状态，不能塞进本表。

### 6.5 `password_credentials`

职责：密码登录凭据，与用户主体分离。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `user_id` | `BINARY(16)` | PK, FK users | 一对一，可不存在 |
| `password_hash` | `VARCHAR(255)` | NOT NULL | PHC 格式 Argon2id |
| `hash_scheme` | `VARCHAR(32)` | NOT NULL | 便于迁移和审计 |
| `password_changed_at` | `DATETIME(6)` | NOT NULL |  |
| `must_change` | `BOOLEAN` | NOT NULL DEFAULT 0 | 风险处置 |
| `compromised_at` | `DATETIME(6)` | 可空 | 已知泄露标记 |
| `created_at` | `DATETIME(6)` | NOT NULL |  |
| `updated_at` | `DATETIME(6)` | NOT NULL |  |

规则：

- 新密码使用 Argon2id。
- 登录成功时发现参数过旧，使用 `verify_and_update` 透明升级。
- 当前管理端 PBKDF2 可以保留，普通用户新模块不继续使用 260,000 次 PBKDF2 作为
  新基线。
- 失败次数不要直接高频写本表；实时限流放 Redis，长期事件写 `auth_events`。

### 6.6 `auth_sessions`

职责：可撤销的服务端登录会话。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `BINARY(16)` | PK | 管理页面使用的会话 ID |
| `user_id` | `BINARY(16)` | FK users, NOT NULL |  |
| `token_hash` | `BINARY(32)` | UNIQUE, NOT NULL | SHA-256(session token) |
| `csrf_secret_hash` | `BINARY(32)` | NOT NULL | 同步器 CSRF secret 摘要 |
| `auth_version` | `INT UNSIGNED` | NOT NULL | 创建时用户认证版本 |
| `auth_method` | `VARCHAR(32)` | NOT NULL | 登录方式 |
| `created_ip` | `VARBINARY(16)` | 可空 | IPv4/IPv6 二进制 |
| `last_ip` | `VARBINARY(16)` | 可空 |  |
| `user_agent` | `VARCHAR(512)` | 可空 | 截断后的 UA |
| `device_label` | `VARCHAR(128)` | 可空 | 服务端解析的展示标签 |
| `created_at` | `DATETIME(6)` | NOT NULL |  |
| `last_seen_at` | `DATETIME(6)` | NOT NULL | 节流更新 |
| `idle_expires_at` | `DATETIME(6)` | NOT NULL | 空闲过期 |
| `absolute_expires_at` | `DATETIME(6)` | NOT NULL | 绝对过期 |
| `revoked_at` | `DATETIME(6)` | 可空 |  |
| `revoke_reason` | `VARCHAR(64)` | 可空 | logout/reset/suspend/reuse |

索引：

- `UNIQUE uq_session_token_hash(token_hash)`。
- `INDEX idx_session_user_active(user_id, revoked_at, absolute_expires_at)`。
- `INDEX idx_session_expiry(absolute_expires_at)`。
- `INDEX idx_session_last_seen(last_seen_at)`。

Cookie：

- 令牌至少 256 bit 随机值。
- 生产名建议 `__Host-starmap_session`。
- `Secure; HttpOnly; SameSite=Lax; Path=/`。
- 不设置 `Domain`。
- Cookie 只保存原始随机令牌；数据库和日志均不保存明文。

`SameSite=Lax` 兼顾 OAuth 和邮件顶层导航；状态变更接口仍必须使用 CSRF token 和
Origin 校验。

建议初始期限，待产品确认：

| 模式 | Cookie | 空闲期限 | 绝对期限 |
|------|--------|----------|----------|
| 不保持登录 | 浏览器会话 Cookie | 12 小时 | 7 天 |
| 保持登录 | 持久 Cookie | 7 天 | 30 天 |

`last_seen_at` 不应每个请求都写数据库，可每 5 到 15 分钟合并更新。

### 6.7 `auth_action_tokens`

职责：邮箱验证、密码重置、邮箱变更和身份绑定等一次性动作。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `BINARY(16)` | PK | UUIDv7 |
| `user_id` | `BINARY(16)` | FK users，可空 | 防枚举流程可能不创建记录 |
| `purpose` | `VARCHAR(32)` | NOT NULL | verify_email/reset_password/change_email/link_identity |
| `challenge_id` | `BINARY(16)` | NOT NULL | 同一邮件中的链接与数字码分组 |
| `token_kind` | `VARCHAR(16)` | NOT NULL | link/code |
| `token_hash` | `BINARY(32)` | UNIQUE, NOT NULL | HMAC-SHA-256 摘要 |
| `key_version` | `SMALLINT UNSIGNED` | NOT NULL | 服务端 HMAC 密钥版本 |
| `target_value` | `VARCHAR(320)` | 可空 | 例如待验证邮箱，按敏感字段保护 |
| `request_ip` | `VARBINARY(16)` | 可空 |  |
| `failed_attempts` | `SMALLINT UNSIGNED` | NOT NULL DEFAULT 0 | 数字码错误次数 |
| `max_attempts` | `SMALLINT UNSIGNED` | 可空 | 数字码建议为 5 |
| `metadata_json` | `JSON` | 可空 | 仅白名单、非核心条件 |
| `created_at` | `DATETIME(6)` | NOT NULL |  |
| `expires_at` | `DATETIME(6)` | NOT NULL |  |
| `consumed_at` | `DATETIME(6)` | 可空 | 单次消费 |
| `invalidated_at` | `DATETIME(6)` | 可空 | 重发或撤销 |

索引：

- `UNIQUE uq_action_token_hash(token_hash)`。
- `INDEX idx_action_challenge(challenge_id, token_kind)`。
- `INDEX idx_action_user_purpose(user_id, purpose, created_at)`。
- `INDEX idx_action_cleanup(expires_at, consumed_at, invalidated_at)`。

邮箱验证推荐一次发送两个凭据：

- 32-byte 随机链接令牌，有效期 30 分钟。
- 6 位密码学安全随机数字码，有效期 10 分钟，最多连续错误 5 次。

两行记录共享 `challenge_id`。任一凭据验证成功后，在同一个数据库事务中消费并使该
`challenge_id` 下其他凭据失效。数字码必须同时绑定浏览器持有的不可猜测注册事务；
不能只依赖邮箱和 6 位码。

低熵数字码不能直接使用无密钥 SHA-256，否则数据库泄露后可离线枚举。所有 action
token 统一使用带版本的服务端 HMAC-SHA-256；原始值不落库、不进日志。同一用户同一
目的的新验证事务发出后，旧事务全部失效。消费和失败次数更新使用行锁或条件更新，
避免并发双重消费和并发绕过次数限制。

### 6.8 `auth_events`

职责：安全审计、风控和用户登录历史，不保存秘密。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `BIGINT UNSIGNED` | PK AUTO_INCREMENT | 追加日志 |
| `user_id` | `BINARY(16)` | 可空 | 未识别账号时为空 |
| `session_id` | `BINARY(16)` | 可空 | 相关会话 |
| `event_type` | `VARCHAR(64)` | NOT NULL | login/register/reset/link/revoke |
| `outcome` | `VARCHAR(16)` | NOT NULL | success/failure/blocked |
| `provider` | `VARCHAR(32)` | 可空 | password/github |
| `reason_code` | `VARCHAR(64)` | 可空 | 机器可读，不保存密码错误细节 |
| `identifier_hmac` | `BINARY(32)` | 可空 | 邮箱 HMAC，用于限流分析 |
| `ip_address` | `VARBINARY(16)` | 可空 | 按固定期限保存 |
| `user_agent` | `VARCHAR(512)` | 可空 | 截断 |
| `request_id` | `VARCHAR(64)` | 可空 | 关联应用日志 |
| `created_at` | `DATETIME(6)` | NOT NULL |  |

索引：

- `INDEX idx_auth_event_user_time(user_id, created_at)`。
- `INDEX idx_auth_event_identifier_time(identifier_hmac, created_at)`。
- `INDEX idx_auth_event_type_time(event_type, created_at)`。
- `INDEX idx_auth_event_cleanup(created_at)`。

禁止记录：

- 明文密码。
- session token、CSRF token、验证 token、重置 token。
- GitHub access token 或 authorization code。
- 完整邮件正文。

### 6.9 `user_consents`

职责：记录条款、隐私说明等版本接受事实。

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | `BIGINT UNSIGNED` | PK AUTO_INCREMENT |  |
| `user_id` | `BINARY(16)` | FK users, NOT NULL |  |
| `document_type` | `VARCHAR(32)` | NOT NULL | terms/privacy/minor_policy |
| `document_version` | `VARCHAR(32)` | NOT NULL | 不可变版本 |
| `accepted_at` | `DATETIME(6)` | NOT NULL |  |
| `ip_address` | `VARBINARY(16)` | 可空 |  |
| `source` | `VARCHAR(32)` | NOT NULL | register/settings/migration |

索引：

- `UNIQUE uq_consent_version(user_id, document_type, document_version)`。
- `INDEX idx_consent_user(user_id, accepted_at)`。

条款接受记录不应被当作所有个人信息处理活动的万能法律依据，处理目的和必要性仍需
单独评估。

### 6.10 可选运营表

`email_deliveries`：

- 记录模板、发送状态、供应商 message ID、收件人 HMAC、失败分类和时间。
- 不保存完整邮件正文和明文 token。
- 用于排查投递、退信和供应商切换。

`account_deletion_jobs`：

- 当用户数据量较大时，记录各存储系统删除进度、重试和完成时间。
- MySQL、Redis、Qdrant、对象存储分别有步骤状态。

## 7. 业务表改造

### 7.1 `chat_sessions`

必须：

- `user_id` 改为 `BINARY(16) NOT NULL` 并建立 FK。
- 创建会话时从 `current_user.id` 写入，不接受请求体传入 user ID。
- 查询历史使用 `WHERE id=? AND user_id=?`。
- 列表索引使用 `(user_id, updated_at, id)`。

`chat_messages` 可通过 `chat_sessions` 继承归属，但读取、删除和 SSE 订阅必须 join
父表校验当前用户。

### 7.2 `user_question_records`

当前 `session_id` 不能表达用户所有权。建议演进为：

- 新增 `user_id BINARY(16) NOT NULL`。
- 新增正式 `practice_session_id`。
- 保留 `session_id` 仅用于兼容迁移，随后删除。
- 索引至少包括：
  - `(user_id, created_at, id)`。
  - `(user_id, question_id, created_at)`。
  - `(practice_session_id, created_at)`。

历史题目内容应通过练习题快照保存，避免题库更新后篡改历史作答语义。

### 7.3 后续用户聚合根

建议每个聚合根直接有 `user_id`：

| 表 | 归属 |
|----|------|
| `learner_profiles` | 用户一对一学习档案 |
| `agent_threads` | 用户 Agent 线程 |
| `practice_sessions` | 用户练习会话 |
| `mistake_records` | 用户错题 |
| `learning_goals` | 用户目标 |
| `study_plans` | 用户计划 |
| `review_schedules` | 用户复习调度 |
| `user_sources` | 用户上传资料 |
| `user_notes` | 用户笔记 |

高频子表是否冗余 `user_id` 的判断：

- 默认通过聚合根外键继承，避免不一致。
- 只有在分区、归档、超高频授权查询或独立生命周期确有收益时才冗余。
- 一旦冗余，必须用创建服务统一写入并增加一致性测试。

### 7.4 删除策略

小型认证表可 `ON DELETE CASCADE`：

- profile、credential、identity、session、action token。

大体量学习表不建议依赖一次巨型级联：

- 账号注销先进入 `deletion_pending`。
- 后台任务按 `user_id` 和主键游标分批删除。
- 每张表都必须有 `user_id` 前导索引。
- 完成 MySQL 后再清理 Qdrant、Redis 和对象存储。
- 删除任务幂等，可从中断点继续。

## 8. API 设计

建议前缀：`/api/v1/auth` 和 `/api/v1/account`。

### 8.1 公开接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 邮箱密码注册 |
| POST | `/auth/email-verification/resend` | 重发验证 |
| POST | `/auth/email-verification/confirm` | 消费链接 token 或注册事务绑定的数字码 |
| POST | `/auth/login` | 邮箱密码登录 |
| GET | `/auth/github/start` | 创建 OAuth 事务并跳转 |
| GET | `/auth/github/callback` | 服务端 OAuth 回调 |
| POST | `/auth/password/forgot` | 发起找回 |
| POST | `/auth/password/reset` | 消费 token 并改密 |

### 8.2 已认证接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/auth/me` | 当前用户和认证状态 |
| POST | `/auth/logout` | 撤销当前会话 |
| POST | `/auth/logout-all` | 撤销全部会话 |
| GET | `/account/sessions` | 会话列表 |
| DELETE | `/account/sessions/{id}` | 撤销指定会话 |
| PATCH | `/account/profile` | 修改非敏感资料 |
| POST | `/account/password/change` | 近期认证后改密 |
| POST | `/account/email/change/request` | 请求新邮箱 |
| POST | `/account/email/change/confirm` | 确认新邮箱 |
| GET | `/account/identities` | 登录方式列表 |
| GET | `/account/identities/github/start` | 绑定 GitHub |
| DELETE | `/account/identities/{id}` | 解绑登录方式 |
| POST | `/account/export` | 创建导出任务 |
| DELETE | `/account` | 注销账号 |

### 8.3 响应规则

- 登录、注册、忘记密码和重发验证使用通用提示，避免枚举。
- `/auth/me` 未登录返回 `401`。
- 私有资源无权访问统一返回 `404`。
- Cookie 认证接口设置 `Cache-Control: no-store`。
- 创建类接口接受 `Idempotency-Key`。
- 所有者从服务端会话注入，请求 schema 不出现 `user_id`。

## 9. GitHub OAuth 实现细节

### 9.1 OAuth App 与 GitHub App

如果目标仅是“使用 GitHub 登录”，OAuth App 已足够，权限和配置更简单。若未来需要
以应用身份操作仓库、细粒度仓库授权和短期安装 token，再评估 GitHub App。

### 9.2 必需防护

- Authorization Code Flow。
- `state` 使用不可预测随机值并绑定浏览器事务。
- PKCE 使用 `S256`。
- 回调 URI 固定配置，不接受客户端任意 URI。
- `return_to` 只允许站内路径白名单。
- 授权码交换只在服务端进行。
- 每次登录后重新调用 GitHub API 验证当前身份。
- 外部身份键使用 GitHub user ID，不使用 login 或 email。
- OAuth 临时状态放 Redis，TTL 建议 10 分钟，并且单次消费。

### 9.3 邮箱处理

- 无 scope 时可能拿不到私有邮箱。
- 若产品要求 GitHub 用户必须有可联系主邮箱，可申请只读 `user:email`。
- 从邮箱列表选择 `primary=true && verified=true`。
- 没有可信邮箱时进入补充邮箱流程。
- GitHub 的邮箱只是身份提供方快照，不能每次登录覆盖本系统邮箱。

### 9.4 Token 处理

仅登录时：

1. 交换 access token。
2. 读取 `/user` 和必要的 `/user/emails`。
3. 完成本地身份映射。
4. 丢弃 access token。

未来需要 GitHub API 集成时，才新增加密 grant 存储，并对 scope、撤销、轮换和删除
单独建模。

## 10. 密码实现

推荐依赖：

```text
pwdlib[argon2]
```

使用 `PasswordHash.recommended()`，并在部署环境做性能校准，使单次验证达到可接受的
CPU/内存成本。OWASP 当前 Argon2id 最低建议之一是 19 MiB、2 次迭代、并行度 1；
最终参数以生产实例压测为准，不能直接照抄开发机结果。

规则：

- 注册和改密前检查泄露/常见密码 blocklist。
- 登录对不存在账号使用固定 dummy hash，降低时间枚举。
- 成功登录时透明 rehash。
- 密码最大输入长度在进入昂贵哈希前限制，防止资源耗尽。
- 不记录密码长度、字符组成或校验失败片段。

## 11. Cookie、CSRF 与浏览器状态

### 11.1 登录状态

前端启动流程：

1. React 加载。
2. 请求 `/api/v1/auth/me`，浏览器自动携带 HttpOnly Cookie。
3. `200` 时写入内存中的 current user。
4. `401` 时进入未登录状态。
5. 不把 token 或 `authenticated=true` 作为事实源。

可以在内存缓存用户资料，但刷新后必须重新向服务端确认。

### 11.2 CSRF

推荐 synchronizer token：

- 会话创建时生成 CSRF secret，服务端保存摘要或派生值。
- 前端从 `/auth/csrf` 或 `/auth/me` 响应获得非秘密展示 token。
- 所有 POST/PUT/PATCH/DELETE 通过 `X-CSRF-Token` 发送。
- 服务端同时校验 token 和 Origin。
- OAuth callback 使用独立 state/PKCE，不复用普通 CSRF token。

### 11.3 安全响应头

认证页面和 API 至少配置：

- `Strict-Transport-Security`。
- `Content-Security-Policy`，限制脚本、连接和 frame。
- `X-Content-Type-Options: nosniff`。
- `Referrer-Policy: no-referrer` 或严格策略。
- `frame-ancestors 'none'`。
- `Cache-Control: no-store` 用于认证和敏感响应。

## 12. 限流与风控

Redis 使用滑动窗口、令牌桶或成熟限流实现。key 中使用邮箱 HMAC，而不是明文邮箱。

建议初始策略，不作为公开产品承诺：

| 流程 | 维度 | 初始策略 |
|------|------|----------|
| 登录 | IP | 短窗口限制 + 渐进延迟 |
| 登录 | identifier HMAC | 连续失败限制 |
| 注册 | IP + 邮箱 | 小时级限制 |
| 验证重发 | 用户 + 邮箱 | 冷却时间 + 小时上限 |
| 忘记密码 | IP + 邮箱 | 通用响应 + 小时上限 |
| OAuth start | IP + 浏览器事务 | 防状态表耗尽 |

注意：

- 不永久锁定账号。
- 限流服务故障时，认证不能完全无保护地 fail open。
- Redis 不可用时应有进程内低容量保护和告警；多实例场景仍以 Redis 为准。
- 不能只使用 `(IP, identifier)` 组合桶；IP 桶和 identifier 桶必须独立检查。
- CAPTCHA 的可见交互只在达到风险阈值后出现。

### 12.1 人机校验决策

实现统一接口，业务层不直接依赖供应商 SDK：

```text
AntiBotVerifier.verify(
    token,
    action,
    remote_ip,
    expected_hostname,
) -> AntiBotDecision
```

策略：

- `/register`、`/email-verification/resend`、`/password/forgot` 每次提交反自动化票据；
  正常用户走无感验证，供应商判断高风险时再展示交互挑战。
- `/login` 首次不要求票据，账号或 IP 连续失败、代理池特征或异常速率出现后才要求。
- `/github/start` 默认限流，只有异常流量才触发挑战。
- 邮箱确认、`/auth/me`、退出和正常已认证 API 不依赖人机校验供应商。
- 供应商结果只是一个风险信号，不能代替业务限流、账号限流和审计。

供应商可选项：

| 方案 | 适用 | 优点 | 代价 |
|------|------|------|------|
| Cloudflare Turnstile | 海外或已使用 Cloudflare 的部署 | 接入简单，可独立使用，有免费方案 | 需验证目标用户网络可达性和数据区域 |
| 阿里云验证码 2.0 | 中国内地部署 | 有中国内地区域和无感/风险挑战 | 按量成本和阿里云依赖 |
| 腾讯云验证码 | 中国内地部署 | Web/App 票据和服务端风险结果 | 按量成本和腾讯云依赖 |
| reCAPTCHA Enterprise | Google Cloud 体系 | 风险评分和账号防护能力成熟 | 中国内地可达性、成本和数据区域需评估 |

无论供应商如何选择：

- 前端票据必须提交后端，再由后端调用供应商服务端校验。
- 校验 action、hostname/场景、有效期和单次使用属性。
- 密钥只在服务端保存；使用独立低权限凭据。
- 供应商超时设置短超时和熔断。受保护匿名写操作校验失败时返回 `503` 或通用重试
  提示，不执行用户创建和邮件发送。
- 记录 action、结果、错误类型和延迟，不记录供应商原始设备指纹。

最终供应商取决于生产部署区域。中国内地优先实测阿里云或腾讯云；海外部署优先
Turnstile。该选择不影响业务接口。

### 12.2 CAPTCHA 之外的抗宕机方案

CAPTCHA 防的是功能滥用，不是完整 DDoS 方案。生产入口需要：

1. CDN + WAF + 云厂商 DDoS 防护隐藏和保护源站。
2. 网关对连接、每 IP 请求、请求体、上传、慢请求和总并发设置硬上限。
3. 应用按 endpoint、IP、identifier、session、user 独立限流。
4. 邮件、文件解析和 Agent 任务进入有界队列，设置单用户并发、超时和成本预算。
5. 数据库连接池、Redis 连接池和外部 HTTP 连接池均设置上限与获取超时。
6. 对邮件、模型和人机校验供应商使用超时、熔断和全局预算。
7. 为注册、邮件发送、匿名聊天、文件解析和模型调用设置独立紧急开关。
8. 监控边缘拦截量、源站 RPS、`429/503`、队列深度、连接池、CPU、内存和供应商费用。

`robots.txt` 和 User-Agent 黑名单不构成安全边界。对登录后的高成本接口，用户配额和
并发限制比 CAPTCHA 更可靠。

## 13. 邮件方案

### 13.1 注册验证方式决策

首发必须验证邮箱所有权，但邮箱不是实名证明，也不作为第二因素。验证邮件同时提供：

1. **主方式：高熵 HTTPS 验证链接。** 点击成本低，令牌强度高。
2. **备用方式：6 位数字确认码。** 用户在手机查看邮件、桌面完成注册时可手动回填。

收益：

- 过滤拼写错误、不可达或由他人随意填写的邮箱。
- 保证后续密码找回、安全通知和账号变更通知有可用通道。
- 提高批量虚假账号的成本，并减少无效账号污染用户数据。
- 在 GitHub 缺少可用验证邮箱时，为内部账号建立稳定的恢复邮箱。

限制：

- 只能证明当时能访问该邮箱，不能证明用户真实身份。
- 会增加注册步骤、邮件费用、投递延迟和退信处理。
- 邮箱被接管时仍可能导致账号风险，因此不能把邮件验证码当作 MFA。

建议参数：

| 凭据 | 有效期 | 尝试次数 | 绑定 |
|------|--------|----------|------|
| 高熵链接 | 30 分钟 | 单次使用 | purpose + challenge + user |
| 6 位数字码 | 10 分钟 | 最多 5 次 | purpose + challenge + pre-auth transaction |

原注册浏览器轮询验证状态或在用户返回页面时刷新状态。链接在其他浏览器打开时只完成
邮箱验证，不直接登录；只有持有匹配 pre-auth transaction 的原浏览器可以自动升级为
正式会话。

### 13.2 SMTP

优点：

- 通用、供应商可替换。
- 初始接入简单。

缺点：

- 投递事件、退信和投诉处理能力取决于供应商。
- 网络超时和连接池处理更复杂。

### 13.3 邮件 API：Resend 或 Postmark

优点：

- 开发接口简单，模板和投递事件较清晰。
- Webhook 便于更新投递状态。

缺点：

- 外部供应商依赖。
- 需评估部署地区、数据跨境、域名信誉和费用。

### 13.4 AWS SES

优点：

- 规模和成本控制能力强。
- 与云上队列、事件和权限体系集成好。

缺点：

- 域名验证、生产权限、退信和信誉运营配置较多。
- 若主系统不在 AWS，初始运维复杂度更高。

### 13.5 推荐抽象

不在业务服务中直接调用供应商 SDK：

```text
EmailSender.send(template_id, recipient, variables, idempotency_key)
```

邮件先写 outbox 或任务队列，再由 worker 发送。数据库事务只负责创建用户和事件，
邮件失败通过重试解决。

## 14. 迁移方案

### 阶段 1：身份域落库

- 新增核心认证表和模型。
- 新增 `/auth/*`。
- 新增 current user 依赖。
- 用户端改为 `/auth/me` 恢复状态。

### 阶段 2：保护公共用户 API

- `/chat` 和 history 默认依赖 current user。
- 创建 `chat_sessions` 时写 `user_id`。
- 所有历史查询增加用户范围。
- 增加 A/B 用户对象越权测试。

### 阶段 3：迁移做题记录

- `user_question_records` 新增 nullable `user_id`。
- 新代码双写真实 `user_id`。
- 旧演示数据隔离、删除或标记 orphan，不按客户端 session ID 自动认领。
- 清理后将 `user_id` 改为 NOT NULL。
- 淘汰临时 session 所有权逻辑。

### 阶段 4：扩展全部学习对象

- Agent thread/run。
- 练习、错题、掌握度、计划。
- 用户资料、Qdrant payload 和对象存储。

### 阶段 5：账号设置和生命周期

- 会话管理。
- 修改密码、邮箱和绑定身份。
- 导出、注销和跨存储删除任务。

## 15. 测试门禁

### 15.1 单元测试

- 邮箱规范化和唯一性。
- 密码 hash、verify、rehash。
- action token 生成、摘要、过期、单次消费。
- session 创建、空闲过期、绝对过期、撤销和 auth_version。
- OAuth state、PKCE 和 return path 白名单。
- 账号状态转换。

### 15.2 集成测试

- 注册到验证到登录。
- GitHub 新用户、已有身份、邮箱冲突、无邮箱。
- 忘记密码通用响应和全部会话失效。
- CSRF 缺失、错误 Origin、过期 Cookie。
- Redis 降级和邮件任务重试。
- 并发重复使用同一 token 只有一次成功。

### 15.3 授权测试

每类用户私有资源必须统一覆盖：

1. 用户 A 创建资源。
2. 用户 B 用该资源 ID 执行读取、修改、删除、导出。
3. HTTP、WebSocket、SSE、文件下载均拒绝。
4. 管理员没有明确权限时也不能读取。

没有这组测试，不得上线任何新的用户私有资源。

### 15.4 安全测试

- XSS 下 JavaScript 无法读取 session Cookie。
- CSRF 跨站 POST 被拒绝。
- OAuth state 不匹配和 code 重放被拒绝。
- 登录和重置账号枚举测试。
- 高频请求限流。
- 日志扫描确认不包含密码、token、authorization code。
- 依赖漏洞和密钥泄露扫描。

## 16. 监控与告警

指标：

- `auth_login_total{method,outcome,reason}`。
- `auth_register_total{outcome}`。
- `auth_email_delivery_total{template,status}`。
- `auth_token_consume_total{purpose,outcome}`。
- `auth_rate_limited_total{flow}`。
- `auth_active_sessions`。
- `auth_api_duration_seconds`。
- `auth_cross_user_denied_total{resource_type}`。

告警：

- 登录失败突然增加。
- 单 IP 或单网段大规模账号尝试。
- 重置/验证邮件激增。
- GitHub OAuth 回调失败率上升。
- 邮件退信和投诉异常。
- Redis 限流不可用。
- 认证数据库查询延迟上升。
- 对象级授权拒绝异常增加。

日志中只保留 request ID、内部 user ID、事件类型和脱敏网络信息。

## 17. 实施拆分

### 切片 1：可信会话

- 核心表。
- 邮箱注册、验证、登录、退出、`/me`。
- Cookie、CSRF、限流。
- 用户端删除伪认证。

### 切片 2：GitHub

- OAuth App 配置。
- state + PKCE。
- 身份映射和安全绑定。
- GitHub 登录 UI。

### 切片 3：用户资源保护

- 对话和做题记录绑定真实用户。
- 私有 API 默认认证。
- 对象级授权测试。

### 切片 4：账号恢复和设置

- 忘记密码。
- 修改密码、邮箱。
- 会话管理和退出全部设备。

### 切片 5：生命周期

- 账号停用。
- 数据导出。
- 注销和跨存储删除。
- 登录提醒和安全中心。

### 切片 6：增强认证

- Passkey。
- TOTP 和恢复码。
- 管理员认证升级。

## 18. 需要拍板的路线

推荐默认选择：

| 决策 | 推荐 |
|------|------|
| 身份平台 | 当前 FastAPI 内自建 |
| 会话 | MySQL 服务端不透明会话 Cookie |
| 浏览器 token | 不使用 localStorage/sessionStorage |
| 后端服务 | 一个模块化单体，初期一个部署，保留 public/admin 双部署能力 |
| 用户与管理员 | 两套账号、会话、Cookie 和授权安全域 |
| 密码 | Argon2id，最少 15，最大 128 |
| GitHub | OAuth App，Code + PKCE + state |
| OAuth 同邮箱 | 证明现有账号后再绑定 |
| 用户 ID | UUIDv7，MySQL `BINARY(16)` |
| 邮箱验证 | 高熵链接为主 + 6 位数字码备用 |
| 人机校验 | 发邮件入口每次校验无感票据，登录按风险触发 |
| 邮件 | 抽象适配器 + 异步 outbox/worker |
| 私有资源 | `user_id` + 每请求对象级授权 |

需要业务确认：

1. 是否接受自建认证带来的安全开发责任。
2. 是否坚持 15 字符密码基线。
3. 邮件供应商和数据区域。
4. “保持登录”期限。
5. 邮箱验证后的自动登录策略。
6. 账号注销恢复期和数据保留期限。
7. 未成年人使用边界。
8. 生产部署区域对应的人机校验供应商。

## 19. 主要参考

- [OAuth 2.0 Security Best Current Practice, RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html)
- [OAuth 2.0 for Browser-Based Applications](https://datatracker.ietf.org/doc/draft-ietf-oauth-browser-based-apps/)
- [GitHub Authorizing OAuth Apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [OWASP CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)
- [OWASP IDOR Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Insecure_Direct_Object_Reference_Prevention_Cheat_Sheet.html)
- [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- [OWASP Multifactor Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Multifactor_Authentication_Cheat_Sheet.html)
- [OWASP Bot Management and Anti-Automation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Bot_Management_and_Anti-Automation_Cheat_Sheet.html)
- [OWASP Denial of Service Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html)
- [OWASP Email Validation and Verification Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Email_Validation_and_Verification_Cheat_Sheet.html)
- [NIST SP 800-63A Confirmation Codes](https://pages.nist.gov/800-63-4/sp800-63a/ial-general/)
- [CISA Identity and Access Management Recommended Best Practices](https://www.cisa.gov/sites/default/files/2023-12/ESF%20IDENTITY%20AND%20ACCESS%20MANAGEMENT%20RECOMMENDED%20BEST%20PRACTICES%20FOR%20ADMINISTRATORS%20PP-23-0248_508C.pdf)
- [FastAPI password hashing with pwdlib and Argon2](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
- [Authlib Starlette OAuth Client](https://docs.authlib.org/en/latest/client/starlette.html)
- [RFC 9562 UUIDv7](https://www.rfc-editor.org/rfc/rfc9562.html)
- [Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/)
- [Supabase Auth](https://supabase.com/docs/guides/auth)
- [FastAPI Users repository status](https://github.com/fastapi-users/fastapi-users)
