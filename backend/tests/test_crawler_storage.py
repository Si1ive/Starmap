"""爬虫下载目录路径约束测试。"""

from pathlib import Path

import pytest

from app.modules.crawler import storage


def test_resolve_download_path_accepts_file_under_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    download_store = tmp_path / "downloads"
    target = download_store / "task-1" / "paper.pdf"
    monkeypatch.setattr(storage, "DOWNLOAD_STORE", download_store.resolve())

    assert storage.resolve_download_path(str(target)) == target.resolve()


def test_resolve_download_path_rejects_similar_prefix_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    download_store = tmp_path / "downloads"
    sibling = tmp_path / "downloads-private" / "secret.pdf"
    monkeypatch.setattr(storage, "DOWNLOAD_STORE", download_store.resolve())

    with pytest.raises(ValueError, match="不在下载目录内"):
        storage.resolve_download_path(str(sibling))
