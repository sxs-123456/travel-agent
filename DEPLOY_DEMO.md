# 公网演示部署（静态前端 + 独立 API）

本项目可以用 GitHub 作为代码仓库，把 Vue 前端发布到 Cloudflare Pages、Vercel、Netlify 等静态托管平台。FastAPI 需要一个支持 Python 长驻进程或 Docker 的后端托管服务；静态托管平台本身不会运行本项目的 Python Agent。

部署拓扑：

```text
浏览器 → 静态托管（Vue） → HTTPS 请求 → FastAPI 后端 → 模型 / 地图等外部 API
```

## 1. 发布后端 API

在支持 Docker 的托管平台中连接 GitHub 仓库，创建 Web Service：

- Dockerfile：仓库根目录的 `Dockerfile`
- 部署分支：通常选择 `main`
- 健康检查路径：`/health`（平台支持时设置）
- 监听地址：容器会使用 `HOST=0.0.0.0`；端口使用平台注入的 `PORT`，没有注入时为 `8000`

在后端服务的环境变量设置中填写：

```ini
LLM_API_KEY=你的模型服务密钥
LLM_BASE_URL=https://你的模型服务兼容地址
LLM_MODEL=你的模型名称
AMAP_API_KEY=你的高德 Web 服务密钥
CORS_ORIGINS=https://你的前端域名
```

`CORS_ORIGINS` 填部署完成后前端的完整来源，例如 `https://trip-demo.pages.dev`，不要加路径或末尾斜杠。多个来源用英文逗号分隔。`PEXELS_API_KEY`、`BAIDU_MAP_AK` 等可选功能密钥按需设置。

后端部署完成后记录其公开 HTTPS 地址，例如 `https://trip-api.example-host.com`，并先打开 `https://trip-api.example-host.com/health` 确认服务正常。

## 2. 发布前端

在 Cloudflare Pages、Vercel、Netlify 或同类静态托管平台中连接同一个 GitHub 仓库，并设置：

- 项目根目录：`frontend`
- 安装命令：`npm ci`
- 构建命令：`npm run build`
- 输出目录：`dist`

添加前端构建环境变量：

```ini
VITE_API_BASE=https://你的后端服务域名
VITE_AMAP_KEY=可选的高德 JS API key
VITE_AMAP_SECURITY_CODE=可选的高德 JS API 安全码
```

`VITE_API_BASE` 填后端 HTTPS 地址，不要带 `/api` 路径或末尾斜杠。修改变量后需要重新构建/部署前端。高德 JS API key 会进入浏览器可下载的静态文件；若启用它，请在高德控制台限制允许的站点域名。**不要把 `LLM_API_KEY`、高德 Web 服务密钥或其他后端密钥设置为 `VITE_*` 变量。**

## 3. 配置 CORS 并验证

拿到静态托管域名后，回到后端环境变量，将 `CORS_ORIGINS` 设置为该域名，然后重新部署后端。访问前端公开地址提交一次短行程；同时确认后端 `/health` 返回成功。若浏览器控制台显示 CORS 错误，检查来源域名是否完全匹配（包括 `https`），并确认两端都已重新部署。

也可以先本地模拟分离部署：复制 `frontend/.env.example` 为 `frontend/.env.local`，填入后端地址，再运行 `cd frontend; npm ci; npm run build`。本地文件不会被 Git 跟踪。

## 费用与公开访问

静态前端通常可从托管平台的个人免费额度开始，但各平台额度和休眠策略会变化，部署时应以平台当前说明为准。后端服务也要单独选择可用方案；免费后端可能休眠或有资源限制。每次规划会调用模型和外部数据接口，模型 API 可能产生费用。正式公开演示前，应在后端托管平台为服务增加访问控制或用量限制，并检查模型服务的余额/额度；不要把后端密钥放进 GitHub 仓库或前端构建变量。
