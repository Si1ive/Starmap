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
        Enum("file", "page", "pdf")
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
    files_extracted: Mapped[int] = mapped_column(default=0, comment="下载文件数")
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


class SystemConfig(Base):
    """系统配置表"""
    __tablename__ = "system_configs"

    config_key: Mapped[str] = mapped_column(String(100), primary_key=True, comment="配置键")
    config_value: Mapped[Optional[dict]] = mapped_column(JSON, comment="配置值 JSON")
    description: Mapped[Optional[str]] = mapped_column(String(255), comment="配置说明")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        {"comment": "系统配置表"}
    )


# ========== 408 考研平台模型 ==========


class Subject(Base):
    """学科表：数据结构/计组/操作系统/计网"""
    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="唯一标识")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="学科名称")
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, comment="学科编码")
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
        nullable=False, comment="所属章节ID（兼容旧接口）"
    )
    subject_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False, comment="所属学科ID"
    )
    # 新增字段 - 多模态扩展
    primary_chapter_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("canonical_chapters.id", ondelete="SET NULL"),
        comment="主标准章节ID"
    )
    source_document_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="SET NULL"),
        comment="来源文档ID"
    )
    canonical_title: Mapped[Optional[str]] = mapped_column(String(200), comment="标准化标题")
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
    topic_terms: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="主题术语列表")
    aliases: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="别名列表")
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="标签列表")
    key_points: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="要点列表")
    related_point_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="关联知识点ID")
    summary: Mapped[Optional[str]] = mapped_column(Text, comment="LLM 一句话摘要（向量召回用）")
    enrich_status: Mapped[str] = mapped_column(
        Enum("pending", "enriching", "done", "failed"),
        default="pending", comment="LLM 富化状态"
    )
    source: Mapped[Optional[str]] = mapped_column(String(100), comment="来源，如 王道2025/第3章")
    source_page: Mapped[Optional[str]] = mapped_column(String(20), comment="来源页码")
    crawl_task_id: Mapped[Optional[str]] = mapped_column(String(32), comment="关联爬取任务ID")
    review_status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected"),
        default="pending", comment="审核状态"
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, comment="审核备注")
    status: Mapped[str] = mapped_column(
        Enum("active", "pending", "deleted"),
        default="pending",
        comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # relationships
    primary_chapter: Mapped[Optional["CanonicalChapter"]] = relationship()
    source_document: Mapped[Optional["Document"]] = relationship()
    chapter_links: Mapped[List["KnowledgePointChapterLink"]] = relationship(back_populates="knowledge_point")
    source_links: Mapped[List["EntitySourceLink"]] = relationship(
        primaryjoin="and_(EntitySourceLink.entity_type=='knowledge_point', "
                    "foreign(EntitySourceLink.entity_id)==KnowledgePoint.id)",
        viewonly=True
    )

    __table_args__ = (
        Index("idx_kp_chapter", "chapter_id"),
        Index("idx_kp_primary_chapter", "primary_chapter_id"),
        Index("idx_kp_subject", "subject_id"),
        Index("idx_kp_difficulty", "difficulty"),
        Index("idx_kp_exam_freq", "exam_frequency"),
        Index("idx_kp_status", "status"),
        Index("idx_kp_review_status", "review_status"),
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
        nullable=False, comment="所属章节ID（兼容旧接口）"
    )
    # 新增字段 - 多模态扩展
    primary_chapter_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("canonical_chapters.id", ondelete="SET NULL"),
        comment="主标准章节ID"
    )
    source_document_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="SET NULL"),
        comment="来源文档ID"
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
    exam_scope: Mapped[Optional[str]] = mapped_column(String(50), comment="考试范围，如 408")
    exam_year: Mapped[int] = mapped_column(default=0, comment="真题年份，练习题为0")
    paper_name: Mapped[Optional[str]] = mapped_column(String(255), comment="试卷名称")
    question_no: Mapped[Optional[str]] = mapped_column(String(20), comment="题号")
    topic_terms: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="主题术语列表")
    knowledge_point_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="关联知识点ID")
    tags: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="标签")
    answer_source: Mapped[str] = mapped_column(
        Enum("none", "extracted", "llm", "manual"),
        default="none", comment="答案来源：none未填/extracted原卷抽取/llm生成/manual人工"
    )
    explanation_source: Mapped[str] = mapped_column(
        Enum("none", "extracted", "llm", "manual"),
        default="none", comment="解析来源"
    )
    enrich_status: Mapped[str] = mapped_column(
        Enum("pending", "enriching", "done", "failed"),
        default="pending", comment="LLM 富化状态"
    )
    review_status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected"),
        default="pending", comment="审核状态"
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, comment="审核备注")
    status: Mapped[str] = mapped_column(
        Enum("active", "pending", "deleted"),
        default="pending",
        comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # relationships
    primary_chapter: Mapped[Optional["CanonicalChapter"]] = relationship()
    source_document: Mapped[Optional["Document"]] = relationship()
    chapter_links: Mapped[List["QuestionChapterLink"]] = relationship(back_populates="question")
    source_links: Mapped[List["EntitySourceLink"]] = relationship(
        primaryjoin="and_(EntitySourceLink.entity_type=='question', "
                    "foreign(EntitySourceLink.entity_id)==Question.id)",
        viewonly=True
    )

    __table_args__ = (
        Index("idx_q_subject", "subject_id"),
        Index("idx_q_chapter", "chapter_id"),
        Index("idx_q_primary_chapter", "primary_chapter_id"),
        Index("idx_q_type", "type"),
        Index("idx_q_difficulty", "difficulty"),
        Index("idx_q_exam_year", "exam_year"),
        Index("idx_q_exam_scope", "exam_scope"),
        Index("idx_q_status", "status"),
        Index("idx_q_review_status", "review_status"),
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


class DownloadedFile(Base):
    """已下载文件记录表"""
    __tablename__ = "downloaded_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="唯一标识")
    task_id: Mapped[Optional[str]] = mapped_column(String(32), comment="关联任务ID")
    repo_name: Mapped[Optional[str]] = mapped_column(String(200), comment="仓库名称，如 user/repo")
    repo_url: Mapped[Optional[str]] = mapped_column(String(500), comment="仓库URL")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="仓库内文件路径")
    file_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="文件名")
    file_type: Mapped[Optional[str]] = mapped_column(String(20), comment="文件类型: pdf/doc/ppt")
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, comment="文件大小(bytes)")
    download_url: Mapped[Optional[str]] = mapped_column(String(500), comment="下载URL")
    local_path: Mapped[Optional[str]] = mapped_column(String(500), comment="本地存储路径")
    status: Mapped[str] = mapped_column(
        Enum("downloaded", "skipped", "failed", "processing", "processed"),
        default="downloaded",
        comment="状态"
    )
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="失败原因")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_df_task_id", "task_id"),
        Index("idx_df_repo", "repo_name"),
        Index("idx_df_status", "status"),
        Index("idx_df_file_type", "file_type"),
        {"comment": "已下载文件记录表"}
    )


