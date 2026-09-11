import sys
from pathlib import Path

import pytest

# 将项目根目录（trip-planner-agent）加入 sys.path，使测试可直接 import backend 包。
_ROOT = Path(__file__).resolve().parent.parent
while _ROOT.name != "trip-planner-agent" and _ROOT.parent != _ROOT:
    _ROOT = _ROOT.parent
sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _reset_caches():
    # 图片与门票检索带进程内缓存，测试间重置以避免相互污染。
    import backend.tools.images as _images
    import backend.tools.ticket as _ticket

    _images._cache.clear()
    _ticket._cache.clear()
    yield
    _images._cache.clear()
    _ticket._cache.clear()
