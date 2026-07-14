"""Shared contracts for document parser implementations and consumers."""

from dataclasses import dataclass
from typing import List, Optional, Protocol


class ParserUnavailableError(RuntimeError):
    """Raised when a parser dependency or parser service is unavailable."""

    def __init__(self, parser_name: str, detail: str):
        self.parser_name = parser_name
        self.detail = detail
        super().__init__(detail)


@dataclass
class ParsedPage:
    page_no: int
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class ParsedBlock:
    page_no: int
    block_type: str
    order_no: int
    content_text: Optional[str] = None
    content_md: Optional[str] = None
    bbox: Optional[dict] = None
    html_table: Optional[str] = None
    latex: Optional[str] = None


@dataclass
class ParsedAsset:
    page_no: int
    asset_type: str = "figure"
    caption_text: Optional[str] = None
    bbox: Optional[dict] = None
    file_path: Optional[str] = None
    # Parser service and backend may not share a filesystem, so temporary
    # parser output is transferred inline and persisted by the backend.
    image_base64: Optional[str] = None
    image_ext: Optional[str] = None


@dataclass
class ParsedDocumentResult:
    parser_name: str
    parser_version: str
    pages: List[ParsedPage]
    blocks: List[ParsedBlock]
    assets: List[ParsedAsset]
    document_markdown: str = ""
    confidence: Optional[float] = None
    metadata: Optional[dict] = None
    raw_output: Optional[dict] = None

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def asset_count(self) -> int:
        return len(self.assets)


class DocumentParser(Protocol):
    name: str
    version: str

    def parse(
        self,
        file_path: str,
        task_id: Optional[str] = None,
    ) -> ParsedDocumentResult:
        ...


@dataclass
class PdfParserRuntimeConfig:
    active_parser: str
    deployment_target: str
    local_service_endpoint: str
    remote_service_endpoint: str
    request_timeout_seconds: int
    processing_window_size: Optional[int] = None
