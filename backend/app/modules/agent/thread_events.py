"""Thread 级事件存储与 run 事件公开投影。"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AgentMessage,
    AgentRun,
    AgentThread,
    AgentThreadEvent,
    AgentThreadItem,
)
from .time_utils import utc_now

RUN_EVENT_TYPES = {
    "run.created": "workflow.updated",
    "run.status_changed": "workflow.updated",
    "run.completed": "workflow.completed",
    "run.failed": "workflow.failed",
    "error": "workflow.failed",
    "step.started": "workflow.step.updated",
    "step.completed": "workflow.step.updated",
    "step.failed": "workflow.step.updated",
    "tool.called": "workflow.activity.updated",
    "tool.result": "workflow.activity.updated",
    "artifact.rendered": "workflow.artifact.created",
}

PUBLIC_STEP_LABELS = {
    "intent": "理解需求",
    "route": "选择处理方式",
    "load_scope": "确认学习范围",
    "evidence_loop": "查找相关资料",
    "evidence_gate": "检查资料质量",
    "generate_explanation": "组织讲解",
    "citation_gate": "检查引用",
    "question_discovery": "查找候选题",
    "question_gate": "检查题目质量",
    "create_draft": "生成练习草稿",
    "generate_feedback": "生成反馈",
    "propose_plan_delta": "生成调整方案",
    "wait_for_approval": "等待你的确认",
    "completed": "完成",
}


class ThreadEventStore:
    async def append(
        self,
        session: AsyncSession,
        thread_id: str,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> AgentThreadEvent:
        thread = await self._lock_thread(session, thread_id)
        sequence = thread.last_item_sequence + 1
        thread.last_item_sequence = sequence
        thread.updated_at = utc_now()
        return await self.append_at(session, thread_id, sequence, event_type, payload)

    async def append_at(
        self,
        session: AsyncSession,
        thread_id: str,
        sequence: int,
        event_type: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> AgentThreadEvent:
        event = AgentThreadEvent(
            thread_id=thread_id,
            sequence=sequence,
            event_type=event_type,
            payload={"sequence": sequence, **(payload or {})},
        )
        session.add(event)
        await session.flush()
        return event

    async def get_events(
        self,
        session: AsyncSession,
        thread_id: str,
        after_sequence: int,
        limit: int,
    ) -> list[AgentThreadEvent]:
        result = await session.execute(
            select(AgentThreadEvent)
            .where(
                AgentThreadEvent.thread_id == thread_id,
                AgentThreadEvent.sequence > after_sequence,
            )
            .order_by(AgentThreadEvent.sequence)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def project_run_event(
        self,
        session: AsyncSession,
        run_id: str,
        run_event_type: str,
        payload: Optional[dict[str, Any]],
    ) -> None:
        result = await session.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run:
            return
        root_run_id = run.root_run_id or run.id
        public_payload: dict[str, Any] = {
            "root_run_id": root_run_id,
            "run_id": run.id,
            "status": run.status,
        }

        if run_event_type in {"message.delta", "message.completed", "message.failed"}:
            source = payload or {}
            if run_event_type == "message.delta":
                public_payload["delta"] = source.get("delta", "")
            elif run_event_type == "message.completed":
                public_payload["content"] = source.get("content", "")
            else:
                public_payload.update(
                    {
                        "content": source.get("content", ""),
                        "error_code": source.get("error_code", "agent_run_failed"),
                    }
                )
            await self._project_message_event(
                session, run, root_run_id, run_event_type, public_payload
            )
            return

        if run.presentation == "silent":
            if run.workflow_name == "conversation" and run_event_type in {
                "run.failed",
                "error",
            }:
                source = payload or {}
                error_code = source.get("error_code") or "agent_run_failed"
                await self._project_message_event(
                    session,
                    run,
                    root_run_id,
                    "message.failed",
                    {
                        "error_code": error_code,
                        "content": (
                            "Agent 模型尚未配置好，请联系管理员检查问答 LLM。"
                            if error_code == "agent_model_unavailable"
                            else "这条回复生成失败，请稍后重试。"
                        ),
                    },
                )
            return

        thread_event_type = RUN_EVENT_TYPES.get(run_event_type)
        if thread_event_type:
            source = payload or {}
            if run_event_type.startswith("step."):
                public_payload.update(
                    {
                        "step_id": source.get("step_id"),
                        "label": PUBLIC_STEP_LABELS.get(
                            source.get("node_name"), "执行步骤"
                        ),
                        "step_status": run_event_type.removeprefix("step."),
                    }
                )
            elif run_event_type in {"tool.called", "tool.result"}:
                public_payload.update(
                    {
                        "activity": {
                            "id": source.get("activity_id"),
                            "activity_type": source.get("activity_type", "tool"),
                            "title": source.get("title", "调用工具"),
                            "detail": source.get("detail"),
                            "status": (
                                source.get("status", "completed")
                                if run_event_type == "tool.result"
                                else "running"
                            ),
                            "metadata": source.get("public_metadata") or {},
                            "started_at": source.get("started_at"),
                            "completed_at": source.get("completed_at"),
                        }
                    }
                )
            elif run_event_type == "artifact.rendered":
                public_payload.update(
                    {
                        "artifact_id": source.get("artifact_id"),
                        "artifact_type": source.get("artifact_type"),
                    }
                )
            elif run_event_type in {"run.failed", "error"}:
                public_payload["error"] = source.get("error") or run.error_message
            elif run_event_type == "run.status_changed":
                public_payload["reason"] = source.get("reason")
            await self.append(session, run.thread_id, thread_event_type, public_payload)

    async def project_workflow_interaction(
        self,
        session: AsyncSession,
        run_id: str,
        event_type: str,
        *,
        status: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> None:
        """把待输入或待审批事实投影到 thread 事件流。"""
        result = await session.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if not run or run.presentation == "silent":
            return
        await self.append(
            session,
            run.thread_id,
            event_type,
            {
                "root_run_id": run.root_run_id or run.id,
                "run_id": run.id,
                "status": status,
                **(payload or {}),
            },
        )

    async def _project_message_event(
        self,
        session: AsyncSession,
        run: AgentRun,
        root_run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        result = await session.execute(
            select(AgentMessage)
            .where(AgentMessage.run_id == run.id, AgentMessage.role == "assistant")
            .order_by(AgentMessage.created_at.desc())
            .limit(1)
        )
        message = result.scalar_one_or_none()
        if not message:
            message = AgentMessage(
                id=f"msg_{uuid.uuid4().hex[:20]}",
                thread_id=run.thread_id,
                user_id=run.user_id,
                run_id=run.id,
                role="assistant",
                status="streaming",
                content_text="",
                content_blocks_json=[],
            )
            session.add(message)
            await session.flush()
            thread = await self._lock_thread(session, run.thread_id)
            item_sequence = thread.last_item_sequence + 1
            thread.last_item_sequence = item_sequence
            thread.updated_at = utc_now()
            item = AgentThreadItem(
                id=f"item_{uuid.uuid4().hex[:20]}",
                thread_id=run.thread_id,
                sequence=item_sequence,
                item_type="message",
                ref_id=message.id,
                run_id=run.id,
            )
            session.add(item)
            await self.append_at(
                session,
                run.thread_id,
                item_sequence,
                "timeline.item.created",
                {"item_id": item.id, "item_type": "message", "ref_id": message.id},
            )

        if event_type == "message.delta":
            message.content_text = (message.content_text or "") + str(
                payload.get("delta", "")
            )
            message.status = "streaming"
            public_type = "message.delta"
            public_payload = {
                "message_id": message.id,
                "delta": payload.get("delta", ""),
            }
        elif event_type == "message.completed":
            message.content_text = str(
                payload.get("content") or message.content_text or ""
            )
            message.status = "completed"
            message.completed_at = utc_now()
            public_type = "message.completed"
            public_payload = {
                "message_id": message.id,
                "root_run_id": root_run_id,
                "message": {
                    "id": message.id,
                    "role": message.role,
                    "status": message.status,
                    "content": message.content_text,
                },
            }
        else:
            message.content_text = str(
                payload.get("content") or "这条回复生成失败，请稍后重试。"
            )
            message.status = "failed"
            message.error_code = str(
                payload.get("error_code") or "agent_run_failed"
            )
            message.completed_at = utc_now()
            public_type = "message.failed"
            public_payload = {
                "message_id": message.id,
                "root_run_id": root_run_id,
                "error_code": message.error_code,
                "message": {
                    "id": message.id,
                    "role": message.role,
                    "status": message.status,
                    "content": message.content_text,
                    "error_code": message.error_code,
                },
            }
        message.updated_at = utc_now()
        await self.append(session, run.thread_id, public_type, public_payload)

    @staticmethod
    async def _lock_thread(session: AsyncSession, thread_id: str) -> AgentThread:
        result = await session.execute(
            select(AgentThread).where(AgentThread.id == thread_id).with_for_update()
        )
        return result.scalar_one()


thread_event_store = ThreadEventStore()
