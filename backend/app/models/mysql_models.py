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
        Enum("full", "incremental", "targeted", "health_check", "cleanup")
    )
    source: Mapped[Optional[str]] = mapped_column(String(50))
    source_id: Mapped[Optional[str]] = mapped_column(String(32), comment="爬取源ID")
    target_count: Mapped[Optional[int]]
    completed_count: Mapped[int] = mapped_column(default=0)
    success_count: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    total_requests: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "completed", "failed", "stopped"),
        default="pending"
    )
    progress: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)
    config: Mapped[Optional[dict]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    
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
        Index("idx_ct_source_id", "source_id"),
        Index("idx_ct_created_at", "created_at"),
        {"comment": "爬虫任务表"}
    )


class CrawlLog(Base):
    """爬虫日志表"""
    __tablename__ = "crawl_logs"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[Optional[str]] = mapped_column(String(32), comment="爬取源ID")
    level: Mapped[str] = mapped_column(
        Enum("INFO", "WARNING", "ERROR", "DEBUG", "SUCCESS", "CRITICAL"),
        default="INFO"
    )
    stage: Mapped[Optional[str]] = mapped_column(
        String(50), comment="阶段: fetch/parse/validate/store"
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
    details: Mapped[Optional[dict]] = mapped_column(JSON, comment="详细日志信息")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_cl_task_id", "task_id"),
        Index("idx_cl_source_id", "source_id"),
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


class CrawlSource(Base):
    """爬取源配置表"""
    __tablename__ = "crawl_sources"
    
    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="唯一标识")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="源名称")
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="源编码")
    type: Mapped[Optional[str]] = mapped_column(String(50), comment="源类型")
    base_url: Mapped[Optional[str]] = mapped_column(String(500), comment="基础URL")
    config: Mapped[Optional[dict]] = mapped_column(JSON, comment="源配置")
    
    # 频率控制
    request_interval: Mapped[float] = mapped_column(DECIMAL(3, 1), default=1.0, comment="请求间隔(秒)")
    daily_limit: Mapped[int] = mapped_column(default=1000, comment="每日请求上限")
    concurrent_limit: Mapped[int] = mapped_column(default=5, comment="并发数限制")
    
    # 状态
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive", "error", "deprecated"),
        default="active"
    )
    health_status: Mapped[str] = mapped_column(
        Enum("healthy", "degraded", "down"),
        default="healthy"
    )
    last_health_check: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    # 统计
    total_requests: Mapped[int] = mapped_column(BigInteger, default=0)
    total_success: Mapped[int] = mapped_column(BigInteger, default=0)
    total_failed: Mapped[int] = mapped_column(BigInteger, default=0)
    avg_response_time: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 2))
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    
    __table_args__ = (
        Index("idx_cs_status", "status"),
        Index("idx_cs_type", "type"),
        Index("idx_cs_health", "health_status"),
        {"comment": "爬取源配置表"}
    )


class CrawlSourceStats(Base):
    """爬取源日统计表"""
    __tablename__ = "crawl_source_stats"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="爬取源ID")
    stat_date: Mapped[datetime] = mapped_column(Date, nullable=False, comment="统计日期")
    
    # 请求统计
    total_requests: Mapped[int] = mapped_column(default=0)
    success_requests: Mapped[int] = mapped_column(default=0)
    failed_requests: Mapped[int] = mapped_column(default=0)
    timeout_requests: Mapped[int] = mapped_column(default=0)
    rate_limited_requests: Mapped[int] = mapped_column(default=0)
    
    # 数据产出
    persons_extracted: Mapped[int] = mapped_column(default=0)
    works_extracted: Mapped[int] = mapped_column(default=0)
    relations_extracted: Mapped[int] = mapped_column(default=0)
    valid_records: Mapped[int] = mapped_column(default=0)
    duplicate_records: Mapped[int] = mapped_column(default=0)
    
    # 性能指标
    avg_response_time: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 2))
    min_response_time: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 2))
    max_response_time: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 2))
    p95_response_time: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 2))
    
    # 数据质量
    avg_completeness: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 2))
    
    # 资源消耗
    total_duration: Mapped[int] = mapped_column(default=0, comment="总耗时(秒)")
    data_size_mb: Mapped[Optional[float]] = mapped_column(DECIMAL(8, 2))
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint("source_id", "stat_date", name="uk_source_date"),
        Index("idx_css_stat_date", "stat_date"),
        Index("idx_css_source_id", "source_id"),
        {"comment": "爬取源日统计表"}
    )


