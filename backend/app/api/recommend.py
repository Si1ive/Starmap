"""
推荐API路由

提供推荐相关的RESTful API：
- GET /persons/{person_id}/similar - 相似人物推荐

注意：相似人物接口已在 person.py 中实现，
此处保留路由文件用于后续扩展其他推荐功能。
"""

from fastapi import APIRouter

router = APIRouter(tags=["推荐"])

# 相似人物推荐已移至 /persons/{person_id}/similar
# 后续可在此添加：
# - 热门人物推荐
# - 个性化推荐
# - 趋势推荐