# ========== 多模态语料库模型 ==========


class CorpusFile(Base):
    """语料文件注册表"""
    __tablename__ = "corpus_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="语料文件ID")
    source_type: Mapped[str] = mapped_column(
        Enum("crawler", "manual", "upload", "import"),
        nullable=False, comment="来源类型"
    )
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), comment="来源引用，如 task_id 或 batch_id")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="文件名")
    file_ext: Mapped[str] = mapped_column(String(20), nullable=False, comment="扩展名")
    local_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="本地路径")
    storage_uri: Mapped[Optional[str]] = mapped_column(String(500), comment="对象存储URI")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, comment="文件哈希")
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, comment="文件大小")
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), comment="MIME类型")
    language: Mapped[Optional[str]] = mapped_column(String(20), comment="文档主语言")
    doc_type: Mapped[str] = mapped_column(
        Enum("textbook", "past_exam", "mock_exam", "notes", "other"),
        default="other", comment="文档业务类型"
    )
    version: Mapped[int] = mapped_column(default=1, comment="同源版本号")
    status: Mapped[str] = mapped_column(
        Enum("pending", "parsing", "parsed", "extracting", "indexed", "failed", "archived"),
        default="pending", comment="处理状态"
    )
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="失败原因")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("sha256", name="uk_corpus_files_sha256"),
        Index("idx_corpus_files_status", "status"),
        Index("idx_corpus_files_source_type", "source_type"),
        Index("idx_corpus_files_doc_type", "doc_type"),
        {"comment": "统一语料文件注册表"}
    )