class CrawlSchedule(Base):
    """定时任务配置表"""
    __tablename__ = "crawl_schedules"
    
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    task_type: Mapped[str] = mapped_column(
        Enum("full", "incremental", "targeted", "health_check", "cleanup"),
        nullable=False
    )
    source_ids: Mapped[Optional[List[str]]] = mapped_column(JSON)
    target_config: Mapped[Optional[dict]] = mapped_column(JSON)
    
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Shanghai")
    
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_retries: Mapped[int] = mapped_column(default=3)
    retry_interval: Mapped[int] = mapped_column(default=300)
    concurrent_limit: Mapped[int] = mapped_column(default=1)
    timeout: Mapped[int] = mapped_column(default=3600)
    
    notify_on_success: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_on_failure: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_emails: Mapped[Optional[List[str]]] = mapped_column(JSON)
    
    total_runs: Mapped[int] = mapped_column(default=0)
    success_runs: Mapped[int] = mapped_column(default=0)
    failed_runs: Mapped[int] = mapped_column(default=0)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_run_status: Mapped[Optional[str]] = mapped_column(
        Enum("success", "failed", "running", "timeout")
    )
    last_run_duration: Mapped[Optional[int]]
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    
    created_by: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    
    __table_args__ = (
        Index("idx_csch_enabled", "is_enabled"),
        Index("idx_csch_next_run", "next_run_at"),
        Index("idx_csch_task_type", "task_type"),
        {"comment": "定时任务配置表"}
    )


class CrawlScheduleRun(Base):
    """定时任务执行历史表"""
    __tablename__ = "crawl_schedule_runs"
    
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    schedule_id: Mapped[str] = mapped_column(String(32), nullable=False)
    task_id: Mapped[Optional[str]] = mapped_column(String(32))
    
    status: Mapped[str] = mapped_column(
        Enum("running", "success", "failed", "timeout", "cancelled"),
        nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    duration: Mapped[Optional[int]]
    
    total_requests: Mapped[int] = mapped_column(default=0)
    success_count: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    log_summary: Mapped[Optional[str]] = mapped_column(Text)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index("idx_csr_schedule_id", "schedule_id"),
        Index("idx_csr_status", "status"),
        Index("idx_csr_started_at", "started_at"),
        {"comment": "定时任务执行历史表"}
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


# ========== 408 考研平台模型 ==========


class Subject(Base):
    """学科表：数据结构/计组/操作系统/计网"""
    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="唯一标识")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="学科名称")
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment="学科编码")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="学科描述")
    icon: Mapped[Optional[str]] = mapped_column(String(100), comment="图标标识")
    sort_order: Mapped[int] = mapped_column(default=0, comment="排序序号")
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive"),
        default="active",
        comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    chapters: Mapped[List["Chapter"]] = relationship(back_populates="subject")

    __table_args__ = (
        Index("idx_subject_code", "code"),
        Index("idx_subject_status", "status"),
        Index("idx_subject_sort", "sort_order"),
        {"comment": "学科表"}
    )


class Chapter(Base):
    """章节表"""
    __tablename__ = "chapters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="唯一标识")
    subject_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False, comment="所属学科ID"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="章节名称")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="章节描述")
    sort_order: Mapped[int] = mapped_column(default=0, comment="排序序号")
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive"),
        default="active",
        comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    subject: Mapped["Subject"] = relationship(back_populates="chapters")

    __table_args__ = (
        Index("idx_chapter_subject", "subject_id"),
        Index("idx_chapter_sort", "subject_id", "sort_order"),
        {"comment": "章节表"}
    )


