# 智能旅行助手（Trip Planner Agent）

基于《Hello-Agents》第十三章「智能旅行助手」架构实现的 Agent 项目。
**仅支持真实模式**：景点、天气等数据通过外部接口查询，行程由 LLM 生成；
酒店和部分交通费用为参考估算，餐饮建议由模型生成。
缺失密钥会抛出清晰错误，而非回退到伪造结果。

## 特性

- **多智能体协作**：`AttractionSearchAgent`（景点）/ `WeatherQueryAgent`（天气）/
  `HotelAgent`（酒店）/ `PlannerAgent`（整合行程+预算），由 `TripPlannerAgent` 编排。
- **自然语言入口**：用户直接描述出发地、目的地和日期；大模型只负责抽取请求字段，缺少目的地或日期时返回补充提示，校验通过后复用原有规划工作流。
- **真实数据接入**：
  - 高德 POI / 天气（v3 REST）
  - **真实门票**：百度百科词条卡片 API（免费、免 key），如故宫「60元旺季/40元淡季」
  - **车次选择推荐**：12306 官方接口（直连免 key），候选车次列表 + 推荐班次 + 推荐理由
  - 市内打车：优先用百度、否则用高德路线查询距离/时长后按参考费率估价；路线不可用时不虚构金额、不计入预算；不调用网约车下单服务
  - 餐饮：按每日景点位置检索高德真实餐厅 POI 与人均消费
  - 景点图片：优先使用 POI 返回的实景图；缺图时按“城市 + 地点”搜索 Pexels（可选 key）→ Openverse（兜底）
- **多天行程不重复**：按天数甄选不同景区 + 跨天同名/同景区后处理去重，保证每天去不同地方。
- **候选 ID 约束**：LLM 只选择高德 POI ID，名称、坐标和门票由后端恢复；未知 ID 不进入结果。
- **受控修复**：草稿出现天数错误、空行程、重复或未知 ID 时，最多自动修复一次。
- **路线优化**：最近邻排序后调用高德驾车路线，返回真实道路距离与预计时长；失败时自动回退直线距离。
- **成本可观测**：按一次规划聚合模型调用次数、输入/输出 token；配置模型单价后返回费用估算。
- **延迟优化**：门票、路线、餐厅和市内交通受控并发；酒店按真实候选确定性排序，减少一次 LLM 调用。
- **Pydantic 数据模型**：`Location → Attraction/Meal/Hotel → DayPlan → TripPlan`。
- **Vue3 前端**：一句话输入 → 独立结果页 → 高德 JS API 地图（无 key 降级坐标列表）→ 逐日时间轴 → 预算明细 → 车次选择面板。
- **首页视觉**：浅色纸张质感与项目原创手绘地标背景，配合自然语言行程输入框。
- **分级故障处理**：核心规划依赖失败返回错误；图片、车次等辅助能力允许缺省，并通过说明标注。

## 技术栈

后端：LangChain（ChatOpenAI 兼容）+ Pydantic + FastAPI + httpx
前端：Vue3 + TypeScript + Vite + Ant Design Vue + 高德 JS API

## 目录结构

