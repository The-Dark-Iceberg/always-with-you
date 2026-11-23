"""本地向量模型：BAAI/bge-m3（官方 ONNX 版本，MIT 许可，约 2.27GB）。

用途：把一句话变成 1024 个数字，让「跑步」也能搜到「晨练」。只用 CPU 就够。
- 用 ONNX Runtime 运行，不依赖 PyTorch（PyTorch 有好几 GB）。
- 第一次使用前需要下载（设置页里点「下载模型」），下载后逐个文件做 SHA-256 校验，
  校验不通过直接删除，防止下到被篡改的文件。
- 模型平时不常驻：用的时候加载，闲置一段时间后释放内存。
- 没有模型时记忆库照样能用，只是退回到「关键词搜索」。
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger(__name__)

MODEL_NAME = "bge-m3"
REVISION = "5617a9f61b028005a4858fdac845db406aefb181"  # 固定版本，避免上游悄悄变化
BASE_URL = f"https://huggingface.co/BAAI/bge-m3/resolve/{REVISION}/"
FILES = {
    # 本地文件名: (远端路径, 字节数, sha256)
    "model.onnx": ("onnx/model.onnx", 724923,
                   "f84251230831afb359ab26d9fd37d5936d4d9bb5d1d5410e66442f630f24435b"),
    "model.onnx_data": ("onnx/model.onnx_data", 2266820608,
                        "1eebfb28493f67bba03ce0ef64bfdc7fc5a3bd9d7493f818bb1d78cd798416b4"),
    "tokenizer.json": ("onnx/tokenizer.json", 17082821,
                       "6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790"),
}
MAX_TOKENS = 512
IDLE_UNLOAD_SECONDS = 120


def model_dir(root: Path) -> Path:
    return root / MODEL_NAME


def is_installed(root: Path) -> bool:
    d = model_dir(root)
    return all((d / n).exists() and (d / n).stat().st_size == size for n, (_, size, _) in FILES.items())


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(root: Path, progress: Callable[[str, int, int], None] | None = None,
             base_url: str = BASE_URL) -> None:
    """下载并校验模型。支持断点续传。progress(文件名, 已下载字节, 总字节)。"""
    import httpx

    d = model_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    for name, (remote, size, sha) in FILES.items():
        dest = d / name
        if dest.exists() and dest.stat().st_size == size and _sha256(dest) == sha:
            continue
        part = d / (name + ".part")
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        with httpx.stream("GET", base_url + remote, headers=headers, follow_redirects=True,
                          timeout=httpx.Timeout(60.0, read=300.0)) as r:
            if r.status_code == 200 and have:
                have = 0  # 服务器不支持续传，从头来
                part.unlink(missing_ok=True)
            r.raise_for_status()
            with part.open("ab") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    have += len(chunk)
                    if progress:
                        progress(name, have, size)
        if part.stat().st_size != size or _sha256(part) != sha:
            part.unlink(missing_ok=True)
            raise ValueError(f"{name} 校验失败，已删除，请重试")
        part.replace(dest)


class Bge3Embedder:
    """encode(list[str]) -> (n, 1024) 的单位向量。"""

    name = MODEL_NAME

    def __init__(self, root: Path) -> None:
        self.dir = model_dir(root)
        self._lock = threading.Lock()
        self._session = None
        self._tok = None
        self._last_used = 0.0
        self._timer: threading.Timer | None = None

    def _load(self) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(str(self.dir / "model.onnx"), sess_options=opts,
                                             providers=["CPUExecutionProvider"])
        self._tok = Tokenizer.from_file(str(self.dir / "tokenizer.json"))
        self._tok.enable_truncation(MAX_TOKENS)
        self._tok.enable_padding()
        log.info("向量模型已加载")

    def _schedule_unload(self) -> None:
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(IDLE_UNLOAD_SECONDS, self._unload_if_idle)
        self._timer.daemon = True
        self._timer.start()

    def _unload_if_idle(self) -> None:
        with self._lock:
            if self._session is not None and time.time() - self._last_used >= IDLE_UNLOAD_SECONDS - 1:
                self._session = None
                self._tok = None
                log.info("向量模型闲置，已释放内存")

    def encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            if self._session is None:
                self._load()
            encs = self._tok.encode_batch(list(texts))
            ids = np.array([e.ids for e in encs], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            names = {i.name for i in self._session.get_inputs()}
            feeds = {k: v for k, v in feeds.items() if k in names}
            # 官方导出有两个输出：token_embeddings (n,L,1024) 和 sentence_embedding (n,1024)（2026-11-20 实测）。
            # 优先用 sentence_embedding；万一换了导出格式，退回取 token_embeddings 的 [CLS]（BGE-M3 dense 的定义）。
            out_names = [o.name for o in self._session.get_outputs()]
            if "sentence_embedding" in out_names:
                vec = np.asarray(self._session.run(["sentence_embedding"], feeds)[0], dtype=np.float32)
            else:
                arr = np.asarray(self._session.run(None, feeds)[0], dtype=np.float32)
                vec = arr[:, 0, :] if arr.ndim == 3 else arr
            vec = vec / np.maximum(np.linalg.norm(vec, axis=1, keepdims=True), 1e-12)
            self._last_used = time.time()
        self._schedule_unload()
        return vec