class KnowledgePoint(Base):
    """知识点表"""
    __tablename__ = "knowledge_points"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="唯一标识")
    chapter_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False, comment="所属章节ID"
    )
    subject_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False, comment="所属学科ID（冗余，方便查询）"
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="知识点标题")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="知识点正文（Markdown）")
    difficulty: Mapped[str] = mapped_column(
        Enum("easy", "medium", "hard"),
        default="medium",
        comment="难度"
    )
    exam_frequency: Mapped[str] = mapped_column(
        Enum("high", "medium", "low", "never"),
        default="medium",
        comment="考试频率"
    )
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="标签列表")
    key_points: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="要点列表")
    related_point_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="关联知识点ID")
    source: Mapped[Optional[str]] = mapped_column(String(100), comment="来源，如 王道2025/第3章")
    source_page: Mapped[Optional[str]] = mapped_column(String(20), comment="来源页码")
    crawl_task_id: Mapped[Optional[str]] = mapped_column(String(32), comment="关联爬取任务ID")
    status: Mapped[str] = mapped_column(
        Enum("active", "pending", "deleted"),
        default="pending",
        comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_kp_chapter", "chapter_id"),
        Index("idx_kp_subject", "subject_id"),
        Index("idx_kp_difficulty", "difficulty"),
        Index("idx_kp_exam_freq", "exam_frequency"),
        Index("idx_kp_status", "status"),
        Index("idx_kp_title", "title"),
        {"comment": "知识点表"}
    )


class Question(Base):
    """题目表"""
    __tablename__ = "questions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="唯一标识")
    subject_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False, comment="所属学科ID"
    )
    chapter_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False, comment="所属章节ID"
    )
    type: Mapped[str] = mapped_column(
        Enum("choice", "fill", "judge", "short_answer", "design", "analysis"),
        nullable=False,
        comment="题型"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="题目正文")
    options: Mapped[Optional[List[dict]]] = mapped_column(
        JSON, comment="选择题选项，格式: [{\"key\":\"A\",\"text\":\"...\"}]"
    )
    answer: Mapped[str] = mapped_column(Text, nullable=False, comment="标准答案")
    explanation: Mapped[Optional[str]] = mapped_column(Text, comment="解析")
    difficulty: Mapped[str] = mapped_column(
        Enum("easy", "medium", "hard"),
        default="medium",
        comment="难度"
    )
    source: Mapped[Optional[str]] = mapped_column(String(100), comment="来源，如 2024年408真题")
    exam_year: Mapped[int] = mapped_column(default=0, comment="真题年份，练习题为0")
    knowledge_point_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="关联知识点ID")
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="标签")
    status: Mapped[str] = mapped_column(
        Enum("active", "pending", "deleted"),
        default="pending",
        comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_q_subject", "subject_id"),
        Index("idx_q_chapter", "chapter_id"),
        Index("idx_q_type", "type"),
        Index("idx_q_difficulty", "difficulty"),
        Index("idx_q_exam_year", "exam_year"),
        Index("idx_q_status", "status"),
        {"comment": "题目表"}
    )


class UserQuestionRecord(Base):
    """用户做题记录表"""
    __tablename__ = "user_question_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="用户会话ID")
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False, comment="题目ID"
    )
    user_answer: Mapped[Optional[str]] = mapped_column(Text, comment="用户答案")
    is_correct: Mapped[Optional[bool]] = mapped_column(Boolean, comment="是否正确")
    time_spent: Mapped[Optional[int]] = mapped_column(comment="用时（秒）")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_uqr_session", "session_id"),
        Index("idx_uqr_question", "question_id"),
        Index("idx_uqr_created", "created_at"),
        {"comment": "用户做题记录表"}
    )
