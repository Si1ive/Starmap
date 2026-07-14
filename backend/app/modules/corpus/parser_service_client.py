"""HTTP clients and payload normalization for the MinerU parser service."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import requests

from app.modules.corpus.mineru_parser import normalize_mineru_block_type
from app.modules.corpus.parser_types import (
    ParsedAsset,
    ParsedBlock,
    ParsedDocumentResult,
    ParsedPage,
    ParserUnavailableError,
)


class HttpParserServiceClient:
    def __init__(
        self,
        parser_name: str,
        endpoint: str,
        timeout_seconds: int,
        deployment_target: str,
        processing_window_size: Optional[int] = None,
    ):
        self.name = parser_name
        self.version = "service"
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.deployment_target = deployment_target
        self.processing_window_size = processing_window_size

    @property
    def _target_label(self) -> str:
        return "远程" if self.deployment_target == "remote" else "本地"

    def parse(
        self,
        file_path: str,
        task_id: Optional[str] = None,
    ) -> ParsedDocumentResult:
        if not self.endpoint:
            raise ParserUnavailableError(
                self.name,
                f"未配置{self._target_label}解析服务地址，请在系统设置中确认解析服务配置",
            )

        try:
            with open(file_path, "rb") as file_obj:
                response = requests.post(
                    f"{self.endpoint}/parse",
                    data={
                        "parser_name": self.name,
                        **(
                            {
                                "processing_window_size": str(
                                    self.processing_window_size
                                )
                            }
                            if self.name == "mineru"
                            and self.processing_window_size
                            else {}
                        ),
                        **({"task_id": task_id} if task_id else {}),
                    },
                    files={
                        "file": (
                            Path(file_path).name,
                            file_obj,
                            "application/pdf",
                        )
                    },
                    timeout=self.timeout_seconds,
                )
        except requests.RequestException as exc:
            raise ParserUnavailableError(
                self.name,
                f"无法连接{self._target_label}解析服务 {self.endpoint}：{str(exc)[:200]}",
            ) from exc

        if response.status_code >= 400:
            detail = extract_service_error_detail(response)
            raise ParserUnavailableError(
                self.name,
                f"{self._target_label}解析服务返回异常（HTTP {response.status_code}）：{detail}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ParserUnavailableError(
                self.name,
                f"{self._target_label}解析服务返回了无效 JSON：{response.text[:200]}",
            ) from exc

        normalized = unwrap_service_payload(payload)
        return parsed_document_result_from_dict(
            parser_name=self.name,
            payload=normalized,
            fallback_metadata={
                "source_file": file_path,
                "service_endpoint": self.endpoint,
                "deployment_target": self.deployment_target,
            },
        )

    def fetch_progress(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return parser progress, or None when the optional endpoint is unavailable."""
        if not self.endpoint or not task_id:
            return None
        try:
            response = requests.get(
                f"{self.endpoint}/progress/{task_id}",
                timeout=5,
            )
            if response.status_code != 200:
                return None
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            return data if isinstance(data, dict) else None
        except Exception:
            return None


class LocalParserServiceClient(HttpParserServiceClient):
    def __init__(
        self,
        parser_name: str,
        endpoint: str,
        timeout_seconds: int,
        processing_window_size: Optional[int] = None,
    ):
        super().__init__(
            parser_name=parser_name,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            deployment_target="local",
            processing_window_size=processing_window_size,
        )


class RemoteParserServiceClient(HttpParserServiceClient):
    def __init__(
        self,
        parser_name: str,
        endpoint: str,
        timeout_seconds: int,
        processing_window_size: Optional[int] = None,
    ):
        super().__init__(
            parser_name=parser_name,
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            deployment_target="remote",
            processing_window_size=processing_window_size,
        )


def extract_service_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200] or "未知错误"

    if isinstance(payload, dict):
        if isinstance(payload.get("detail"), str):
            return payload["detail"][:200]
        if isinstance(payload.get("message"), str):
            return payload["message"][:200]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("detail"), str):
            return data["detail"][:200]
    return str(payload)[:200]


