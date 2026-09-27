# 智能旅行助手（Trip Planner Agent）

一个渐进式重构的生产级 Stateful Travel Agent。系统保留高德、12306、百度百科、Open-Meteo 等真实数据源，以强类型 `TravelState` 串联显式节点工作流；LLM 只负责意图抽取、候选 Source ID 选择和可选的语义偏好判断，所有可由数据源或确定性代码获得的事实均不交给模型生成。

## 特性

- **Stateful Agent Workflow**：`TravelState` 作为共享状态，显式执行 Discovery → Draft → Prepare → Enrich → Constraint → Replan/Complete。
- **独立 Tool/Node**：景点、酒店、天气、草稿、路线、餐厅、12306、预算、约束和图片各自封装，并通过统一 `ToolResult` 返回状态、错误、重试次数、fallback、latency 和 source IDs。
- **并行与韧性**：景点/酒店/天气并行发现，路线/餐厅/车次并行补全；按节点配置 Retry、Timeout、Fallback 和最大循环次数。
- **自然语言入口**：用户直接描述出发地、目的地和日期；大模型只负责抽取请求字段，缺少目的地或日期时返回补充提示，校验通过后复用原有规划工作流。
- **真实数据接入**：
  - 高德 POI / 天气（v3 REST）
  - **真实门票**：百度百科词条卡片 API（免费、免 key），如故宫「60元旺季/40元淡季」
  - **车次选择推荐**：12306 官方接口（直连免 key），候选车次列表 + 推荐班次 + 推荐理由
  - 市内交通：高德公交路线提供地铁/公交建议与票价；缺少票价时按乘车段数保守估算
  - 餐饮：只按每日景点位置检索高德真实餐厅 POI 与人均消费，不再由模型编造餐厅
  - 景点图片：优先使用 POI 返回的实景图；缺图时按“城市 + 地点”搜索 Pexels（可选 key）→ Openverse（兜底）
- **多天行程不重复**：按天数甄选不同景区 + 跨天同名/同景区后处理去重，保证每天去不同地方。
- **候选 ID 约束**：LLM 只选择高德 POI ID，名称、坐标和门票由后端恢复；未知 ID 不进入结果。
- **独立 Constraint Checker**：确定性检查 Source ID、重复景点、营业时间、路线距离、每日时间负载、预算一致性和用户硬约束；失败后只进行有限次数 Replan。
- **可选 MCP 边界**：通过 MCP v2 暴露真实 POI 和天气工具，并由 Client Adapter 转换为统一 `ToolResult`，核心链路仍使用低开销的本地节点。
- **路线优化**：使用最近邻算法排列景点，并发查询各段高德公交/地铁路线、耗时与票价。
- **成本可观测**：按一次规划聚合模型调用次数、输入/输出 token；配置模型单价后返回费用估算。
- **延迟优化**：门票、路线、餐厅和市内交通受控并发；酒店按真实候选确定性排序，减少一次 LLM 调用。
- **Pydantic 数据模型**：`Location → Attraction/Meal/Hotel → DayPlan → TripPlan`。
- **Vue3 前端**：一句话输入 → 独立结果页 → 公交/地铁攻略 → 逐日时间轴 → 预算明细 → 车次选择面板。
- **首页视觉**：浅色纸张质感与项目原创手绘地标背景，配合自然语言行程输入框。
- **分级故障处理**：核心规划依赖失败返回错误；图片、车次等辅助能力允许缺省，并通过说明标注。

## 技术栈

后端：Python + LangChain（ChatOpenAI 兼容）+ Pydantic + FastAPI + httpx + MCP Python SDK
前端：Vue3 + TypeScript + Vite + Ant Design Vue

## 目录结构

```
trip-planner-agent/
├── backend/
│   ├── agents/             # 四个专属 Agent + base
│   ├── tools/              # 高德 / Openverse / 12306 / 百度百科
│   ├── models/             # TripPlan / TravelState 共享强类型契约
│   ├── workflow/           # 显式状态机、Nodes、Constraint Checker
│   ├── mcp_tools/          # 可选 MCP Server / Client Adapter
│   ├── api/main.py         # FastAPI 路由 + 静态托管前端
│   ├── rail_client.py      # 12306 客户端门面
│   ├── planner.py          # TripPlannerAgent 编排器
│   ├── config.py           # .env 配置
│   ├── evaluation.py       # 端到端评测指标汇总
│   └── run.py              # uvicorn 启动入口
├── evals/                  # 固定评测数据集、运行器和真实结果
├── docs/                   # 架构图与 Benchmark Report
├── frontend/               # Vue3 前端
├── tests/                  # pytest
├── Dockerfile / docker-compose.yml
├── .github/workflows/ci.yml
└── requirements.txt / requirements-dev.txt
```

## 配置

