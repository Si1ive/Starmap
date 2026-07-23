"""Agent thread 对话 turn 与时间线投影服务。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger

from .events import event_store
from .models import (
    AgentApproval,
    AgentArtifact,
    AgentInput,
    AgentMessage,
    AgentRun,
    AgentStep,
    AgentThread,
    AgentThreadItem,
)
from .outbox import outbox_store
from .state_machine import RunStatus
from .thread_events import thread_event_store

logger = get_logger(__name__)


WORKFLOW_TITLES = {
    "conversation": "处理请求",
    "explain": "整理讲解",
    "validate": "生成专项练习",
    "grade": "分析作答",
    "plan": "调整学习计划",
}

STEP_LABELS = {
    "intent": "理解需求",
    "route": "选择处理方式",
    "load_scope": "确认学习范围",
    "evidence_loop": "查找相关资料",
    "evidence_gate": "检查资料质量",
    "generate_explanation": "组织讲解",
    "citation_gate": "检查引用",
    "load_learning_evidence": "整理学习记录",
    "question_discovery": "查找候选题",
    "question_gate": "检查题目质量",
    "composition_gate": "调整题目组合",
    "create_draft": "生成练习草稿",
    "load_attempt_snapshot": "读取作答记录",
    "objective_grade": "检查客观题",
    "rubric_gate": "核对评分标准",
    "generate_feedback": "生成反馈",
    "feedback_gate": "检查反馈质量",
    "aggregate_learning_evidence": "整理学习情况",
    "planning_precondition_gate": "检查调整条件",
    "propose_plan_delta": "生成调整方案",
    "plan_quality_gate": "检查方案质量",
    "create_approval": "准备确认内容",
    "wait_for_approval": "等待你的确认",
    "apply_plan_change": "应用计划调整",
    "render_artifact": "整理结果",
    "render_plan_result": "整理计划结果",
    "completed": "完成",
}

STATUS_SUMMARIES = {
    "queued": "已加入执行队列",
    "running": "正在执行",
    "waiting_for_user": "需要你补充信息",
    "waiting_for_approval": "等待你的确认",
    "completed": "已完成",
    "failed": "执行未完成",
}


class ThreadNotFoundError(Exception):
    """thread 不存在或不属于当前用户。"""


class TurnConflictError(Exception):
    """client_message_id 已被另一条消息使用。"""


@dataclass(frozen=True)
class TurnCreation:
    message: AgentMessage
    run: AgentRun
    timeline_cursor: int


@dataclass(frozen=True)
class TimelinePage:
    thread: AgentThread
    items: list[dict[str, Any]]
    previous_cursor: Optional[int]
    latest_cursor: int
    has_more: bool


class AgentTimelineService:
    """创建用户 turn，并返回前端可直接渲染的 thread 时间线。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_turn(
        self,
        *,
        user_id: str,
        thread_id: str,
        content: str,
        client_message_id: str,
        attachments: list[dict[str, Any]],
        context_refs: list[dict[str, Any]],
        preferred_action: Optional[str],
    ) -> TurnCreation:
        """原子创建用户消息、根 run、时间线项和 outbox 任务。"""
        thread_result = await self.db.execute(
            select(AgentThread)
            .where(AgentThread.id == thread_id, AgentThread.user_id == user_id)
            .with_for_update()
        )
        thread = thread_result.scalar_one_or_none()
        if not thread:
            raise ThreadNotFoundError(thread_id)

        existing_result = await self.db.execute(
            select(AgentMessage).where(
                AgentMessage.user_id == user_id,
                AgentMessage.client_message_id == client_message_id,
            )
        )
        existing_message = existing_result.scalar_one_or_none()
        if existing_message:
            if (
                existing_message.thread_id != thread_id
                or existing_message.content_text != content
            ):
                raise TurnConflictError(client_message_id)
            run_result = await self.db.execute(
                select(AgentRun).where(
                    AgentRun.trigger_message_id == existing_message.id,
                    AgentRun.parent_run_id.is_(None),
                )
            )
            existing_run = run_result.scalar_one_or_none()
            if not existing_run:
                raise TurnConflictError(client_message_id)
            return TurnCreation(
                message=existing_message,
                run=existing_run,
                timeline_cursor=thread.last_item_sequence,
            )

        now = datetime.utcnow()
        message = AgentMessage(
            id=f"msg_{uuid.uuid4().hex[:20]}",
            thread_id=thread.id,
            user_id=user_id,
            role="user",
            status="completed",
            content_text=content,
            content_blocks_json=self._build_content_blocks(
                content=content,
                attachments=attachments,
                context_refs=context_refs,
            ),
            client_message_id=client_message_id,
            completed_at=now,
        )
        self.db.add(message)
        await self.db.flush()

        run = AgentRun(
            id=f"run_{uuid.uuid4().hex[:20]}",
            thread_id=thread.id,
            user_id=user_id,
            workflow_name="conversation",
            workflow_key="conversation",
            workflow_version="v1",
            status=RunStatus.QUEUED.value,
            input_message=content,
            trigger_message_id=message.id,
            presentation="workflow",
            public_title=WORKFLOW_TITLES["conversation"],
            public_summary=STATUS_SUMMARIES[RunStatus.QUEUED.value],
            metadata_json={
                "preferred_action": preferred_action,
                "attachments": attachments,
                "context_refs": context_refs,
            },
        )
        self.db.add(run)
        await self.db.flush()
        run.root_run_id = run.id
        message.run_id = run.id

        message_sequence = thread.last_item_sequence + 1
        workflow_sequence = message_sequence + 1
        self.db.add_all(
            [
                AgentThreadItem(
                    id=f"item_{uuid.uuid4().hex[:20]}",
                    thread_id=thread.id,
                    sequence=message_sequence,
                    item_type="message",
                    ref_id=message.id,
                    run_id=run.id,
                ),
                AgentThreadItem(
                    id=f"item_{uuid.uuid4().hex[:20]}",
                    thread_id=thread.id,
                    sequence=workflow_sequence,
                    item_type="workflow",
                    ref_id=run.id,
                    run_id=run.id,
                ),
            ]
        )
        thread.last_item_sequence = workflow_sequence
        thread.updated_at = now
        if thread.title == "新会话":
            thread.title = self._derive_thread_title(content)

        await thread_event_store.append_at(
            self.db,
            thread.id,
            message_sequence,
            "timeline.item.created",
            {
                "item_type": "message",
                "ref_id": message.id,
                "run_id": run.id,
            },
        )
        await thread_event_store.append_at(
            self.db,
            thread.id,
            workflow_sequence,
            "timeline.item.created",
            {
                "item_type": "workflow",
                "ref_id": run.id,
                "root_run_id": run.id,
            },
        )

        await event_store.append(
            self.db,
            run.id,
            "run.created",
            {
                "run_id": run.id,
                "thread_id": thread.id,
                "workflow": "conversation@v1",
                "trigger_message_id": message.id,
                "root_run_id": run.id,
            },
        )
        await outbox_store.enqueue(self.db, run.id)
        await self.db.flush()

        logger.info(
            "对话 turn 创建",
            thread_id=thread.id,
            message_id=message.id,
            run_id=run.id,
            sequence=workflow_sequence,
        )
        return TurnCreation(
            message=message,
            run=run,
            timeline_cursor=thread.last_item_sequence,
        )

    async def get_timeline(
        self,
        *,
        user_id: str,
        thread_id: str,
        before: Optional[int],
        limit: int,
    ) -> TimelinePage:
        """按 thread sequence 倒序分页读取，再以正序返回可渲染投影。"""
        thread_result = await self.db.execute(
            select(AgentThread).where(
                AgentThread.id == thread_id,
                AgentThread.user_id == user_id,
            )
        )
        thread = thread_result.scalar_one_or_none()
        if not thread:
            raise ThreadNotFoundError(thread_id)

        query = select(AgentThreadItem).where(
            AgentThreadItem.thread_id == thread_id,
            AgentThreadItem.visibility == "visible",
        )
        if before is not None:
            query = query.where(AgentThreadItem.sequence < before)
        item_result = await self.db.execute(
            query.order_by(desc(AgentThreadItem.sequence)).limit(limit + 1)
        )
        descending_items = list(item_result.scalars().all())
        has_more = len(descending_items) > limit
        page_items = list(reversed(descending_items[:limit]))

        projected = await self._project_items(page_items)
        previous_cursor = page_items[0].sequence if has_more and page_items else None
        return TimelinePage(
            thread=thread,
            items=projected,
            previous_cursor=previous_cursor,
            latest_cursor=thread.last_item_sequence,
            has_more=has_more,
        )

    async def _project_items(
        self,
        items: list[AgentThreadItem],
    ) -> list[dict[str, Any]]:
        message_ids = [item.ref_id for item in items if item.item_type == "message"]
        root_run_ids = [item.ref_id for item in items if item.item_type == "workflow"]

        messages: dict[str, AgentMessage] = {}
        if message_ids:
            result = await self.db.execute(
                select(AgentMessage).where(AgentMessage.id.in_(message_ids))
            )
            messages = {message.id: message for message in result.scalars().all()}

        workflow_views = await self._build_workflow_views(root_run_ids)
        projected: list[dict[str, Any]] = []
        for item in items:
            base: dict[str, Any] = {
                "id": item.id,
                "sequence": item.sequence,
                "type": item.item_type,
                "message": None,
                "workflow": None,
                "notice": None,
                "created_at": item.created_at,
            }
            if item.item_type == "message":
                message = messages.get(item.ref_id)
                if message:
                    base["message"] = self.message_view(message)
            elif item.item_type == "workflow":
                base["workflow"] = workflow_views.get(item.ref_id)
            else:
                base["notice"] = {"id": item.ref_id}
            projected.append(base)
        return projected

    async def _build_workflow_views(
        self,
        root_run_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not root_run_ids:
            return {}

        run_result = await self.db.execute(
            select(AgentRun).where(
                or_(
                    AgentRun.id.in_(root_run_ids),
                    AgentRun.root_run_id.in_(root_run_ids),
                )
            )
        )
        runs = list(run_result.scalars().all())
        run_ids = [run.id for run in runs]

        steps = await self._load_grouped(AgentStep, AgentStep.run_id, run_ids)
        inputs = await self._load_grouped(AgentInput, AgentInput.run_id, run_ids)
        approvals = await self._load_grouped(
            AgentApproval, AgentApproval.run_id, run_ids
        )
        artifacts = await self._load_grouped(
            AgentArtifact, AgentArtifact.run_id, run_ids
        )

        grouped_runs: dict[str, list[AgentRun]] = {
            root_id: [] for root_id in root_run_ids
        }
        for run in runs:
            root_id = run.root_run_id or run.id
            if root_id in grouped_runs:
                grouped_runs[root_id].append(run)

        views: dict[str, dict[str, Any]] = {}
        for root_id, group in grouped_runs.items():
            if not group:
                continue
            group.sort(key=lambda run: (run.created_at, run.id))
            root = next((run for run in group if run.id == root_id), group[0])
            effective = self._effective_run(group)
            group_run_ids = {run.id for run in group}
            group_steps = [
                step for run_id in group_run_ids for step in steps.get(run_id, [])
            ]
            group_steps.sort(key=lambda step: (step.created_at, step.id))
            group_inputs = [
                item for run_id in group_run_ids for item in inputs.get(run_id, [])
            ]
            group_approvals = [
                item for run_id in group_run_ids for item in approvals.get(run_id, [])
            ]
            group_artifacts = [
                item for run_id in group_run_ids for item in artifacts.get(run_id, [])
            ]

            pending_input = next(
                (item for item in reversed(group_inputs) if item.status == "pending"),
                None,
            )
            pending_approval = next(
                (
                    item
                    for item in reversed(group_approvals)
                    if item.status == "pending"
                ),
                None,
            )
            title_source = (
                effective if effective.workflow_key != "conversation" else root
            )
            views[root_id] = {
                "root_run_id": root_id,
                "status": effective.status,
                "title": title_source.public_title
                or WORKFLOW_TITLES.get(
                    title_source.workflow_key or title_source.workflow_name, "执行任务"
                ),
                "summary": effective.public_summary
                or STATUS_SUMMARIES.get(effective.status),
                "current_step": self._step_label(effective.current_public_step),
                "progress": {
                    "completed": sum(
                        step.status in {"completed", "skipped"} for step in group_steps
                    ),
                    "total": len(group_steps),
                },
                "steps": [self._step_view(step) for step in group_steps],
                "pending_input": (
                    self._input_view(pending_input) if pending_input else None
                ),
                "pending_approval": (
                    self._approval_view(pending_approval) if pending_approval else None
                ),
                "artifacts": [
                    self._artifact_view(artifact) for artifact in group_artifacts
                ],
                "created_at": root.created_at,
                "updated_at": max(run.updated_at for run in group),
            }
        return views

    async def _load_grouped(
        self, model, run_id_column, run_ids: list[str]
    ) -> dict[str, list[Any]]:
        if not run_ids:
            return {}
        result = await self.db.execute(
            select(model).where(run_id_column.in_(run_ids)).order_by(model.created_at)
        )
        grouped: dict[str, list[Any]] = {}
        for record in result.scalars().all():
            grouped.setdefault(record.run_id, []).append(record)
        return grouped

    @staticmethod
    def message_view(message: AgentMessage) -> dict[str, Any]:
        return {
            "id": message.id,
            "role": message.role,
            "status": message.status,
            "content": message.content_text,
            "content_blocks": message.content_blocks_json or [],
            "error_code": message.error_code,
            "created_at": message.created_at,
            "updated_at": message.updated_at,
            "completed_at": message.completed_at,
        }

    @staticmethod
    def _build_content_blocks(
        *,
        content: str,
        attachments: list[dict[str, Any]],
        context_refs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [{"type": "text", "text": content}]
        if attachments:
            blocks.append({"type": "attachments", "items": attachments})
        if context_refs:
            blocks.append({"type": "context_refs", "items": context_refs})
        return blocks

    @staticmethod
    def _derive_thread_title(content: str) -> str:
        compact = " ".join(content.split())
        return compact[:30] or "新会话"

    @staticmethod
    def _effective_run(runs: list[AgentRun]) -> AgentRun:
        active_statuses = {
            "waiting_for_user",
            "waiting_for_approval",
            "running",
            "queued",
        }
        for run in reversed(runs):
            if run.status in active_statuses:
                return run
        for run in reversed(runs):
            if run.status == "failed":
                return run
        return runs[-1]

    @staticmethod
    def _step_label(node_name: Optional[str]) -> Optional[str]:
        if not node_name:
            return None
        return STEP_LABELS.get(node_name, "执行步骤")

    @classmethod
    def _step_view(cls, step: AgentStep) -> dict[str, Any]:
        return {
            "id": step.id,
            "label": cls._step_label(step.node_name) or "执行步骤",
            "status": step.status,
            "started_at": step.started_at,
            "completed_at": step.completed_at,
        }

    @staticmethod
    def _input_view(agent_input: AgentInput) -> dict[str, Any]:
        return {
            "id": agent_input.id,
            "run_id": agent_input.run_id,
            "input_key": agent_input.input_key,
            "status": agent_input.status,
            "question": agent_input.prompt_ref or "请补充所需信息",
            "schema": {"version": agent_input.input_schema_version or "v1"},
            "expires_at": agent_input.expires_at,
        }

    @staticmethod
    def _approval_view(approval: AgentApproval) -> dict[str, Any]:
        return {
            "id": approval.id,
            "run_id": approval.run_id,
            "action_key": approval.action_key,
            "status": approval.status,
            "change": AgentTimelineService._safe_json(approval.diff_ref),
            "expires_at": approval.expires_at,
        }

    @staticmethod
    def _artifact_view(artifact: AgentArtifact) -> dict[str, Any]:
        content = artifact.content_json or {}
        return {
            "id": artifact.id,
            "type": artifact.artifact_type,
            "title": content.get("title") or "执行结果",
            "summary": content.get("summary") or content.get("content"),
            "content": content,
            "actions": [],
            "created_at": artifact.created_at,
        }

    @staticmethod
    def _safe_json(value: Optional[str]) -> dict[str, Any]:
        if not value:
            return {"kind": "confirmation", "summary": "需要你的确认"}
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {"kind": "reference", "summary": value}
        return (
            parsed
            if isinstance(parsed, dict)
            else {"kind": "reference", "value": parsed}
        )
