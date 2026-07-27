"""从持久化线程事实构建受控的 Agent 模型上下文。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    AgentApproval,
    AgentArtifact,
    AgentInput,
    AgentMessage,
    AgentRun,
    AgentConversationSummary,
    AgentThreadMemoryState,
    AgentThread,
    AgentThreadItem,
)

CONTEXT_POLICY_VERSION = "thread-context-v1"


class ContextNotFoundError(Exception):
    """线程、运行或当前消息不属于调用用户时使用统一的未找到错误。"""


class ContextIntegrityError(Exception):
    """持久化事实之间的关联不完整或互相冲突。"""


class ConversationMessage(BaseModel):
    """经过权限和状态过滤的用户可见消息。"""

    id: str
    role: Literal["user", "assistant"]
    content: str
    sequence: int
    created_at: datetime
    estimated_tokens: int


class ArtifactContext(BaseModel):
    """可提供给 Agent 的公开产物摘要。"""

    id: str
    run_id: str
    artifact_type: str
    summary: str
    created_at: datetime
    estimated_tokens: int
    reference_entities: list[dict[str, Any]] = Field(default_factory=list)


class PendingInteraction(BaseModel):
    """线程中尚未完成的结构化输入或审批。"""

    kind: Literal["input", "approval"]
    id: str
    run_id: str
    interaction_key: str
    public_prompt: str | None = None


class PermissionScope(BaseModel):
    """本轮上下文已经校验过的最小资源范围。"""

    user_id: str
    thread_id: str
    root_run_id: str
    artifact_ids: list[str] = Field(default_factory=list)


class AgentRunContext(BaseModel):
    """Provider-neutral 的单轮 Agent 上下文。"""

    thread_id: str
    user_id: str
    turn_id: str
    current_message_id: str
    current_input: str
    recent_messages: list[ConversationMessage] = Field(default_factory=list)
    conversation_summary: str | None = None
    conversation_summary_source: dict[str, Any] | None = None
    recent_artifacts: list[ArtifactContext] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    pending_interactions: list[PendingInteraction] = Field(default_factory=list)
    active_topic: dict[str, Any] | None = None
    memory_state_version: int | None = None
    standalone_request: str | None = None
    memory_snapshot_id: str | None = None
    permission_scope: PermissionScope
    token_budget: int
    history_token_budget: int
    estimated_tokens: int
    selected_message_ids: list[str] = Field(default_factory=list)
    dropped_message_ids: list[str] = Field(default_factory=list)
    selected_artifact_ids: list[str] = Field(default_factory=list)
    dropped_artifact_ids: list[str] = Field(default_factory=list)
    policy_version: str = CONTEXT_POLICY_VERSION

    def to_message_history(self) -> list[ModelMessage]:
        """转换为可直接交给 Pydantic AI Agent.run 的消息历史。"""
        history: list[ModelMessage] = []
        for message in self.recent_messages:
            if message.role == "user":
                part = UserPromptPart(content=message.content)
                history.append(ModelRequest(parts=[part]))
            else:
                part = TextPart(content=message.content)
                history.append(ModelResponse(parts=[part]))
        return history


class ThreadContextBuilder:
    """按权限、可见性和确定性预算装配线程上下文。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        max_history_turns: int = 12,
        max_artifacts: int = 8,
    ):
        self.db = db
        self.max_history_turns = max_history_turns
        self.max_artifacts = max_artifacts

    async def build(
        self,
        *,
        user_id: str,
        thread_id: str,
        turn_id: str,
        current_message_id: str | None = None,
        token_budget: int = 4096,
    ) -> AgentRunContext:
        """从数据库事实构建本轮上下文，不信任客户端提交的历史。"""
        if token_budget <= 0:
            raise ValueError("token_budget 必须大于 0")

        thread = await self._load_thread(user_id=user_id, thread_id=thread_id)
        run = await self._load_run(
            user_id=user_id,
            thread_id=thread.id,
            run_id=turn_id,
        )
        message_id = current_message_id or run.trigger_message_id
        if not message_id:
            raise ContextIntegrityError("当前运行缺少触发消息")
        if run.trigger_message_id and run.trigger_message_id != message_id:
            raise ContextIntegrityError("当前消息不是该运行的触发消息")

        current_message, current_sequence = await self._load_current_message(
            user_id=user_id,
            thread_id=thread.id,
            message_id=message_id,
        )
        current_input = (current_message.content_text or "").strip()
        if (
            current_message.role != "user"
            or current_message.status != "completed"
            or not current_input
        ):
            raise ContextIntegrityError("当前触发消息必须是已完成的非空用户消息")

        root_run = await self._load_root_run(
            current_run=run,
            user_id=user_id,
            thread_id=thread.id,
        )
        attachments, context_refs = self._extract_run_metadata(root_run)
        explicit_artifact_ids = self._extract_explicit_artifact_ids(context_refs)
        artifact_candidates = await self._load_artifacts(
            user_id=user_id,
            thread_id=thread.id,
            explicit_artifact_ids=explicit_artifact_ids,
        )
        pending_interactions = await self._load_pending_interactions(
            user_id=user_id,
            thread_id=thread.id,
        )
        memory_state = await self._load_thread_memory_state(
            user_id=user_id,
            thread_id=thread.id,
        )

        current_tokens = self.estimate_tokens(current_input)
        mandatory_tokens = self._estimate_supplemental_tokens(
            artifacts=(),
            attachments=attachments,
            context_refs=context_refs,
            interactions=pending_interactions,
        )
        artifacts, dropped_artifacts = self._select_recent_artifacts(
            artifact_candidates,
            explicit_artifact_ids=explicit_artifact_ids,
            token_budget=max(0, token_budget - current_tokens - mandatory_tokens),
        )
        supplemental_tokens = mandatory_tokens + sum(
            artifact.estimated_tokens for artifact in artifacts
        )
        history_token_budget = max(
            0,
            token_budget - current_tokens - supplemental_tokens,
        )
        candidates = await self._load_history_candidates(
            user_id=user_id,
            thread_id=thread.id,
            before_sequence=current_sequence,
        )
        selected, dropped = self._select_recent_turns(
            candidates,
            token_budget=history_token_budget,
        )
        selected_history_tokens = sum(message.estimated_tokens for message in selected)
        conversation_summary, conversation_summary_source = (
            await self._load_conversation_summary(
                user_id=user_id,
                thread_id=thread.id,
                before_sequence=(selected[0].sequence if selected else current_sequence),
                token_budget=max(0, history_token_budget - selected_history_tokens),
            )
        )

        selected_artifact_ids = [artifact.id for artifact in artifacts]
        return AgentRunContext(
            thread_id=thread.id,
            user_id=user_id,
            turn_id=run.id,
            current_message_id=current_message.id,
            current_input=current_input,
            recent_messages=selected,
            conversation_summary=conversation_summary,
            conversation_summary_source=conversation_summary_source,
            recent_artifacts=artifacts,
            attachments=attachments,
            context_refs=context_refs,
            pending_interactions=pending_interactions,
            active_topic=(
                dict(memory_state.active_topic_json)
                if memory_state and memory_state.active_topic_json
                else None
            ),
            memory_state_version=memory_state.version if memory_state else None,
            permission_scope=PermissionScope(
                user_id=user_id,
                thread_id=thread.id,
                root_run_id=root_run.id,
                artifact_ids=selected_artifact_ids,
            ),
            token_budget=token_budget,
            history_token_budget=history_token_budget,
            estimated_tokens=(
                current_tokens
                + supplemental_tokens
                + selected_history_tokens
                + int((conversation_summary_source or {}).get("token_estimate") or 0)
            ),
            selected_message_ids=[message.id for message in selected],
            dropped_message_ids=[message.id for message in dropped],
            selected_artifact_ids=selected_artifact_ids,
            dropped_artifact_ids=[artifact.id for artifact in dropped_artifacts],
        )

    async def _load_thread(self, *, user_id: str, thread_id: str) -> AgentThread:
        result = await self.db.execute(
            select(AgentThread).where(
                AgentThread.id == thread_id,
                AgentThread.user_id == user_id,
            )
        )
        thread = result.scalar_one_or_none()
        if not thread:
            raise ContextNotFoundError("线程不存在")
        return thread

    async def _load_run(
        self,
        *,
        user_id: str,
        thread_id: str,
        run_id: str,
    ) -> AgentRun:
        result = await self.db.execute(
            select(AgentRun).where(
                AgentRun.id == run_id,
                AgentRun.thread_id == thread_id,
                AgentRun.user_id == user_id,
            )
        )
        run = result.scalar_one_or_none()
        if not run:
            raise ContextNotFoundError("运行不存在")
        return run

    async def _load_current_message(
        self,
        *,
        user_id: str,
        thread_id: str,
        message_id: str,
    ) -> tuple[AgentMessage, int]:
        result = await self.db.execute(
            select(AgentMessage, AgentThreadItem.sequence)
            .join(
                AgentThreadItem,
                (AgentThreadItem.ref_id == AgentMessage.id)
                & (AgentThreadItem.thread_id == AgentMessage.thread_id)
                & (AgentThreadItem.item_type == "message"),
            )
            .where(
                AgentMessage.id == message_id,
                AgentMessage.thread_id == thread_id,
                AgentMessage.user_id == user_id,
                AgentThreadItem.visibility == "visible",
            )
        )
        row = result.one_or_none()
        if not row:
            raise ContextNotFoundError("当前消息不存在")
        return row[0], row[1]

    async def _load_root_run(
        self,
        *,
        current_run: AgentRun,
        user_id: str,
        thread_id: str,
    ) -> AgentRun:
        root_run_id = current_run.root_run_id or current_run.id
        root_run = await self._load_run(
            user_id=user_id,
            thread_id=thread_id,
            run_id=root_run_id,
        )
        if root_run.parent_run_id is not None:
            raise ContextIntegrityError("root_run_id 未指向根运行")
        return root_run

    async def _load_history_candidates(
        self,
        *,
        user_id: str,
        thread_id: str,
        before_sequence: int,
    ) -> list[ConversationMessage]:
        result = await self.db.execute(
            select(AgentMessage, AgentThreadItem.sequence)
            .join(
                AgentThreadItem,
                (AgentThreadItem.ref_id == AgentMessage.id)
                & (AgentThreadItem.thread_id == AgentMessage.thread_id)
                & (AgentThreadItem.item_type == "message"),
            )
            .where(
                AgentMessage.thread_id == thread_id,
                AgentMessage.user_id == user_id,
                AgentMessage.role.in_(("user", "assistant")),
                AgentMessage.status == "completed",
                AgentThreadItem.visibility == "visible",
                AgentThreadItem.sequence < before_sequence,
            )
            .order_by(AgentThreadItem.sequence.asc())
        )
        messages: list[ConversationMessage] = []
        for message, sequence in result.all():
            content = (message.content_text or "").strip()
            if not content:
                continue
            messages.append(
                ConversationMessage(
                    id=message.id,
                    role=message.role,
                    content=content,
                    sequence=sequence,
                    created_at=message.created_at,
                    estimated_tokens=self.estimate_tokens(content),
                )
            )
        return messages

    async def _load_artifacts(
        self,
        *,
        user_id: str,
        thread_id: str,
        explicit_artifact_ids: set[str],
    ) -> list[ArtifactContext]:
        recent_result = await self.db.execute(
            select(AgentArtifact)
            .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
            .where(
                AgentRun.thread_id == thread_id,
                AgentRun.user_id == user_id,
                AgentRun.presentation != "silent",
            )
            .order_by(AgentArtifact.created_at.desc(), AgentArtifact.id.desc())
            .limit(max(self.max_artifacts * 4, self.max_artifacts))
        )
        artifact_rows = list(recent_result.scalars())
        if explicit_artifact_ids:
            explicit_result = await self.db.execute(
                select(AgentArtifact)
                .join(AgentRun, AgentRun.id == AgentArtifact.run_id)
                .where(
                    AgentArtifact.id.in_(explicit_artifact_ids),
                    AgentRun.thread_id == thread_id,
                    AgentRun.user_id == user_id,
                    AgentRun.presentation != "silent",
                )
            )
            artifact_rows.extend(explicit_result.scalars())

        unique_rows = {artifact.id: artifact for artifact in artifact_rows}
        ordered_rows = sorted(
            unique_rows.values(),
            key=lambda artifact: (artifact.created_at, artifact.id),
            reverse=True,
        )
        artifacts: list[ArtifactContext] = []
        optional_count = 0
        for artifact in ordered_rows:
            metadata = artifact.metadata_json or {}
            if metadata.get("visibility") == "hidden":
                continue
            is_explicit = artifact.id in explicit_artifact_ids
            if not is_explicit and optional_count >= self.max_artifacts:
                continue
            summary = self._summarize_artifact(artifact.content_json)
            if not summary:
                continue
            artifacts.append(
                ArtifactContext(
                    id=artifact.id,
                    run_id=artifact.run_id,
                    artifact_type=artifact.artifact_type,
                    summary=summary,
                    created_at=artifact.created_at,
                    estimated_tokens=self.estimate_tokens(summary),
                    reference_entities=self._extract_artifact_reference_entities(
                        artifact_id=artifact.id,
                        artifact_type=artifact.artifact_type,
                        content=artifact.content_json,
                    ),
                )
            )
            if not is_explicit:
                optional_count += 1
        artifacts.reverse()
        return artifacts

    async def _load_pending_interactions(
        self,
        *,
        user_id: str,
        thread_id: str,
    ) -> list[PendingInteraction]:
        now = datetime.now(UTC).replace(tzinfo=None)
        input_result = await self.db.execute(
            select(AgentInput)
            .join(AgentRun, AgentRun.id == AgentInput.run_id)
            .where(
                AgentRun.thread_id == thread_id,
                AgentRun.user_id == user_id,
                AgentInput.status == "pending",
                or_(AgentInput.expires_at.is_(None), AgentInput.expires_at > now),
            )
            .order_by(AgentInput.created_at.asc(), AgentInput.id.asc())
        )
        approval_result = await self.db.execute(
            select(AgentApproval)
            .join(AgentRun, AgentRun.id == AgentApproval.run_id)
            .where(
                AgentRun.thread_id == thread_id,
                AgentRun.user_id == user_id,
                AgentApproval.status == "pending",
                or_(
                    AgentApproval.expires_at.is_(None),
                    AgentApproval.expires_at > now,
                ),
            )
            .order_by(AgentApproval.created_at.asc(), AgentApproval.id.asc())
        )
        interactions = [
            PendingInteraction(
                kind="input",
                id=item.id,
                run_id=item.run_id,
                interaction_key=item.input_key,
                public_prompt=item.prompt_ref,
            )
            for item in input_result.scalars()
        ]
        interactions.extend(
            PendingInteraction(
                kind="approval",
                id=item.id,
                run_id=item.run_id,
                interaction_key=item.action_key,
                public_prompt=item.diff_ref,
            )
            for item in approval_result.scalars()
        )
        return interactions

    async def _load_thread_memory_state(
        self,
        *,
        user_id: str,
        thread_id: str,
    ) -> AgentThreadMemoryState | None:
        result = await self.db.execute(
            select(AgentThreadMemoryState).where(
                AgentThreadMemoryState.thread_id == thread_id,
                AgentThreadMemoryState.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _load_conversation_summary(
        self,
        *,
        user_id: str,
        thread_id: str,
        before_sequence: int,
        token_budget: int,
    ) -> tuple[str | None, dict[str, Any] | None]:
        result = await self.db.execute(
            select(AgentConversationSummary)
            .where(
                AgentConversationSummary.thread_id == thread_id,
                AgentConversationSummary.user_id == user_id,
                AgentConversationSummary.superseded_by_id.is_(None),
                AgentConversationSummary.end_sequence < before_sequence,
            )
            .order_by(AgentConversationSummary.end_sequence.desc())
            .limit(2)
        )
        summaries = list(result.scalars())
        if len(summaries) > 1:
            raise ContextIntegrityError("同一线程存在多条活跃对话摘要")
        if not summaries:
            return None, None
        summary = summaries[0]
        content = summary.summary_text.strip()
        token_estimate = self.estimate_tokens(content) if content else 0
        if not content or token_estimate > token_budget:
            return None, None
        return content, {
            "id": summary.id,
            "version": summary.version,
            "start_sequence": summary.start_sequence,
            "end_sequence": summary.end_sequence,
            "source_message_ids": list(summary.source_message_ids_json or []),
            "token_estimate": token_estimate,
        }

    def _select_recent_artifacts(
        self,
        artifacts: Sequence[ArtifactContext],
        *,
        explicit_artifact_ids: set[str],
        token_budget: int,
    ) -> tuple[list[ArtifactContext], list[ArtifactContext]]:
        selected_ids = {
            artifact.id
            for artifact in artifacts
            if artifact.id in explicit_artifact_ids
        }
        used_tokens = sum(
            artifact.estimated_tokens
            for artifact in artifacts
            if artifact.id in selected_ids
        )
        for artifact in reversed(artifacts):
            if artifact.id in selected_ids:
                continue
            if used_tokens + artifact.estimated_tokens > token_budget:
                continue
            selected_ids.add(artifact.id)
            used_tokens += artifact.estimated_tokens

        selected = [artifact for artifact in artifacts if artifact.id in selected_ids]
        dropped = [
            artifact for artifact in artifacts if artifact.id not in selected_ids
        ]
        return selected, dropped

    def _select_recent_turns(
        self,
        messages: Sequence[ConversationMessage],
        *,
        token_budget: int,
    ) -> tuple[list[ConversationMessage], list[ConversationMessage]]:
        turns: list[list[ConversationMessage]] = []
        for message in messages:
            if message.role == "user" or not turns:
                turns.append([])
            turns[-1].append(message)

        selected_turns: list[list[ConversationMessage]] = []
        used_tokens = 0
        for turn in reversed(turns):
            if len(selected_turns) >= self.max_history_turns:
                break
            turn_tokens = sum(message.estimated_tokens for message in turn)
            if used_tokens + turn_tokens > token_budget:
                break
            selected_turns.append(turn)
            used_tokens += turn_tokens

        selected = [message for turn in reversed(selected_turns) for message in turn]
        selected_ids = {message.id for message in selected}
        dropped = [message for message in messages if message.id not in selected_ids]
        return selected, dropped

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """P0 确定性估算；实际 usage 仍以 Pydantic AI 返回值为准。"""
        return max(1, (len(text) + 3) // 4)

    @classmethod
    def _estimate_supplemental_tokens(
        cls,
        *,
        artifacts: Sequence[ArtifactContext],
        attachments: Sequence[dict[str, Any]],
        context_refs: Sequence[dict[str, Any]],
        interactions: Sequence[PendingInteraction],
    ) -> int:
        artifact_tokens = sum(item.estimated_tokens for item in artifacts)
        structured: dict[str, Any] = {}
        if attachments:
            structured["attachments"] = attachments
        if context_refs:
            structured["context_refs"] = context_refs
        if interactions:
            structured["pending_interactions"] = [
                item.model_dump(mode="json") for item in interactions
            ]
        if not structured:
            return artifact_tokens
        return artifact_tokens + cls.estimate_tokens(
            json.dumps(structured, ensure_ascii=False, sort_keys=True)
        )

    @staticmethod
    def _extract_run_metadata(
        root_run: AgentRun,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        metadata = root_run.metadata_json or {}
        attachments = metadata.get("attachments")
        context_refs = metadata.get("context_refs")
        safe_attachments = (
            [dict(item) for item in attachments if isinstance(item, dict)]
            if isinstance(attachments, list)
            else []
        )
        safe_context_refs = (
            [dict(item) for item in context_refs if isinstance(item, dict)]
            if isinstance(context_refs, list)
            else []
        )
        return safe_attachments, safe_context_refs

    @staticmethod
    def _extract_explicit_artifact_ids(
        context_refs: Sequence[dict[str, Any]],
    ) -> set[str]:
        artifact_ids: set[str] = set()
        for reference in context_refs:
            artifact_id = reference.get("artifact_id")
            if isinstance(artifact_id, str):
                artifact_ids.add(artifact_id)
            reference_ids = reference.get("artifact_ids")
            if isinstance(reference_ids, list):
                artifact_ids.update(
                    item for item in reference_ids if isinstance(item, str)
                )
            if reference.get("type") == "artifact":
                reference_id = reference.get("id")
                if isinstance(reference_id, str):
                    artifact_ids.add(reference_id)
        return artifact_ids

    @staticmethod
    def _summarize_artifact(content: dict[str, Any] | None) -> str:
        if not isinstance(content, dict):
            return ""
        parts: list[str] = []
        for key in ("title", "summary", "content", "text", "result"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        if not parts:
            parts.append(json.dumps(content, ensure_ascii=False, sort_keys=True))
        return "\n".join(parts)[:1200]

    @staticmethod
    def _extract_artifact_reference_entities(
        *,
        artifact_id: str,
        artifact_type: str,
        content: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """只从受信任的产物结构提取实体 ID，不解析标题或摘要。"""
        if artifact_type != "practice" or not isinstance(content, dict):
            return []
        artifact_content = content.get("content")
        if not isinstance(artifact_content, dict):
            return []
        question_ids = artifact_content.get("question_ids")
        if not isinstance(question_ids, list):
            return []

        references: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for value in question_ids:
            if not isinstance(value, str):
                continue
            question_id = value.strip()
            if not question_id or question_id in seen_ids:
                continue
            seen_ids.add(question_id)
            references.append(
                {
                    "type": "question",
                    "id": question_id,
                    "source": "artifact",
                    "artifact_id": artifact_id,
                }
            )
        return references