`.env`（项目根）：
```ini
LLM_API_KEY=你的key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_INPUT_COST_PER_1M_USD=0   # 按模型官方单价填写，启用费用估算
LLM_OUTPUT_COST_PER_1M_USD=0
AMAP_API_KEY=你的高德Web服务key
PEXELS_API_KEY=                  # 选填，启用 Pexels 封面图（留空则只用 Openverse）
USE_RAIL_MCP=true                # 启用 12306 真实火车票
RAIL_MCP_SEAT_CLASS=二等座
WORKFLOW_MAX_LOOPS=2             # 包含首次规划，范围 1~5
TOOL_TIMEOUT_SECONDS=25
TOOL_MAX_ATTEMPTS=2
ENABLE_SEMANTIC_CONSTRAINT_CHECK=false
```

`frontend/.env` 仅在前后端分开部署时设置 `VITE_API_BASE`；同源部署无需配置。

**完全免费、免 key 的数据源**：门票（百度百科）、封面图（Openverse）、火车票（12306 直连）。Pexels 为可选增强（免费 key，200 次/时）。

## 运行

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m backend.run --port 8001
```

浏览器打开 `http://localhost:8001`（8000 被占用时换 8001）。例如输入“10月1日到10月7日从上海去北京，两个人想逛故宫和胡同”，按回车或点击按钮生成行程。Shift + 回车可换行。结果页地址为 `#/plan`，当前浏览器会话刷新后可继续查看；它不是可分享的永久链接。输入出发城市且启用 12306 时，结果中会展示车次选择推荐。

自然语言接口是 `POST /api/trip-plan/from-text`，请求体为 `{"query":"10月1日到10月7日从上海去北京"}`，响应包含解析后的 `request` 和原有 `plan`。无明确日期或目的地时返回 422；日期未写年份时按北京时间选择最近一次尚未过去的出发日期。该入口会比结构化接口多一次 LLM 解析调用，因此会增加少量模型耗时和费用。

也可以用容器启动（根目录需有 `.env`）：

```powershell
docker compose up --build
```

访问 `http://localhost:8000`。提交到 GitHub 后，Actions 会自动执行后端测试、前端构建和容器构建。

## 公网演示部署

可将 Vue 前端部署到 Cloudflare Pages、Vercel、Netlify 等静态托管平台，并把 FastAPI 部署到单独的 Python/Docker 服务。配置步骤、所需环境变量、CORS 和公开访问注意事项见 [`DEPLOY_DEMO.md`](DEPLOY_DEMO.md)。

## 测试

```powershell
pytest tests/ -q
```

## 固定评测集

先启动后端，再执行 12 个固定场景。日期按运行日自动顺延，结果包含成功率、质量通过率、
日期/天气覆盖率、P50/P95 延迟以及 token/费用汇总：

```powershell
python evals/run_evaluation.py --base-url http://127.0.0.1:8001
```

结果写入 `evals/results/latest.json`。该命令会真实调用已配置的 LLM 和外部接口，可能产生模型费用；
简历中的指标应引用实际生成的结果，不应使用测试桩数据。

### Stateful Agent 真实评测结果

2026-09-27 对 Railway 当前部署运行全部 12 个固定场景：Task Success、Grounded POI、Constraint Satisfaction 和 Tool Call Success 均为 `100%`，Duplicate 与 Hallucination 均为 `0%`，P50/P95 延迟为 `34.88s / 42.06s`，总 token 为 `54,224`。模型单价未配置，因此费用如实记为 unavailable。原始结果见 [`evals/results/latest.json`](evals/results/latest.json)，指标定义和复现命令见 [`docs/BENCHMARK.md`](docs/BENCHMARK.md)。

## 已知限制

- 高德天气多天预报上限 4 天。
- 门票：小众景点/园区内部点查不到时显示「门票以景区现场公告为准」，不臆造。
- 酒店：免费接口无真实房价，按「城市系数 × 档次/评分」参考估算并标注；如需官方报价需携程/同程/美团开放平台（商业 key）。
- 车次：实际以 12306 下单为准。
## 工程化与简历展示

架构说明与 Mermaid 工作流图见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。CI 在每次 push/PR 执行 Python 编译、完整 pytest、Vue TypeScript 构建和 Docker 镜像构建；Railway 绑定 `main` 分支后负责通过已验证提交持续部署。

简历描述建议只引用 `evals/results/latest.json` 中真实生成的数字：

> 基于 FastAPI、LangChain、Pydantic 与 Vue3 构建 Stateful Travel Agent，以强类型 TravelState 和显式 Node Workflow 编排真实数据工具；实现并行 Tool Execution、统一错误与 Trace、受限 Retry/Timeout/Fallback/Replan，并以 Source ID 恢复事实字段、确定性 Constraint Checker 和固定评测集约束幻觉与行程冲突。
