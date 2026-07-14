"""爬虫下载文件的本地存储约定。"""

import os
from pathlib import Path

DOWNLOAD_STORE = Path(
    os.getenv(
        "DOWNLOAD_STORE",
        str(Path(__file__).resolve().parents[3] / "downloads"),
    )
).resolve()


def resolve_download_path(raw_path: str) -> Path:
    """解析下载文件路径，并确保结果位于下载根目录内。"""
    local_path = Path(raw_path).resolve()
    if local_path != DOWNLOAD_STORE and DOWNLOAD_STORE not in local_path.parents:
        raise ValueError("文件路径不在下载目录内")
    return local_path
