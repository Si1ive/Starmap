"""Request schemas for corpus file and parse operations."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    root_path: str = Field(..., description="扫描根目录")
    file_types: Optional[List[str]] = Field(
        default=None,
        description="文件类型列表，如 pdf/docx/pptx",
    )
    batch_label: Optional[str] = Field(default=None, description="批次标签")


class RegisterFileRequest(BaseModel):
    file_path: str = Field(..., description="文件绝对路径")
    batch_label: Optional[str] = Field(default=None, description="批次标签")


class RegisterByDownloadRequest(BaseModel):
    downloaded_file_id: str = Field(..., description="已下载文件ID")
    batch_label: Optional[str] = Field(default=None, description="批次标签")


class ParseCorpusFileRequest(BaseModel):
    parser_name: Optional[Literal["docling", "mineru"]] = Field(
        default=None,
        description=(
            "仅用于开发期临时覆盖；正式运行应通过系统设置"
            "切换单活解析器"
        ),
    )
    parse_mode: Literal["primary", "fallback", "retry", "manual_fix"] = Field(
        default="primary",
        description=(
            "解析执行标记，用于区分主解析、重试、人工修复等运行语义"
        ),
    )
