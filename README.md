# 智能旅行助手（Trip Planner Agent）

基于《Hello-Agents》第十三章「智能旅行助手」架构实现的 Agent 项目。
**仅支持真实模式**：所有外部数据（景点 / 天气 / 酒店 / 行程 / 封面图）均来自真实接口；
缺失密钥会抛出清晰错误，而非回退到伪造结果。

## 特性

- **多智能体协作**：`AttractionSearchAgent`（景点）/ `WeatherQueryAgent`（天气）/
  `HotelAgent`（酒店）/ `PlannerAgent`（整合行程+预算），由 `TripPlannerAgent` 编排。
- **真实数据接入**：
  - 高德 POI / 天气（v3 REST）
  - **真实门票**：百度百科词条卡片 API（免费、免 key），如故宫「60元旺季/40元淡季」
  - **车次选择推荐**：12306 官方接口（直连免 key），候选车次列表 + 推荐班次 + 推荐理由
  - 打车：百度地图驾车路线规划
  - 封面图：Pexels 免费图库（可选 key，首选）→ Openverse 开放图库（免 key，兜底）→ 无图
- **多天行程不重复**：按天数甄选不同景区 + 跨天同名/同景区后处理去重，保证每天去不同地方。
- **RAG 知识库问答**：本地向量检索（sentence-transformers + 轻量 numpy 向量库，免 key 免部署），
  文档切块 → 向量化 → 检索 → 生成带引用来源的回答。
- **Pydantic 数据模型**：`Location → Attraction/Meal/Hotel → DayPlan → TripPlan`。
- **Vue3 前端**：表单 → 真实行程 → 高德 JS API 地图（无 key 降级坐标列表）→ 逐日时间轴 → 预算明细 → 车次选择面板。
- **故障即报错**：任何外部调用失败都会抛出清晰异常，不静默降级。

## 技术栈

后端：LangChain（ChatOpenAI 兼容）+ Pydantic + FastAPI + httpx + sentence-transformers + numpy
前端：Vue3 + TypeScript + Vite + Ant Design Vue + 高德 JS API

## 目录结构

```
trip-planner-agent/
├── backend/
│   ├── agents/             # 四个专属 Agent + base
│   ├── tools/              # 高德 / Openverse / 12306 / 百度打车 / 百度百科
│   ├── rag/                # RAG：embedding / 向量库 / 切块 / 入库 / 问答
│   │   └── data/           # 示例知识库（旅行攻略 markdown）
│   ├── models/             # Pydantic 数据模型（trip / rag）
│   ├── api/main.py         # FastAPI 路由 + 静态托管前端
│   ├── rail_client.py      # 12306 客户端门面
│   ├── planner.py          # TripPlannerAgent 编排器
│   ├── config.py           # .env 配置
│   └── run.py              # uvicorn 启动入口
├── frontend/               # Vue3 前端
├── tests/                  # pytest
└── requirements.txt
```

## 配置

`.env`（项目根）：
```ini
LLM_API_KEY=你的key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
AMAP_API_KEY=你的高德Web服务key
PEXELS_API_KEY=                  # 选填，启用 Pexels 封面图（留空则只用 Openverse）
USE_RAIL_MCP=true                # 启用 12306 真实火车票
RAIL_MCP_SEAT_CLASS=二等座
BAIDU_MAP_AK=                    # 选填，启用百度打车真实距离/时长估算
```

`frontend/.env`：
```ini
VITE_AMAP_KEY=                   # 选填，启用高德 JS API 可视化地图
VITE_AMAP_SECURITY_CODE=
```

**完全免费、免 key 的数据源**：门票（百度百科）、封面图（Openverse）、火车票（12306 直连）。Pexels 为可选增强（免费 key，200 次/时）。

## 运行

```powershell
& "D:\develop\Travel Assistant\.venv\Scripts\python.exe" -m backend.run --port 8001
```

浏览器打开 `http://localhost:8001`（8000 被占用时换 8001）。表单填"出发城市"可看到 12306
车次选择推荐面板（去程+返程 + 候选车次表格 + 推荐班次）。

## RAG 知识库问答（可选模块）

本地向量检索问答，**免 key、免部署**，覆盖 Embedding / 向量库 / 切块 / 检索 / 生成全链路。

1. 安装依赖（不装不影响行程规划主流程）：
   ```powershell
   # 国内加速（可选）
   $env:HF_ENDPOINT = "https://hf-mirror.com"
   pip install -r requirements-rag.txt
   ```

2. 入库示例知识库（`backend/rag/data/*.md`）：
   ```powershell
   python -m backend.rag.ingest
   ```

3. 启动服务后调用问答接口：
   ```powershell
   curl -X POST http://localhost:8001/api/rag/query ^
     -H "Content-Type: application/json" ^
     -d "{\"question\": \"故宫门票多少钱？\"}"
   ```
   返回：`{"answer": "...", "sources": [{"source": "北京旅行攻略.md", "snippet": "...", "score": 0.9}]}`

**实现要点**：文档切块（句子感知 + 重叠）→ `BAAI/bge-small-zh-v1.5` 本地向量化 → 轻量
numpy 向量库余弦检索 top-k（接口与 Chroma 对齐，可无缝替换）→ 组装带引用 prompt → LLM
生成回答并标注来源。向量库数据落盘 `.vectordb/`（已加入 .gitignore）。

## 测试

```powershell
pytest tests/ -q
```

## 已知限制

- 高德天气多天预报上限 4 天。
- 门票：小众景点/园区内部点查不到时显示「门票以景区现场公告为准」，不臆造。
- 酒店：免费接口无真实房价，按「城市系数 × 档次/评分」参考估算并标注；如需官方报价需携程/同程/美团开放平台（商业 key）。
- 车次：实际以 12306 下单为准。