class ParseRun(Base):
    """文档解析执行记录"""
    __tablename__ = "parse_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="解析任务ID")
    corpus_file_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("corpus_files.id", ondelete="CASCADE"),
        nullable=False, comment="语料文件ID"
    )
    parser_name: Mapped[str] = mapped_column(String(50), nullable=False, comment="解析器名称")
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False, comment="解析器版本")
    parse_mode: Mapped[str] = mapped_column(
        Enum("primary", "fallback", "retry", "manual_fix"),
        default="primary", comment="解析模式"
    )
    status: Mapped[str] = mapped_column(
        Enum("running", "success", "failed", "partial"),
        default="running", comment="执行状态"
    )
    page_count: Mapped[Optional[int]] = mapped_column(comment="识别页数")
    block_count: Mapped[Optional[int]] = mapped_column(comment="识别块数")
    asset_count: Mapped[Optional[int]] = mapped_column(comment="识别资产数")
    confidence: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 4), comment="整体置信度")
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="错误信息")
    metrics_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="耗时与质量指标")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_parse_runs_corpus_file_id", "corpus_file_id"),
        Index("idx_parse_runs_status", "status"),
        {"comment": "文档解析执行记录"}
    )


class Document(Base):
    """正规化文档主表"""
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="文档ID")
    corpus_file_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("corpus_files.id", ondelete="CASCADE"),
        nullable=False, comment="文件ID"
    )
    latest_parse_run_id: Mapped[Optional[str]] = mapped_column(String(32), comment="最新成功解析ID")
    title: Mapped[Optional[str]] = mapped_column(String(255), comment="文档标题")
    doc_type: Mapped[str] = mapped_column(
        Enum("textbook", "past_exam", "mock_exam", "notes", "other"),
        default="other", comment="文档类型"
    )
    subject_id: Mapped[Optional[str]] = mapped_column(String(32), comment="主学科ID")
    source_label: Mapped[Optional[str]] = mapped_column(String(255), comment="展示来源")
    exam_scope: Mapped[Optional[str]] = mapped_column(String(50), comment="例如408")
    exam_year: Mapped[Optional[int]] = mapped_column(comment="真题年份")
    paper_name: Mapped[Optional[str]] = mapped_column(String(255), comment="试卷名")
    language: Mapped[Optional[str]] = mapped_column(String(20), comment="文档语言")
    page_count: Mapped[Optional[int]] = mapped_column(comment="页数")
    document_markdown: Mapped[Optional[str]] = mapped_column(Text, comment="展示Markdown")
    document_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="结构化文档对象")
    raw_parser_output: Mapped[Optional[dict]] = mapped_column(JSON, comment="解析器原始输出JSON")
    status: Mapped[str] = mapped_column(
        Enum("active", "pending", "deleted"),
        default="pending", comment="业务状态"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_documents_corpus_file_id", "corpus_file_id"),
        Index("idx_documents_subject_id", "subject_id"),
        Index("idx_documents_exam_year", "exam_year"),
        Index("idx_documents_doc_type", "doc_type"),
        Index("idx_documents_status", "status"),
        {"comment": "正规化文档主表"}
    )


class DocumentPage(Base):
    """文档页表"""
    __tablename__ = "document_pages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="页ID")
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, comment="文档ID"
    )
    page_no: Mapped[int] = mapped_column(nullable=False, comment="页码，从1开始")
    page_image_path: Mapped[Optional[str]] = mapped_column(String(500), comment="页截图路径")
    width: Mapped[Optional[int]] = mapped_column(comment="宽度")
    height: Mapped[Optional[int]] = mapped_column(comment="高度")
    rotation: Mapped[Optional[int]] = mapped_column(comment="旋转角度")
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, comment="页级OCR文本")
    layout_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="布局信息")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("document_id", "page_no", name="uk_document_pages_doc_page"),
        Index("idx_document_pages_document_id", "document_id"),
        {"comment": "文档页表"}
    )


class DocumentBlock(Base):
    """文档块表"""
    __tablename__ = "document_blocks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="块ID")
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, comment="文档ID"
    )
    page_id: Mapped[Optional[str]] = mapped_column(String(32), comment="页ID")
    page_no: Mapped[int] = mapped_column(nullable=False, comment="页码")
    block_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="块类型")
    order_no: Mapped[int] = mapped_column(nullable=False, comment="页内顺序")
    bbox: Mapped[Optional[dict]] = mapped_column(JSON, comment="坐标")
    content_text: Mapped[Optional[str]] = mapped_column(Text, comment="纯文本")
    content_md: Mapped[Optional[str]] = mapped_column(Text, comment="Markdown表示")
    content_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="结构化表示")
    latex: Mapped[Optional[str]] = mapped_column(Text, comment="公式LaTeX")
    html_table: Mapped[Optional[str]] = mapped_column(Text, comment="表格HTML")
    asset_id: Mapped[Optional[str]] = mapped_column(String(32), comment="关联资产ID")
    confidence: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 4), comment="识别置信度")
    review_status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected"),
        default="pending", comment="审核状态"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_document_blocks_document_page", "document_id", "page_no"),
        Index("idx_document_blocks_type", "block_type"),
        Index("idx_document_blocks_review_status", "review_status"),
        {"comment": "文档块表"}
    )


