"""
实体（知识点 / 题目）与文档资产（figure / table / formula）的关联服务。

入口：在抽取阶段，根据实体覆盖的 block 范围（page_no 或 block_id 列表），找到该
区域内的 DocumentAsset 行并建立 EntityAssetLink。
"""

import uuid
from typing import Iterable, List, Optional, Set, Dict, Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.mysql_models import (
    DocumentAsset, EntityAssetLink,
)

logger = get_logger(__name__)


def _gen_id() -> str:
    return uuid.uuid4().hex[:32]


async def link_entity_assets_by_pages(
    session: AsyncSession,
    entity_type: str,
    entity_id: str,
    document_id: str,
    page_numbers: Iterable[int],
    asset_types: Optional[List[str]] = None,
) -> int:
    """
    把指定页码范围内的 figure/table/formula 资产关联到实体上。

    Args:
        entity_type: 'knowledge_point' / 'question'
        entity_id: 实体 ID
        document_id: 文档 ID
        page_numbers: 实体覆盖的页码集合
        asset_types: 资产类型过滤；默认 figure/table/formula

    Returns:
        新建的关联数量
    """
    pages = sorted({int(p) for p in page_numbers if p is not None})
    if not pages:
        return 0

    asset_types = asset_types or ["figure", "table", "formula"]

    rows = (await session.execute(
        select(DocumentAsset).where(
            DocumentAsset.document_id == document_id,
            DocumentAsset.page_no.in_(pages),
            DocumentAsset.asset_type.in_(asset_types),
        )
    )).scalars().all()
    if not rows:
        return 0

    existing = (await session.execute(
        select(EntityAssetLink.asset_id).where(
            EntityAssetLink.entity_type == entity_type,
            EntityAssetLink.entity_id == entity_id,
        )
    )).scalars().all()
    existing_set: Set[str] = set(existing)

    created = 0
    for idx, asset in enumerate(rows):
        if asset.id in existing_set:
            continue
        session.add(EntityAssetLink(
            id=_gen_id(),
            entity_type=entity_type,
            entity_id=entity_id,
            asset_id=asset.id,
            relation="inline",
            sort_order=idx,
        ))
        created += 1

    return created


async def get_entity_assets(
    session: AsyncSession,
    entity_type: str,
    entity_id: str,
) -> List[Dict[str, Any]]:
    """获取实体关联的所有资产（含资产元数据）"""
    rows = (await session.execute(
        select(EntityAssetLink, DocumentAsset)
        .join(DocumentAsset, EntityAssetLink.asset_id == DocumentAsset.id)
        .where(
            EntityAssetLink.entity_type == entity_type,
            EntityAssetLink.entity_id == entity_id,
        )
        .order_by(EntityAssetLink.sort_order, DocumentAsset.page_no)
    )).all()

    items: List[Dict[str, Any]] = []
    for link, asset in rows:
        items.append({
            "link_id": link.id,
            "relation": link.relation,
            "asset_id": asset.id,
            "asset_type": asset.asset_type,
            "page_no": asset.page_no,
            "file_path": asset.file_path,
            "caption_text": asset.caption_text,
            "bbox": asset.bbox,
            "metadata": asset.metadata_json,
            "ocr_text": asset.ocr_text,
        })
    return items


async def cleanup_entity_links(
    session: AsyncSession,
    entity_type: str,
    entity_ids: Iterable[str],
) -> int:
    """删除实体的所有资产关联（用于重新抽取前清理）"""
    ids = list(entity_ids)
    if not ids:
        return 0
    result = await session.execute(
        delete(EntityAssetLink).where(
            EntityAssetLink.entity_type == entity_type,
            EntityAssetLink.entity_id.in_(ids),
        )
    )
    return int(result.rowcount or 0)