```
trip-planner-agent/
├── backend/
│   ├── agents/             # 四个专属 Agent + base
│   ├── tools/              # 高德 / Openverse / 12306 / 百度打车 / 百度百科
│   ├── models/             # Pydantic 数据模型（trip）
│   ├── api/main.py         # FastAPI 路由 + 静态托管前端
│   ├── rail_client.py      # 12306 客户端门面
│   ├── planner.py          # TripPlannerAgent 编排器
│   ├── config.py           # .env 配置
│   ├── evaluation.py       # 端到端评测指标汇总
│   └── run.py              # uvicorn 启动入口
├── evals/                  # 固定评测案例 + 评测运行器
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
USE_AMAP_DRIVING_ROUTE=true   # 高德真实驾车距离/时长
PEXELS_API_KEY=                  # 选填，启用 Pexels 封面图（留空则只用 Openverse）
USE_RAIL_MCP=true                # 启用 12306 真实火车票
RAIL_MCP_SEAT_CLASS=二等座
BAIDU_MAP_AK=                    # 选填，优先使用百度路线；缺失时使用 AMAP_API_KEY 查询路线
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

### 真实评测结果（2026-09-24，优化后）

以下指标来自结构化接口 `/api/trip-plan`，不包含新版首页额外的自然语言解析耗时和费用。

在 DeepSeek、高德、Open-Meteo、百度地图、12306 与图片服务的真实调用链上运行 12 个固定场景：

- API 成功率：`12/12 = 100%`
- 质量通过率：`12/12 = 100%`
- 日期覆盖率：`100%`；天气覆盖率：`91.67%`
- 端到端延迟：P50 `19.25s`，P95 `22.77s`
- 模型用量：24 次调用，输入 27,165 tokens，输出 4,685 tokens，共 31,850 tokens
- 相比优化前：P50 降低约 `46.5%`，P95 降低约 `55.2%`，总 token 降低约 `35.2%`

曾出现的洛阳四日游空日问题已通过“通用 POI 补查 + 两级确定性补位”修复；完整 12 场景复测
质量通过率为 `100%`。正式结果保存在 `evals/results/latest.json`，定向回归结果保存在
`evals/results/regression-luoyang.json`。

## 已知限制

- 高德天气多天预报上限 4 天。
- 门票：小众景点/园区内部点查不到时显示「门票以景区现场公告为准」，不臆造。
- 酒店：免费接口无真实房价，按「城市系数 × 档次/评分」参考估算并标注；如需官方报价需携程/同程/美团开放平台（商业 key）。
- 车次：实际以 12306 下单为准。
## 工程化与简历展示

项目采用固定工作流编排：景点、天气、酒店并行采集，再由规划 Agent 整合，最后执行确定性后处理。它不是自主选择任意工具的通用 Agent；面试时可以重点解释并行依赖关系、结构化输出恢复和数据可信边界。

- 深模块接口：规划模型只输出每天的候选 POI ID、餐饮建议和备注；城市、日期、酒店、坐标、门票、预算及路线由后端确定性恢复。
- 景点事实约束：景点通过高德 POI ID 绑定，未知或重复 ID 被拒绝，不接受规划模型自行改写价格与坐标。该约束保证与采集结果一致，不等于上游资料已被独立核实。
- 输入校验：有效日历日期、统一日期格式、非空目的地，非法请求在调用外部服务之前返回 422。
- 执行追踪：每次规划记录统一 trace_id，各阶段记录耗时和成功/失败状态；HTTP 响应附 X-Request-ID，与该请求的规划 trace_id 一致。不记录完整用户请求。
- 质量诊断与修复：草稿结构问题最多触发一次定向重做；最终结果仍由 `backend/quality.py` 独立检查并记录覆盖率与预算一致性，不会无限循环。
- 路线计算：使用 Haversine 最近邻算法排序景点，再逐段调用高德驾车路线获取道路距离与预计时长；接口不可用时明确回退直线距离。
- 成本统计：LangChain 回调按一次请求聚合 LLM 调用和 token；在 `.env` 配置模型单价后同时给出美元费用估算。
- 固定评测：12 个不同城市、天数、预算和人数的端到端案例，输出成功率、质量通过率及 P50/P95 延迟。
- 回归测试：HTTP/LLM 使用桩替换，验证字段映射、校验和业务路径，不产生模型费用。

简历描述示例（不要填写未实测的性能数字）：

> 基于 FastAPI、LangChain 与 Vue3 实现旅行规划 Agent 工作流，并行整合景点、酒店、天气数据；以 POI ID 约束模型选择并由后端恢复事实字段，实现一次受控修复、路线距离排序、阶段追踪和固定评测集，覆盖结构化输出异常、推荐一致性与外部服务降级。

后续可继续深化：补充餐厅营业时间；在积累真实评测失败案例后，把修复提示从通用问题列表细化为分类策略；部署到云平台后补充公开演示地址。
