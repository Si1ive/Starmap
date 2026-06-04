"""
MySQL ORM 模型定义

使用 SQLAlchemy 2.0 声明式模型，与 docs/tech/data-model.md 保持一致。
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    String, Text, Date, DateTime, DECIMAL, JSON, 
    Enum, Boolean, Integer, BigInteger, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.mysql import Base


class Person(Base):
    """人物表"""
    __tablename__ = "persons"
    
    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="唯一标识")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="中文名")
    name_en: Mapped[Optional[str]] = mapped_column(String(100), comment="英文名")
    avatar: Mapped[Optional[str]] = mapped_column(String(500), comment="头像URL")
    gender: Mapped[Optional[str]] = mapped_column(Enum("male", "female", "unknown"), comment="性别")
    birth_date: Mapped[Optional[datetime]] = mapped_column(Date, comment="出生日期")
    birth_place: Mapped[Optional[str]] = mapped_column(String(200), comment="出生地")
    nationality: Mapped[Optional[str]] = mapped_column(String(50), comment="国籍")
    height: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), comment="身高(cm)")
    summary: Mapped[Optional[str]] = mapped_column(Text, comment="简介")
    biography: Mapped[Optional[str]] = mapped_column(Text, comment="详细传记")
    popularity_score: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2), comment="知名度评分")
    categories: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="分类标签")
    
    # 数据状态
    status: Mapped[str] = mapped_column(
        Enum("active", "pending", "deleted"), 
        default="pending", 
        comment="数据状态"
    )
    data_quality_score: Mapped[Optional[float]] = mapped_column(DECIMAL(3, 2), comment="数据质量评分")
    
    # 爬取信息
    crawl_source: Mapped[Optional[str]] = mapped_column(String(50), comment="数据来源")
    crawl_url: Mapped[Optional[str]] = mapped_column(String(500), comment="原始爬取URL")
    crawl_task_id: Mapped[Optional[str]] = mapped_column(String(32), comment="关联的爬取任务ID")
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, comment="保留原始爬取数据")
    
    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    # 关系
    works: Mapped[List["PersonWork"]] = relationship(back_populates="person")
    relations_as_source: Mapped[List["PersonRelation"]] = relationship(
        foreign_keys="PersonRelation.source_id",
        back_populates="source_person"
    )
    relations_as_target: Mapped[List["PersonRelation"]] = relationship(
        foreign_keys="PersonRelation.target_id",
        back_populates="target_person"
    )
    
    __table_args__ = (
        Index("idx_name", "name"),
        Index("idx_name_en", "name_en"),
        Index("idx_nationality", "nationality"),
        Index("idx_status", "status"),
        Index("idx_birth_date", "birth_date"),
        Index("idx_crawl_source", "crawl_source"),
        Index("idx_created_at", "created_at"),
        {"comment": "人物表"}
    )


class Work(Base):
    """作品表"""
    __tablename__ = "works"
    
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    title_en: Mapped[Optional[str]] = mapped_column(String(200))
    type: Mapped[Optional[str]] = mapped_column(
        Enum("album", "movie", "tv", "drama", "book", "single", "ep")
    )
    release_date: Mapped[Optional[datetime]] = mapped_column(Date)
    genre: Mapped[Optional[str]] = mapped_column(String(100))
    rating: Mapped[Optional[float]] = mapped_column(DECIMAL(3, 1))
    poster: Mapped[Optional[str]] = mapped_column(String(500))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    
    status: Mapped[str] = mapped_column(
        Enum("active", "pending", "deleted"), 
        default="pending"
    )
    
    crawl_source: Mapped[Optional[str]] = mapped_column(String(50))
    crawl_url: Mapped[Optional[str]] = mapped_column(String(500))
    crawl_task_id: Mapped[Optional[str]] = mapped_column(String(32))
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    # 关系
    persons: Mapped[List["PersonWork"]] = relationship(back_populates="work")
    
    __table_args__ = (
        Index("idx_work_title", "title"),
        Index("idx_work_type", "type"),
        Index("idx_work_release_date", "release_date"),
        Index("idx_work_status", "status"),
        {"comment": "作品表"}
    )


class PersonWork(Base):
    """人物-作品关联表"""
    __tablename__ = "person_works"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    person_id: Mapped[str] = mapped_column(String(32), ForeignKey("persons.id", ondelete="CASCADE"))
    work_id: Mapped[str] = mapped_column(String(32), ForeignKey("works.id", ondelete="CASCADE"))
    role: Mapped[Optional[str]] = mapped_column(String(100), comment="饰演角色/职位")
    role_type: Mapped[Optional[str]] = mapped_column(
        Enum("actor", "director", "singer", "composer", "producer", "writer")
    )
    is_lead: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否主演")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    # 关系
    person: Mapped["Person"] = relationship(back_populates="works")
    work: Mapped["Work"] = relationship(back_populates="persons")
    
    __table_args__ = (
        UniqueConstraint("person_id", "work_id", "role_type", name="uk_person_work_role"),
        Index("idx_pw_person_id", "person_id"),
        Index("idx_pw_work_id", "work_id"),
        {"comment": "人物作品关联表"}
    )


class PersonRelation(Base):
    """人物关系表"""
    __tablename__ = "person_relations"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(
        String(32), 
        ForeignKey("persons.id", ondelete="CASCADE"),
        comment="源人物ID"
    )
    target_id: Mapped[str] = mapped_column(
        String(32), 
        ForeignKey("persons.id", ondelete="CASCADE"),
        comment="目标人物ID"
    )
    relation_type: Mapped[str] = mapped_column(
        Enum("MARRIED_TO", "COLLABORATED_WITH", "MENTOR_OF", "RELATIVE", "FRIEND"),
        comment="关系类型"
    )
    properties: Mapped[Optional[dict]] = mapped_column(JSON, comment="关系属性")
    confidence: Mapped[float] = mapped_column(
        DECIMAL(3, 2), 
        default=1.0, 
        comment="关系可信度"
    )
    source: Mapped[Optional[str]] = mapped_column(String(50), comment="数据来源")
    
    # 验证状态
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_by: Mapped[Optional[str]] = mapped_column(String(32))
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    # 关系
    source_person: Mapped["Person"] = relationship(
        foreign_keys=[source_id],
        back_populates="relations_as_source"
    )
    target_person: Mapped["Person"] = relationship(
        foreign_keys=[target_id],
        back_populates="relations_as_target"
    )
    
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation_type", name="uk_relation"),
        Index("idx_rel_source_id", "source_id"),
        Index("idx_rel_target_id", "target_id"),
        Index("idx_rel_type", "relation_type"),
        Index("idx_rel_confidence", "confidence"),
        {"comment": "人物关系表"}
    )


class CrawlTask(Base):
    """爬虫任务表"""
    __tablename__ = "crawl_tasks"
    
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    task_type: Mapped[Optional[str]] = mapped_column(
        Enum("full", "incremental", "targeted")
    )
    source: Mapped[Optional[str]] = mapped_column(String(50))
    target_count: Mapped[Optional[int]]
    completed_count: Mapped[int] = mapped_column(default=0)
    success_count: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "completed", "failed", "stopped"),
        default="pending"
    )
    progress: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)
    config: Mapped[Optional[dict]] = mapped_column(JSON)
    
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_by: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    __table_args__ = (
        Index("idx_ct_status", "status"),
        Index("idx_ct_task_type", "task_type"),
        Index("idx_ct_source", "source"),
        Index("idx_ct_created_at", "created_at"),
        {"comment": "爬虫任务表"}
    )


class CrawlLog(Base):
    """爬虫日志表"""
    __tablename__ = "crawl_logs"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(
        Enum("INFO", "WARNING", "ERROR", "DEBUG"),
        default="INFO"
    )
    
    resource_url: Mapped[Optional[str]] = mapped_column(String(500))
    resource_name: Mapped[Optional[str]] = mapped_column(String(200))
    resource_type: Mapped[Optional[str]] = mapped_column(
        Enum("person", "work", "page")
    )
    
    action: Mapped[Optional[str]] = mapped_column(String(50))
    status: Mapped[Optional[str]] = mapped_column(
        Enum("success", "failed", "retry", "pending")
    )
    duration_ms: Mapped[Optional[int]]
    message: Mapped[Optional[str]] = mapped_column(Text)
    error_type: Mapped[Optional[str]] = mapped_column(String(50))
    error_detail: Mapped[Optional[str]] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_cl_task_id", "task_id"),
        Index("idx_cl_level", "level"),
        Index("idx_cl_status", "status"),
        Index("idx_cl_resource_type", "resource_type"),
        Index("idx_cl_error_type", "error_type"),
        Index("idx_cl_created_at", "created_at"),
        {"comment": "爬虫日志表"}
    )


class AdminUser(Base):
    """管理员用户表"""
    __tablename__ = "admin_users"
    
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        Enum("super_admin", "data_admin", "operator"),
        default="operator"
    )
    permissions: Mapped[Optional[List[str]]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(45))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    __table_args__ = (
        Index("idx_au_username", "username"),
        Index("idx_au_role", "role"),
        Index("idx_au_is_active", "is_active"),
        {"comment": "管理员用户表"}
    )


class AuditLog(Base):
    """审计日志表"""
    __tablename__ = "audit_logs"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(32))
    action: Mapped[Optional[str]] = mapped_column(String(100))
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    resource_id: Mapped[Optional[str]] = mapped_column(String(32))
    old_values: Mapped[Optional[dict]] = mapped_column(JSON)
    new_values: Mapped[Optional[dict]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45))
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_al_user_id", "user_id"),
        Index("idx_al_resource", "resource_type", "resource_id"),
        Index("idx_al_action", "action"),
        Index("idx_al_created_at", "created_at"),
        {"comment": "审计日志表"}
    )
