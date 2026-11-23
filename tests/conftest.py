from datetime import datetime

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """每个测试都用独立的临时数据目录，绝不碰真实数据。"""
    monkeypatch.setenv("AWY_DATA_DIR", str(tmp_path / "data"))
    from awy import i18n
    monkeypatch.setattr(i18n, "system_lang", lambda: "zh")   # 测试一律用中文，不受这台电脑的系统语言影响
    i18n.set_lang("zh")
    return tmp_path / "data"


class FakeEmbedder:
    """测试用的假向量模型：按字统计，意思相近 ≈ 用字相近。"""

    name = "fake"

    def encode(self, texts):
        out = []
        for t in texts:
            v = np.zeros(256, dtype=np.float32)
            for ch in t:
                v[ord(ch) % 256] += 1
            n = np.linalg.norm(v)
            out.append(v / n if n else v)
        return np.vstack(out)


@pytest.fixture
def store(tmp_path):
    from awy.memory.store import MemoryStore
    s = MemoryStore(tmp_path / "m.db", embedder=FakeEmbedder())
    yield s
    s.close()


def at(s: str) -> str:
    return datetime.fromisoformat(s).astimezone().isoformat(timespec="seconds")
