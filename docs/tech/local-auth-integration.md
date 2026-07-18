# 本地 GitHub OAuth 与 SMTP 联调

本文用于没有公网服务器和域名时，在同一台电脑完成 GitHub 登录、账号绑定、邮箱验证和密码恢复的真实联调。

## 本地地址

本地认证链路统一使用以下地址：

- 用户端：`http://localhost:5173`
- 后端 API：`http://localhost:8000`
- GitHub OAuth 回调：`http://localhost:8000/api/v1/auth/github/callback`

不要在同一次 OAuth 流程中混用 `localhost` 和 `127.0.0.1`。认证 Cookie 按主机保存，混用可能导致回调无法读取发起授权时写入的 Cookie。

## 环境文件

使用 Podman Compose 时，在项目根目录创建本地环境文件：

```bash
cp .env.example .env
```

直接在宿主机启动后端时，后端从当前工作目录读取 `.env`：

```bash
cp .env.example backend/.env
```

`.env` 和 `backend/.env` 已被 Git 忽略，不要把 OAuth Secret、SMTP 授权码或邮箱密码提交到仓库。

## GitHub OAuth

在 GitHub 创建 OAuth App，并填写：

```text
Homepage URL:
http://localhost:5173

Authorization callback URL:
http://localhost:8000/api/v1/auth/github/callback
```

把生成的凭据写入实际使用的 `.env`：

```dotenv
AUTH_GITHUB_CLIENT_ID=你的-client-id
AUTH_GITHUB_CLIENT_SECRET=你的-client-secret
AUTH_GITHUB_CALLBACK_URL=http://localhost:8000/api/v1/auth/github/callback
AUTH_FRONTEND_BASE_URL=http://localhost:5173
```

修改后重启后端。登录页的 GitHub 入口会在首次授权时创建账号；已登录用户可在个人中心绑定 GitHub。

## SMTP 邮件

本地后端可以直接连接外部 SMTP 服务，不需要本地搭建邮件服务器。先从邮件服务商获取 SMTP 主机、端口、用户名和授权码，再配置：

```dotenv
AUTH_EMAIL_BACKEND=smtp
AUTH_EMAIL_FROM_ADDRESS=发件邮箱
AUTH_EMAIL_FROM_NAME=408 学习工作台
AUTH_EMAIL_REPLY_TO=
AUTH_SMTP_HOST=SMTP主机
AUTH_SMTP_PORT=587
AUTH_SMTP_USERNAME=SMTP用户名
AUTH_SMTP_PASSWORD=SMTP授权码
AUTH_SMTP_SECURITY=starttls
AUTH_SMTP_TIMEOUT_SECONDS=10
```

使用隐式 TLS 的服务商通常改为：

```dotenv
AUTH_SMTP_PORT=465
AUTH_SMTP_SECURITY=ssl
```

优先使用服务商生成的 SMTP 授权码或应用专用密码，不要填写邮箱网页登录密码。

验证邮件中的链接指向 `localhost:5173`，需要在运行用户端的这台电脑上打开。也可以在其他设备查看邮件，再把 6 位验证码输入本机验证页面。

## 启动

使用 Podman Compose：

```bash
podman-compose -f docker-compose.podman.yml up -d backend frontend
```

用户端容器会把 `/api` 请求代理到 Compose 网络内的 `backend:8000`，浏览器仍通过 `http://localhost:5173` 访问。

直接在宿主机启动：

```bash
cd backend
source venv/bin/activate
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

另开终端启动用户端：

```bash
cd frontend
npm run dev
```

## 验收顺序

1. 使用邮箱注册，确认收到验证邮件，并分别测试 6 位验证码和验证链接。
2. 从登录页发起 GitHub 登录，确认首次授权自动创建账号。
3. 使用邮箱账号登录，在个人中心绑定 GitHub。
4. 发起密码找回，确认重置邮件和链接可用。

本地联调完成后仍不能供外部用户访问。正式上线时需要把前端地址、后端地址、GitHub 回调和邮件链接基址统一替换为公网 HTTPS 地址。
