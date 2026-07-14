"""空的后台兼容路由，等待移除主应用注册。"""

from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["后台管理"])
