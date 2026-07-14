# MinerU 解析服务部署

> 更新日期：2026-07-14
> 适用范围：Podman 本地部署和远程 MinerU 服务部署

## 1. 部署原则

- 解析实现固定为 `MinerU`
- MinerU 重型依赖只安装在 `pdf-parser-service`
- 主 backend 通过 HTTP 调用解析服务
- 本地和远程服务使用相同的 `/health`、`/parse`、`/progress/{task_id}` 协议
- 模型缓存持久化，避免容器重建后重复下载

## 2. 本地 Podman 部署

仓库根目录的 `docker-compose.podman.yml` 已定义 `pdf-parser-service`：

```bash
podman-compose -f docker-compose.podman.yml build pdf-parser-service
podman-compose -f docker-compose.podman.yml up -d pdf-parser-service
```

探活：

```bash
curl http://localhost:8090/health
```

主 backend 在容器内使用：

```bash
PDF_PARSER_LOCAL_ENDPOINT=http://pdf-parser-service:8090
```

主 backend 直接在宿主机运行时使用：

```bash
PDF_PARSER_LOCAL_ENDPOINT=http://localhost:8090
```

## 3. 镜像配置

`backend/parser_service/Dockerfile` 只安装 MinerU：

```text
MINERU_PACKAGE_SPEC=mineru[pipeline]>=3.3,<4
```

可通过构建参数固定经过验证的 MinerU 版本：

```bash
MINERU_PACKAGE_SPEC='mineru[pipeline]==3.3.1' \
  podman-compose -f docker-compose.podman.yml build pdf-parser-service
```

升级 MinerU 后必须运行解析器专项测试和完整后端测试，并用固定试卷样本检查块顺序、
bbox、公式、表格、图片和 OCR 质量。

## 4. 运行参数

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `PARSER_SERVICE_HOST` | `0.0.0.0` | 服务监听地址 |
| `PARSER_SERVICE_PORT` | `8090` | 服务端口 |
| `MINERU_MODEL_SOURCE` | 自动 | 首次使用 ModelScope，已有本地配置时使用 local |
| `MINERU_TOOLS_CONFIG_JSON` | `/root/.cache/mineru/mineru.json` | MinerU 配置文件 |
| `MINERU_PDF_RENDER_THREADS` | `1` | PDF 渲染线程数 |
| `MINERU_PDF_RENDER_TIMEOUT` | `600` | PDF 渲染超时秒数 |
| `MINERU_PROCESSING_WINDOW_SIZE` | `1` | 页面处理窗口，越大峰值内存越高 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

`docker-compose.podman.yml` 将 `/root/.cache` 挂载到 `mineru_cache` 卷，保存模型和
MinerU 配置。

## 5. 远程部署

远程机器运行同一 parser-service 镜像，并通过 HTTPS 或私有网络暴露服务。管理端
系统设置中选择“远程”，填写 `remote_service_endpoint`。

远程服务至少满足：

- 主 backend 能访问服务地址
- 反向代理允许大 PDF 上传和长请求
- 代理超时不小于后端 `request_timeout_seconds`
- `/health` 可用于探活
- `/progress/{task_id}` 可选失败，但不能影响 `/parse`
- 不向公网匿名开放解析接口

## 6. 资源建议

MinerU 首次运行需要下载模型。CPU pipeline 可以运行，但试卷页数、图片数量和公式
密度会显著影响耗时与内存。

建议：

- 生产环境优先使用 Linux
- 至少预留 16GB 内存
- 默认保持 `MINERU_PROCESSING_WINDOW_SIZE=1`
- 通过任务队列限制并发解析数量
- 对超大 PDF 在入口限制文件大小并记录解析耗时

## 7. 故障排查

服务未就绪：

```bash
podman logs starmap-pdf-parser-service
curl http://localhost:8090/health
```

主 backend 无法连接：

1. 检查系统设置中的部署目标和服务地址
2. 检查容器网络内地址是否使用 `pdf-parser-service:8090`
3. 检查宿主机模式是否使用 `localhost:8090`
4. 检查反向代理上传大小和超时

内存过高：

1. 将 `processing_window_size` 调整为 `1`
2. 降低解析任务并发
3. 检查是否重复启动多个 parser-service
4. 根据日志确认是否卡在模型加载、PDF 渲染或页面推理阶段

## 8. 发布检查

1. 构建 MinerU 镜像
2. 启动服务并通过 `/health`
3. 对固定试卷样本执行 `/parse`
4. 检查页数、块数、资产数和图片回传
5. 在主 backend 触发语料解析并确认进度
6. 运行完整后端测试