def unwrap_service_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    if isinstance(payload, dict):
        return payload
    raise ParserUnavailableError("unknown", "解析服务返回结构不符合约定")


def normalize_asset_type(raw_asset_type: Optional[Any]) -> str:
    """Normalize raw asset type to database-safe values."""
    value = (
        str(raw_asset_type).strip().lower()
        if raw_asset_type is not None
        else "figure"
    )
    if not value:
        return "figure"
    if value in {"figure", "table", "formula", "page_crop", "other"}:
        return value
    if value in {"img", "image", "picture", "chart"}:
        return "figure"
    if value in {"eq", "formula_block", "equation", "formula_img"}:
        return "formula"
    return "other"


def normalize_payload_block_type(raw_block_type: Optional[Any]) -> str:
    """Normalize parser-service block types to the internal block type set."""
    value = str(raw_block_type or "").strip().lower()
    if not value:
        return "paragraph"

    if value in {"image", "img", "picture", "chart"}:
        return "figure"
    if value in {"paragraph", "text"}:
        return "paragraph"
    if value in {
        "heading",
        "title",
        "table",
        "figure",
        "formula",
        "code",
        "code_block",
        "list",
        "header",
        "footer",
        "page_number",
        "aside_text",
        "page_footnote",
    }:
        return value if value != "code_block" else "code"
    if value == "equation":
        return "formula"

    return normalize_mineru_block_type(value)


def parsed_document_result_from_dict(
    parser_name: str,
    payload: Dict[str, Any],
    fallback_metadata: Optional[Dict[str, Any]] = None,
) -> ParsedDocumentResult:
    pages = [
        ParsedPage(
            page_no=int(item.get("page_no") or 1),
            width=int(item["width"]) if item.get("width") is not None else None,
            height=int(item["height"]) if item.get("height") is not None else None,
        )
        for item in (payload.get("pages") or [])
        if isinstance(item, dict)
    ]
    blocks = [
        ParsedBlock(
            page_no=int(item.get("page_no") or 1),
            block_type=normalize_payload_block_type(
                item.get("type") or item.get("category") or item.get("block_type")
            ),
            order_no=int(item.get("order_no") or 0),
            content_text=item.get("content_text"),
            content_md=item.get("content_md"),
            bbox=item.get("bbox") if isinstance(item.get("bbox"), dict) else None,
            html_table=item.get("html_table"),
            latex=item.get("latex"),
        )
        for item in (payload.get("blocks") or [])
        if isinstance(item, dict)
    ]
    assets = [
        ParsedAsset(
            page_no=int(item.get("page_no") or 1),
            asset_type=normalize_asset_type(item.get("asset_type")),
            caption_text=item.get("caption_text"),
            bbox=item.get("bbox") if isinstance(item.get("bbox"), dict) else None,
            file_path=item.get("file_path"),
            image_base64=item.get("image_base64"),
            image_ext=item.get("image_ext"),
        )
        for item in (payload.get("assets") or [])
        if isinstance(item, dict)
    ]

    metadata = (
        payload.get("metadata")
        if isinstance(payload.get("metadata"), dict)
        else {}
    )
    if fallback_metadata:
        metadata = {**fallback_metadata, **metadata}

    raw_output = payload.get("raw_output")
    if not isinstance(raw_output, dict):
        raw_output = payload

    return ParsedDocumentResult(
        parser_name=str(payload.get("parser_name") or parser_name),
        parser_version=str(payload.get("parser_version") or "service"),
        pages=pages,
        blocks=blocks,
        assets=assets,
        document_markdown=str(payload.get("document_markdown") or ""),
        confidence=(
            float(payload["confidence"])
            if payload.get("confidence") is not None
            else None
        ),
        metadata=metadata,
        raw_output=raw_output,
    )