class DocumentAsset(Base):
    """文档图表公式资产表"""
    __tablename__ = "document_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="资产ID")
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, comment="文档ID"
    )
    page_no: Mapped[int] = mapped_column(nullable=False, comment="页码")
    asset_type: Mapped[str] = mapped_column(
        Enum("figure", "table", "formula", "page_crop", "other"),
        nullable=False, comment="资产类型"
    )
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="资产文件路径")
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500), comment="缩略图路径")
    bbox: Mapped[Optional[dict]] = mapped_column(JSON, comment="坐标")
    caption_text: Mapped[Optional[str]] = mapped_column(Text, comment="图表标题")
    ocr_text: Mapped[Optional[str]] = mapped_column(Text, comment="图内OCR结果")
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="扩展元数据")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_document_assets_document_page", "document_id", "page_no"),
        Index("idx_document_assets_type", "asset_type"),
        {"comment": "文档图表公式资产表"}
    )


# ========== 多模态语料库扩展模型 ==========


class ExamOutline(Base):
    """考试大纲元信息表"""
    __tablename__ = "exam_outlines"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="大纲ID")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="大纲名称，如：2025年408考研大纲")
    year: Mapped[int] = mapped_column(nullable=False, comment="考试年份")
    version: Mapped[str] = mapped_column(String(20), default="v1.0", comment="版本号")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="大纲说明")
    release_date: Mapped[Optional[datetime]] = mapped_column(Date, comment="发布日期")
    effective_date: Mapped[Optional[datetime]] = mapped_column(Date, comment="生效日期")
    status: Mapped[str] = mapped_column(
        Enum("draft", "active", "archived"),
        default="draft",
        comment="状态：draft=草稿, active=启用, archived=归档"
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否默认大纲")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # relationships
    chapters: Mapped[List["CanonicalChapter"]] = relationship(back_populates="outline")

    __table_args__ = (
        Index("idx_outline_year", "year"),
        Index("idx_outline_status", "status"),
        Index("idx_outline_default", "is_default"),
        UniqueConstraint("year", "version", name="uk_outline_year_version"),
        {"comment": "考试大纲元信息表"}
    )


class ExamOutlineSubject(Base):
    """大纲-科目关联表：存某门课在该版大纲下的考察目标 + 复习指导生成状态"""
    __tablename__ = "exam_outline_subjects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="关联ID")
    outline_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("exam_outlines.id", ondelete="CASCADE"),
        nullable=False, comment="所属大纲ID"
    )
    subject_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False, comment="所属学科ID"
    )
    exam_objective: Mapped[Optional[str]] = mapped_column(Text, comment="该门课考察目标原文（概括性，三四句）")
    guidance_status: Mapped[str] = mapped_column(
        Enum("pending", "generating", "done", "failed"),
        default="pending",
        comment="复习指导批量生成状态"
    )
    chapter_count: Mapped[int] = mapped_column(default=0, comment="该门课章节数")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_outline_subject_outline", "outline_id"),
        Index("idx_outline_subject_subject", "subject_id"),
        UniqueConstraint("outline_id", "subject_id", name="uk_outline_subject"),
        {"comment": "大纲-科目关联表（考察目标）"}
    )


class OutlineIngestionRun(Base):
    """大纲入库任务执行记录"""
    __tablename__ = "outline_ingestion_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="任务ID")
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, comment="源文档ID"
    )
    outline_id: Mapped[Optional[str]] = mapped_column(String(32), comment="生成的大纲ID（成功后填充）")
    outline_name: Mapped[Optional[str]] = mapped_column(String(200), comment="大纲名称")
    year: Mapped[Optional[int]] = mapped_column(Integer, comment="年份")
    version: Mapped[Optional[str]] = mapped_column(String(20), comment="版本")

    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "done", "partial", "failed"),
        default="pending",
        nullable=False,
        comment="任务状态：partial=部分成功"
    )

    total_subjects: Mapped[int] = mapped_column(default=0, comment="总科目数")
    processed_subjects: Mapped[int] = mapped_column(default=0, comment="已处理科目数")
    successful_subjects: Mapped[int] = mapped_column(default=0, comment="成功处理科目数")
    current_subject_name: Mapped[Optional[str]] = mapped_column(String(100), comment="当前处理科目")

    created_chapters: Mapped[int] = mapped_column(default=0, comment="总共创建章节数")
    updated_chapters: Mapped[int] = mapped_column(default=0, comment="总共更新章节数")

    error_detail: Mapped[Optional[str]] = mapped_column(Text, comment="错误详情")
    result_summary: Mapped[Optional[dict]] = mapped_column(JSON, comment="各科目处理结果摘要")

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_outline_run_document", "document_id"),
        Index("idx_outline_run_status", "status"),
        Index("idx_outline_run_created", "created_at"),
        {"comment": "大纲入库任务执行记录"}
    )


