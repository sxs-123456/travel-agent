"""全局配置：从 .env 加载，集中管理所有密钥与运行参数。

本项目仅支持真实模式：所有外部依赖（LLM / 高德 / Pexels）均需配置对应密钥，
不再保留任何 Mock / 演示数据。缺失密钥时，相关调用会抛出清晰的错误提示。
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    """应用配置。所有外部依赖的密钥均在 .env 中设置。"""

    def __init__(self) -> None:
        self.llm_api_key: str = os.getenv("LLM_API_KEY", "")
        self.llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.llm_model: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.llm_input_cost_per_1m_usd: float = float(
            os.getenv("LLM_INPUT_COST_PER_1M_USD", "0")
        )
        self.llm_output_cost_per_1m_usd: float = float(
            os.getenv("LLM_OUTPUT_COST_PER_1M_USD", "0")
        )
        self.amap_api_key: str = os.getenv("AMAP_API_KEY", "")
        self.use_amap_driving_route: bool = os.getenv(
            "USE_AMAP_DRIVING_ROUTE", "true"
        ).lower() in ("1", "true", "yes", "on")
        # Pexels 免费图库（封面图首选，选填）：留空则跳过、自动落到 Openverse 兜底，
        # 不影响「免 key 也能跑」。
        self.pexels_api_key: str = os.getenv("PEXELS_API_KEY", "")
        # 百度地图服务端 AK（打车估算，选填；缺失则市内交通用按天估算）。
        self.baidu_map_ak: str = os.getenv("BAIDU_MAP_AK", "")
        # 启用 12306 真实火车票票价（直连官方接口，免 key 免 npx）。
        # true 且请求填写出发城市时，交通费使用 12306 真实往返票价；否则按档位估算。
        self.use_rail_mcp: bool = os.getenv("USE_RAIL_MCP", "false").lower() in (
            "1", "true", "yes", "on",
        )
        # 偏好席别（二等座/一等座/商务座…），未命中时取最低价。
        self.rail_mcp_seat_class: str = os.getenv("RAIL_MCP_SEAT_CLASS", "二等座")

    @property
    def use_real_llm(self) -> bool:
        """是否已配置 LLM 密钥（真实模式的前置条件）。"""
        return bool(self.llm_api_key)

    @property
    def use_real_amap(self) -> bool:
        """是否已配置高德密钥。"""
        return bool(self.amap_api_key)


settings = Settings()
