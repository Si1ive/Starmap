"""
GitHub Spider for downloading files (PDF, DOC, PPT) from GitHub repositories.

Uses GitHub REST API v3 to:
1. Search repositories by query
2. Browse repository file trees
3. Download matching files to local storage
"""

import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import scrapy

from starmap_scrapy.items import FileDownloadItem

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


class GitHubSpider(scrapy.Spider):
    """
    Spider for downloading files from GitHub repositories.

    Usage:
        scrapy crawl github \\
            -a repo_url=https://github.com/user/repo \\
            -a file_types=pdf,doc \\
            -a task_id=xxx

        # Or search GitHub:
        scrapy crawl github \\
            -a search_query=408考研 数据结构 \\
            -a file_types=pdf \\
            -a task_id=xxx
    """

    name = "github"

    def __init__(
        self,
        repo_url=None,
        search_query=None,
        file_types="pdf",
        max_depth=10,
        task_id=None,
        source="github",
        source_id=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.repo_url = repo_url
        self.search_query = search_query
        self.file_types = [ft.strip().lower() for ft in file_types.split(",") if ft.strip()]
        self.max_depth = int(max_depth)
        self.task_id = task_id
        self.source = source
        self.source_id = source_id

        # GitHub token from environment
        self.github_token = os.getenv("GITHUB_TOKEN", "")

        # Download storage base directory
        self.download_store = os.getenv("DOWNLOAD_STORE", str(Path(__file__).parent.parent.parent.parent / "downloads"))

        self._repos_scanned = 0
        self._files_found = 0
        self._files_downloaded = 0

    def _get_headers(self):
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            headers["Authorization"] = f"token {self.github_token}"
        return headers

    def start_requests(self):
        if self.repo_url:
            # Direct repo URL provided
            owner, repo = self._parse_repo_url(self.repo_url)
            if owner and repo:
                yield self._request_repo_info(owner, repo)
            else:
                logger.error(f"Invalid repo URL: {self.repo_url}")
        elif self.search_query:
            # Search GitHub for repos
            url = f"{GITHUB_API_BASE}/search/repositories?q={self.search_query}&sort=stars&order=desc&per_page=10"
            yield scrapy.Request(
                url=url,
                headers=self._get_headers(),
                callback=self.parse_search_results,
                errback=self.handle_error,
            )
        else:
            logger.error("Either repo_url or search_query must be provided")

    def _parse_repo_url(self, url: str):
        """Extract owner/repo from GitHub URL."""
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(path_parts) >= 2:
            return path_parts[0], path_parts[1]
        return None, None

    def _request_repo_info(self, owner: str, repo: str):
        """Request repo info to get default branch."""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        return scrapy.Request(
            url=url,
            headers=self._get_headers(),
            callback=self.parse_repo_info,
            errback=self.handle_error,
            meta={"owner": owner, "repo": repo},
        )

    def parse_search_results(self, response):
        """Parse GitHub search results and crawl each repo."""
        data = response.json()
        items = data.get("items", [])
        logger.info(f"Found {len(items)} repositories for query: {self.search_query}")

        for item in items:
            owner = item["owner"]["login"]
            repo = item["name"]
            default_branch = item.get("default_branch", "main")
            yield self._request_repo_tree(owner, repo, default_branch)

    def parse_repo_info(self, response):
        """Parse repo info and request file tree."""
        data = response.json()
        owner = response.meta["owner"]
        repo = response.meta["repo"]
        default_branch = data.get("default_branch", "main")
        yield self._request_repo_tree(owner, repo, default_branch)

    def _request_repo_tree(self, owner: str, repo: str, branch: str):
        """Request recursive file tree for a repo."""
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        return scrapy.Request(
            url=url,
            headers=self._get_headers(),
            callback=self.parse_repo_tree,
            errback=self.handle_error,
            meta={"owner": owner, "repo": repo, "branch": branch},
        )

    def parse_repo_tree(self, response):
        """Parse file tree and yield download requests for matching files."""
        data = response.json()
        owner = response.meta["owner"]
        repo = response.meta["repo"]
        branch = response.meta["branch"]
        tree = data.get("tree", [])

        self._repos_scanned += 1
        repo_name = f"{owner}/{repo}"
        repo_url = f"https://github.com/{owner}/{repo}"

        logger.info(f"Scanning repo: {repo_name}, {len(tree)} entries")

        for entry in tree:
            # Skip directories and submodules
            if entry.get("type") != "blob":
                continue

            file_path = entry.get("path", "")
            file_name = Path(file_path).name
            file_ext = Path(file_name).suffix.lower().lstrip(".")

            # Check if file type matches
            if file_ext not in self.file_types:
                continue

            # Check depth
            depth = len(file_path.split("/")) - 1
            if depth > self.max_depth:
                continue

            self._files_found += 1
            file_size = entry.get("size", 0)

            # Build download URL
            download_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}"

            # Build local path
            safe_repo = repo_name.replace("/", "_")
            local_dir = os.path.join(self.download_store, self.task_id or "manual", safe_repo)
            local_path = os.path.join(local_dir, file_path)

            yield scrapy.Request(
                url=download_url,
                headers=self._get_headers(),
                callback=self.download_file,
                errback=self.handle_download_error,
                meta={
                    "repo_name": repo_name,
                    "repo_url": repo_url,
                    "file_path": file_path,
                    "file_name": file_name,
                    "file_type": file_ext,
                    "file_size": file_size,
                    "download_url": download_url,
                    "local_path": local_path,
                    "local_dir": local_dir,
                    "dont_redirect": True,
                },
            )

    def download_file(self, response):
        """Save downloaded file and yield FileDownloadItem."""
        local_path = response.meta["local_path"]
        local_dir = response.meta["local_dir"]

        # Check HTTP status
        if response.status != 200:
            error_msg = f"HTTP {response.status}"
            logger.warning(f"HTTP error for {response.meta['file_name']}: {error_msg}")
            yield FileDownloadItem(
                repo_name=response.meta["repo_name"],
                repo_url=response.meta["repo_url"],
                file_path=response.meta["file_path"],
                file_name=response.meta["file_name"],
                file_type=response.meta["file_type"],
                file_size=response.meta["file_size"],
                download_url=response.meta["download_url"],
                local_path=None,
                task_id=self.task_id,
                status="failed",
                metadata={"error": error_msg},
            )
            return

        # Validate response looks like a file (not an HTML error page)
        content_type = response.headers.get("Content-Type", b"").decode("utf-8", errors="replace")
        if "text/html" in content_type and response.meta["file_type"] not in ("html", "htm"):
            error_msg = f"Got HTML response instead of file (Content-Type: {content_type})"
            logger.warning(f"Content type mismatch for {response.meta['file_name']}: {error_msg}")
            yield FileDownloadItem(
                repo_name=response.meta["repo_name"],
                repo_url=response.meta["repo_url"],
                file_path=response.meta["file_path"],
                file_name=response.meta["file_name"],
                file_type=response.meta["file_type"],
                file_size=response.meta["file_size"],
                download_url=response.meta["download_url"],
                local_path=None,
                task_id=self.task_id,
                status="failed",
                metadata={"error": error_msg},
            )
            return

        try:
            # Create directory
            os.makedirs(local_dir, exist_ok=True)

            # Write file
            with open(local_path, "wb") as f:
                f.write(response.body)

            actual_size = len(response.body)
            self._files_downloaded += 1

            logger.info(f"Downloaded: {response.meta['file_name']} ({actual_size} bytes)")

            yield FileDownloadItem(
                repo_name=response.meta["repo_name"],
                repo_url=response.meta["repo_url"],
                file_path=response.meta["file_path"],
                file_name=response.meta["file_name"],
                file_type=response.meta["file_type"],
                file_size=actual_size,
                download_url=response.meta["download_url"],
                local_path=local_path,
                task_id=self.task_id,
                status="downloaded",
            )

        except Exception as e:
            logger.error(f"Failed to save file {response.meta['file_name']}: {e}")
            yield FileDownloadItem(
                repo_name=response.meta["repo_name"],
                repo_url=response.meta["repo_url"],
                file_path=response.meta["file_path"],
                file_name=response.meta["file_name"],
                file_type=response.meta["file_type"],
                file_size=response.meta["file_size"],
                download_url=response.meta["download_url"],
                local_path=None,
                task_id=self.task_id,
                status="failed",
                metadata={"error": str(e)},
            )

    def handle_error(self, failure):
        """Handle request errors."""
        logger.error(f"Request failed: {failure.request.url} - {failure.value}")

    def handle_download_error(self, failure):
        """Handle file download errors."""
        meta = failure.request.meta
        logger.error(f"Download failed: {meta.get('file_name')} - {failure.value}")
        yield FileDownloadItem(
            repo_name=meta.get("repo_name", ""),
            repo_url=meta.get("repo_url", ""),
            file_path=meta.get("file_path", ""),
            file_name=meta.get("file_name", ""),
            file_type=meta.get("file_type", ""),
            file_size=meta.get("file_size", 0),
            download_url=meta.get("download_url", ""),
            local_path=None,
            task_id=self.task_id,
            status="failed",
            metadata={"error": str(failure.value)},
        )

    def closed(self, reason):
        """Log summary when spider closes."""
        logger.info(
            f"GitHub spider closed: reason={reason}, "
            f"repos_scanned={self._repos_scanned}, "
            f"files_found={self._files_found}, "
            f"files_downloaded={self._files_downloaded}"
        )