class CanonicalChapter(Base):
    """标准章节表 - 学科的标准章节体系（考试大纲章节）"""
    __tablename__ = "canonical_chapters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="章节ID")
    outline_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("exam_outlines.id", ondelete="CASCADE"),
        comment="所属大纲ID"
    )
    subject_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False, comment="所属学科ID"
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("canonical_chapters.id", ondelete="CASCADE"),
        comment="父章节ID，顶级章节为NULL"
    )
    level: Mapped[int] = mapped_column(default=1, comment="层级：1=一级章节，2=二级章节，3=三级章节")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="标准章节名称")
    code: Mapped[Optional[str]] = mapped_column(String(50), comment="章节编码，如 CH1.2")
    outline_code: Mapped[Optional[str]] = mapped_column(String(50), comment="大纲中的编号，如：1.1.1、一、(一)")
    aliases: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="别名列表")
    description: Mapped[Optional[str]] = mapped_column(Text, comment="章节描述（大纲原文考点）")
    enhanced_description: Mapped[Optional[str]] = mapped_column(Text, comment="LLM 增强描述（2-3句，含考法/易混点/核心内容，用于向量检索）")
    keywords: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="关键词标签（别名、英文名、相关术语，用于精确匹配）")
    exam_guidance: Mapped[Optional[str]] = mapped_column(Text, comment="LLM 生成的复习指导（重点内容/复习方向）")
    sort_order: Mapped[int] = mapped_column(default=0, comment="排序序号")
    status: Mapped[str] = mapped_column(
        Enum("active", "inactive"),
        default="active", comment="状态"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # relationships
    outline: Mapped[Optional["ExamOutline"]] = relationship(back_populates="chapters")
    subject: Mapped["Subject"] = relationship()
    parent: Mapped[Optional["CanonicalChapter"]] = relationship(remote_side="CanonicalChapter.id")
    children: Mapped[List["CanonicalChapter"]] = relationship(back_populates="parent")

    __table_args__ = (
        Index("idx_canonical_chapters_outline", "outline_id"),
        Index("idx_canonical_chapters_subject", "subject_id"),
        Index("idx_canonical_chapters_parent", "parent_id"),
        Index("idx_canonical_chapters_level", "level"),
        {"comment": "标准章节表（考试大纲章节）"}
    )


class DocumentSection(Base):
    """文档原生标题树 - 从文档解析出的章节结构"""
    __tablename__ = "document_sections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="section ID")
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, comment="文档ID"
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(32), ForeignKey("document_sections.id", ondelete="CASCADE"),
        comment="父section ID"
    )
    level: Mapped[int] = mapped_column(nullable=False, comment="层级深度")
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="原生标题文本")
    section_path: Mapped[str] = mapped_column(String(1000), nullable=False, comment="完整路径，如 第1章>1.1>1.1.1")
    page_start: Mapped[Optional[int]] = mapped_column(comment="起始页码")
    page_end: Mapped[Optional[int]] = mapped_column(comment="结束页码")
    block_start_id: Mapped[Optional[str]] = mapped_column(String(32), comment="起始block ID")
    block_end_id: Mapped[Optional[str]] = mapped_column(String(32), comment="结束block ID")
    confidence: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 4), comment="识别置信度")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # relationships
    document: Mapped["Document"] = relationship()
    parent: Mapped[Optional["DocumentSection"]] = relationship(remote_side="DocumentSection.id")
    children: Mapped[List["DocumentSection"]] = relationship(back_populates="parent")
    mappings: Mapped[List["DocumentSectionMapping"]] = relationship(back_populates="section")

    __table_args__ = (
        Index("idx_document_sections_document", "document_id"),
        Index("idx_document_sections_parent", "parent_id"),
        Index("idx_document_sections_level", "level"),
        {"comment": "文档原生标题树"}
    )


