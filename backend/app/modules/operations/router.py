"""Authentication and administrator-management routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApiResponse
from app.db import get_db
from app.models.mysql_models import AdminUser, AuditLog
from app.modules.operations.schemas import (
    CreateUserRequest,
    LoginRequest,
    UpdateUserRequest,
)
from app.modules.operations.security import (
    create_admin_access_token,
    hash_admin_password,
    needs_password_rehash,
    require_current_admin,
    require_user_manager,
    verify_admin_password,
)


router = APIRouter(prefix="/admin", tags=["后台认证与用户"])


@router.post("/auth/login", response_model=ApiResponse)
async def login(
    req: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AdminUser).where(AdminUser.username == req.username)
    )
    user = result.scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not verify_admin_password(req.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if needs_password_rehash(user.password_hash):
        user.password_hash = hash_admin_password(req.password)
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.last_login_ip = request.client.host if request.client else None
    db.add(
        AuditLog(
            user_id=user.id,
            action="admin_login",
            resource_type="admin_user",
            resource_id=user.id,
            ip_address=user.last_login_ip,
            user_agent=request.headers.get("User-Agent"),
        )
    )
    await db.commit()

    return ApiResponse(
        message="登录成功",
        data={
            "token": create_admin_access_token(user.id),
            "user": _admin_user_identity(user),
        },
    )


@router.post("/auth/logout", response_model=ApiResponse)
async def logout(
    current_admin: AdminUser = Depends(require_current_admin),
):
    return ApiResponse(message="登出成功", data={"user_id": current_admin.id})


@router.get("/auth/me", response_model=ApiResponse)
async def get_current_user(
    current_admin: AdminUser = Depends(require_current_admin),
):
    return ApiResponse(data=_admin_user_identity(current_admin))


@router.get("/users", response_model=ApiResponse)
async def get_users(
    db: AsyncSession = Depends(get_db),
    _current_admin: AdminUser = Depends(require_user_manager),
):
    result = await db.execute(select(AdminUser).order_by(AdminUser.created_at.desc()))
    users = result.scalars().all()
    return ApiResponse(data={"users": [_admin_user_to_dict(user) for user in users]})


@router.post("/users", response_model=ApiResponse)
async def create_user(
    req: CreateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_user_manager),
):
    existing = await db.scalar(
        select(AdminUser).where(
            or_(AdminUser.username == req.username, AdminUser.email == req.email)
        )
    )
    if existing:
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")

    user = AdminUser(
        id=uuid.uuid4().hex[:32],
        username=req.username,
        email=req.email,
        password_hash=hash_admin_password(req.password),
        role=req.role,
        permissions=req.permissions,
        is_active=req.is_active,
    )
    db.add(user)
    _add_admin_audit_log(
        db,
        request,
        user_id=current_admin.id,
        action="admin_user_create",
        resource_id=user.id,
        new_values=_admin_user_to_dict(user),
    )
    await db.commit()
    return ApiResponse(message="创建成功", data={"user": _admin_user_to_dict(user)})


@router.put("/users/{user_id}", response_model=ApiResponse)
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_user_manager),
):
    user = await db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if req.is_active is False and user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="不能停用当前登录用户")

    old_values = _admin_user_to_dict(user)
    if req.email is not None and req.email != user.email:
        existing = await db.scalar(
            select(AdminUser).where(AdminUser.email == req.email, AdminUser.id != user_id)
        )
        if existing:
            raise HTTPException(status_code=400, detail="邮箱已存在")
        user.email = req.email
    if req.password is not None:
        user.password_hash = hash_admin_password(req.password)
    if req.role is not None:
        user.role = req.role
    if req.permissions is not None:
        user.permissions = req.permissions
    if req.is_active is not None:
        user.is_active = req.is_active

    _add_admin_audit_log(
        db,
        request,
        user_id=current_admin.id,
        action="admin_user_update",
        resource_id=user.id,
        old_values=old_values,
        new_values=_admin_user_to_dict(user),
    )
    await db.commit()
    return ApiResponse(message="更新成功", data={"user": _admin_user_to_dict(user)})


@router.delete("/users/{user_id}", response_model=ApiResponse)
async def delete_user(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_admin: AdminUser = Depends(require_user_manager),
):
    user = await db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录用户")
    if user.username == "admin":
        raise HTTPException(status_code=400, detail="默认管理员不能删除")

    old_values = _admin_user_to_dict(user)
    await db.delete(user)
    _add_admin_audit_log(
        db,
        request,
        user_id=current_admin.id,
        action="admin_user_delete",
        resource_id=user_id,
        old_values=old_values,
    )
    await db.commit()
    return ApiResponse(message="删除成功")


def _admin_user_identity(user: AdminUser) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.username,
        "avatar": None,
        "role": user.role,
        "permissions": user.permissions or [],
    }


def _admin_user_to_dict(user: AdminUser) -> dict:
    return {
        **_admin_user_identity(user),
        "email": user.email,
        "is_active": bool(user.is_active),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _add_admin_audit_log(
    db: AsyncSession,
    request: Request,
    *,
    user_id: str,
    action: str,
    resource_id: str,
    old_values: dict | None = None,
    new_values: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            resource_type="admin_user",
            resource_id=resource_id,
            old_values=old_values,
            new_values=new_values,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("User-Agent"),
        )
    )
