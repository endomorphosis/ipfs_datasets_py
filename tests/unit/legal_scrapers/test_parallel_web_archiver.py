from __future__ import annotations

import pytest

from ipfs_datasets_py.processors.legal_scrapers.parallel_web_archiver import (
    ArchiveResult,
    ParallelWebArchiver,
)
from ipfs_datasets_py.processors.legal_scrapers import parallel_web_archiver as archiver_module


@pytest.mark.anyio
async def test_archive_urls_parallel_gathers_each_url_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archiver_module, "HAVE_AIOHTTP", True)

    seen_urls: list[str] = []

    async def _fake_archive_single_url(self: ParallelWebArchiver, url: str) -> ArchiveResult:
        seen_urls.append(url)
        return ArchiveResult(
            url=url,
            success=True,
            content=f"content:{url}",
            source="test",
        )

    monkeypatch.setattr(ParallelWebArchiver, "_archive_single_url", _fake_archive_single_url)

    archiver = ParallelWebArchiver(max_concurrent=2)
    urls = [
        "https://example.com/one",
        "https://example.com/two",
        "https://example.com/three",
    ]

    results = await archiver.archive_urls_parallel(urls)

    assert seen_urls == urls
    assert [result.url for result in results] == urls
    assert [result.content for result in results] == [f"content:{url}" for url in urls]