class DocumentSectionMapping(Base):
    """文档section到标准章节的映射"""
    __tablename__ = "document_section_mappings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="映射ID")
    document_section_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("document_sections.id", ondelete="CASCADE"),
        nullable=False, comment="文档section ID"
    )
    canonical_chapter_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("canonical_chapters.id", ondelete="CASCADE"),
        nullable=False, comment="标准章节ID"
    )
    mapping_type: Mapped[str] = mapped_column(
        Enum("exact", "partial", "related"),
        default="exact", comment="映射类型"
    )
    confidence: Mapped[float] = mapped_column(DECIMAL(5, 4), nullable=False, comment="映射置信度")
    review_status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected"),
        default="pending", comment="审核状态"
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, comment="审核备注")
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(32), comment="审核人")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="审核时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # relationships
    section: Mapped["DocumentSection"] = relationship(back_populates="mappings")
    canonical_chapter: Mapped["CanonicalChapter"] = relationship()

    __table_args__ = (
        Index("idx_dsm_section", "document_section_id"),
        Index("idx_dsm_chapter", "canonical_chapter_id"),
        Index("idx_dsm_review_status", "review_status"),
        Index("idx_dsm_confidence", "confidence"),
        {"comment": "文档section到标准章节的映射"}
    )


class KnowledgePointChapterLink(Base):
    """知识点与章节关联表"""
    __tablename__ = "knowledge_point_chapter_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_point_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False, comment="知识点ID"
    )
    canonical_chapter_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("canonical_chapters.id", ondelete="CASCADE"),
        nullable=False, comment="标准章节ID"
    )
    is_primary: Mapped[bool] = mapped_column(default=False, comment="是否主章节")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # relationships
    knowledge_point: Mapped["KnowledgePoint"] = relationship(back_populates="chapter_links")
    canonical_chapter: Mapped["CanonicalChapter"] = relationship()

    __table_args__ = (
        UniqueConstraint("knowledge_point_id", "canonical_chapter_id", name="uk_kp_chapter_link"),
        Index("idx_kpcl_knowledge_point", "knowledge_point_id"),
        Index("idx_kpcl_chapter", "canonical_chapter_id"),
        {"comment": "知识点与章节关联表"}
    )


class QuestionChapterLink(Base):
    """题目与章节关联表"""
    __tablename__ = "question_chapter_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False, comment="题目ID"
    )
    canonical_chapter_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("canonical_chapters.id", ondelete="CASCADE"),
        nullable=False, comment="标准章节ID"
    )
    is_primary: Mapped[bool] = mapped_column(default=False, comment="是否主章节")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # relationships
    question: Mapped["Question"] = relationship(back_populates="chapter_links")
    canonical_chapter: Mapped["CanonicalChapter"] = relationship()

    __table_args__ = (
        UniqueConstraint("question_id", "canonical_chapter_id", name="uk_q_chapter_link"),
        Index("idx_qcl_question", "question_id"),
        Index("idx_qcl_chapter", "canonical_chapter_id"),
        {"comment": "题目与章节关联表"}
    )


class QuestionKnowledgeLink(Base):
    """题目与知识点关联表 - 支撑「查题反查知识点」双向反查"""
    __tablename__ = "question_knowledge_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="关联ID")
    question_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False, comment="题目ID"
    )
    knowledge_point_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False, comment="知识点ID"
    )
    relevance: Mapped[float] = mapped_column(
        DECIMAL(5, 4), default=0, comment="关联强度 0-1"
    )
    source: Mapped[str] = mapped_column(
        Enum("llm", "vector", "rule", "manual"),
        default="llm", comment="关联来源：llm考点标识/vector向量召回/rule规则/manual人工"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("question_id", "knowledge_point_id", name="uk_q_kp_link"),
        Index("idx_qkl_question", "question_id"),
        Index("idx_qkl_kp", "knowledge_point_id"),
        {"comment": "题目与知识点关联表"}
    )


class EntitySourceLink(Base):
    """实体来源引用表 - 记录知识点/题目来自哪个文档的哪个位置"""
    __tablename__ = "entity_source_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(
        Enum("knowledge_point", "question"),
        nullable=False, comment="实体类型"
    )
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="实体ID")
    document_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, comment="来源文档ID"
    )
    page_start: Mapped[Optional[int]] = mapped_column(comment="起始页码")
    page_end: Mapped[Optional[int]] = mapped_column(comment="结束页码")
    block_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="来源block ID列表")
    excerpt_text: Mapped[Optional[str]] = mapped_column(Text, comment="来源摘录文本")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_esl_entity", "entity_type", "entity_id"),
        Index("idx_esl_document", "document_id"),
        {"comment": "实体来源引用表"}
    )


class KnowledgeRelation(Base):
    """知识点关系表"""
    __tablename__ = "knowledge_relations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="关系ID")
    source_knowledge_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False, comment="源知识点ID"
    )
    target_knowledge_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("knowledge_points.id", ondelete="CASCADE"),
        nullable=False, comment="目标知识点ID"
    )
    relation_type: Mapped[str] = mapped_column(
        Enum("prerequisite", "contrast_with", "common_confusion",
             "contains", "part_of", "used_in", "similar_to"),
        nullable=False, comment="关系类型"
    )
    directionality: Mapped[str] = mapped_column(
        Enum("directed", "undirected"),
        default="directed", comment="方向性"
    )
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, comment="证据文本")
    evidence_page: Mapped[Optional[int]] = mapped_column(comment="证据页码")
    confidence: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 4), comment="置信度")
    source_type: Mapped[str] = mapped_column(
        Enum("rule", "llm", "manual", "term_similarity"),
        default="llm", comment="来源类型"
    )
    review_status: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected"),
        default="pending", comment="审核状态"
    )
    review_notes: Mapped[Optional[str]] = mapped_column(Text, comment="审核备注")
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(32), comment="审核人")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, comment="审核时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # relationships
    source_knowledge: Mapped["KnowledgePoint"] = relationship(foreign_keys=[source_knowledge_id])
    target_knowledge: Mapped["KnowledgePoint"] = relationship(foreign_keys=[target_knowledge_id])

    __table_args__ = (
        Index("idx_kr_source", "source_knowledge_id"),
        Index("idx_kr_target", "target_knowledge_id"),
        Index("idx_kr_type", "relation_type"),
        Index("idx_kr_review_status", "review_status"),
        {"comment": "知识点关系表"}
    )


class RetrievalSegment(Base):
    """检索单元表 - 用于向量检索的段落"""
    __tablename__ = "retrieval_segments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="segment ID")
    entity_type: Mapped[str] = mapped_column(
        Enum("knowledge_point", "question"),
        nullable=False, comment="实体类型"
    )
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False, comment="实体ID")
    document_id: Mapped[Optional[str]] = mapped_column(String(32), comment="来源文档ID")
    segment_type: Mapped[str] = mapped_column(
        Enum("content", "title", "explanation", "option"),
        default="content", comment="段落类型"
    )
    content_text: Mapped[str] = mapped_column(Text, nullable=False, comment="段落文本")
    content_md: Mapped[Optional[str]] = mapped_column(Text, comment="Markdown格式")
    sparse_text: Mapped[Optional[str]] = mapped_column(Text, comment="稀疏检索文本")
    context_text: Mapped[Optional[str]] = mapped_column(Text, comment="上下文增强文本")
    page_no: Mapped[Optional[int]] = mapped_column(comment="页码")
    subject_id: Mapped[Optional[str]] = mapped_column(String(32), comment="学科ID")
    chapter_ids: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="章节ID列表")
    topic_terms: Mapped[Optional[List[str]]] = mapped_column(JSON, comment="主题术语")
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="扩展元数据")
    qdrant_point_id: Mapped[Optional[str]] = mapped_column(String(100), comment="Qdrant point ID")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_rs_entity", "entity_type", "entity_id"),
        Index("idx_rs_document", "document_id"),
        Index("idx_rs_subject", "subject_id"),
        Index("idx_rs_segment_type", "segment_type"),
        {"comment": "检索单元表"}
    )



# ===== 监控相关表 =====


class LLMCallLog(Base):
    """LLM 调用日志：记录每一次大模型调用的请求/响应/耗时/Token/成本"""
    __tablename__ = "llm_call_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), default="openai_compatible", comment="服务商")
    base_url: Mapped[Optional[str]] = mapped_column(String(255), comment="API base url")
    model: Mapped[str] = mapped_column(String(100), nullable=False, comment="模型名")
    called_by: Mapped[Optional[str]] = mapped_column(String(100), comment="调用方标识，如 chat_service / pdf_structure")
    purpose: Mapped[Optional[str]] = mapped_column(String(100), comment="调用用途说明")

    request_messages: Mapped[Optional[dict]] = mapped_column(JSON, comment="请求 messages（截断后）")
    request_params: Mapped[Optional[dict]] = mapped_column(JSON, comment="temperature/max_tokens 等参数")
    response_text: Mapped[Optional[str]] = mapped_column(Text, comment="响应正文（截断）")
    response_full: Mapped[Optional[dict]] = mapped_column(JSON, comment="完整响应 JSON（截断）")

    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(DECIMAL(10, 6), default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(
        Enum("success", "error", "timeout"),
        default="success", comment="调用状态"
    )
    error_msg: Mapped[Optional[str]] = mapped_column(Text, comment="错误信息")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_llm_calls_created_at", "created_at"),
        Index("idx_llm_calls_status", "status"),
        Index("idx_llm_calls_model", "model"),
        Index("idx_llm_calls_called_by", "called_by"),
        {"comment": "LLM 调用日志"}
    )


class ServiceLog(Base):
    """后端服务日志：structlog 输出会被 sink 到这里供查询"""
    __tablename__ = "service_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level: Mapped[str] = mapped_column(String(16), default="INFO", comment="日志级别")
    logger_name: Mapped[Optional[str]] = mapped_column(String(120), comment="logger 名称（模块）")
    event: Mapped[Optional[str]] = mapped_column(String(255), comment="事件名/简短描述")
    message: Mapped[Optional[str]] = mapped_column(Text, comment="完整消息")
    request_id: Mapped[Optional[str]] = mapped_column(String(64), comment="关联请求 ID")
    context: Mapped[Optional[dict]] = mapped_column(JSON, comment="结构化上下文")
    traceback: Mapped[Optional[str]] = mapped_column(Text, comment="异常堆栈（仅 ERROR）")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_service_logs_level_time", "level", "created_at"),
        Index("idx_service_logs_logger", "logger_name"),
        Index("idx_service_logs_request", "request_id"),
        {"comment": "后端服务日志"}
    )


class SystemMetric(Base):
    """系统资源采样：psutil 后台 task 每 10 秒一条"""
    __tablename__ = "system_metrics"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    cpu_percent: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)
    mem_used_mb: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)
    mem_total_mb: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)
    mem_percent: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)
    disk_used_gb: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)
    disk_total_gb: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)
    disk_percent: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)
    process_rss_mb: Mapped[float] = mapped_column(DECIMAL(10, 2), default=0)
    process_cpu_percent: Mapped[float] = mapped_column(DECIMAL(5, 2), default=0)
    sampled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        {"comment": "系统资源采样"}
    )


class ApiCallStat(Base):
    """API 调用统计：按 (endpoint, method, hour_bucket) 聚合"""
    __tablename__ = "api_call_stats"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False, comment="路由路径")
    method: Mapped[str] = mapped_column(String(10), nullable=False, comment="HTTP 方法")
    hour_bucket: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="小时聚合桶")
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    total_latency_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    max_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    p95_sample_ms: Mapped[int] = mapped_column(Integer, default=0, comment="近似P95（reservoir 采样）")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        UniqueConstraint("endpoint", "method", "hour_bucket", name="uq_api_stats_bucket"),
        Index("idx_api_stats_hour", "hour_bucket"),
        {"comment": "API 调用聚合统计"}
    )


class ChatSession(Base):
    """对话会话：记录每次对话上下文，独立于 Redis 缓存。"""
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="session_id（前端透传）")
    user_id: Mapped[Optional[str]] = mapped_column(String(64), comment="登录用户 ID（mock 时为 admin）")
    title: Mapped[Optional[str]] = mapped_column(String(255), comment="会话标题（首条消息截断）")
    first_message: Mapped[Optional[str]] = mapped_column(Text, comment="首条用户消息预览")
    last_message: Mapped[Optional[str]] = mapped_column(Text, comment="最后一条助手消息预览")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    has_knowledge: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否走过 RAG")
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, comment="扩展元数据")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        Index("idx_chat_sessions_user", "user_id"),
        Index("idx_chat_sessions_updated", "updated_at"),
        {"comment": "对话会话"}
    )


class ChatMessageRecord(Base):
    """对话消息：每条 user/assistant 消息一行"""
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        Enum("user", "assistant", "system"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[Optional[list]] = mapped_column(JSON, comment="引用来源（知识点/题目 ID 列表）")
    llm_call_id: Mapped[Optional[str]] = mapped_column(String(32), comment="关联 llm_call_logs.id")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_chat_messages_session", "session_id", "created_at"),
        {"comment": "对话消息"}
    )


class EntityAssetLink(Base):
    """实体（知识点 / 题目）与文档资产（figure / table / formula）的多对多关联"""
    __tablename__ = "entity_asset_links"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_type: Mapped[str] = mapped_column(
        Enum("knowledge_point", "question"),
        nullable=False
    )
    entity_id: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("document_assets.id", ondelete="CASCADE"),
        nullable=False
    )
    relation: Mapped[str] = mapped_column(
        Enum("inline", "reference", "related"),
        default="inline",
        comment="inline=正文嵌入；reference=引用；related=相关"
    )
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "asset_id", name="uq_entity_asset"),
        Index("idx_entity_asset_entity", "entity_type", "entity_id"),
        Index("idx_entity_asset_asset", "asset_id"),
        {"comment": "实体-资产关联表"}
    )
