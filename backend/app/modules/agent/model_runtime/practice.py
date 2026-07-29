"""题库无合格候选时的结构化练习题生成运行时。"""

from dataclasses import dataclass

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.models import Model

from app.core.config import settings
from app.core.logging import get_logger

from .config import open_agent_model
from .schema import GeneratedPracticeQuestion

logger = get_logger(__name__)


@dataclass(frozen=True)
class PracticeGenerationDeps:
    run_id: str
    user_id: str
    topic: str
    difficulty: str = "medium"


practice_generation_agent = Agent(
    deps_type=PracticeGenerationDeps,
    output_type=GeneratedPracticeQuestion,
    retries=1,
    instructions=(
        "你是考研 408 练习题命题助手。题库没有找到合适真题时，根据给定主题生成一道"
        "事实准确、题意完整、只有一个正确答案的单项选择题。不要声称题目来自真题或知识库；"
        "选项 key 使用 A-H 大写字母。只返回结构化 GeneratedPracticeQuestion。"
    ),
)


class PracticeGenerationRuntime:
    def __init__(self, model: Model | str | None = None):
        self.model = model

    async def generate(
        self, *, deps: PracticeGenerationDeps, db=None
    ) -> GeneratedPracticeQuestion:
        prompt = (
            f"练习主题：{deps.topic}\n"
            f"目标难度：{deps.difficulty}\n"
            "请生成一道可确定性批改的单项选择题，并给出答案和解析。"
        )
        if self.model is not None:
            result = await self._run(prompt, deps=deps, model=self.model)
            model_version = _model_version(self.model)
        elif db is not None:
            async with open_agent_model(
                db, run_id=deps.run_id, purpose="Agent 练习题生成"
            ) as session:
                logger.info(
                    "练习题生成模型调用开始",
                    run_id=deps.run_id,
                    model=session.config.model_name,
                    config_source=session.config.source,
                )
                result = await self._run(
                    prompt,
                    deps=deps,
                    model=session.model,
                    model_settings=session.config.model_settings,
                )
                model_version = session.config.model_name
        else:
            result = await self._run(
                prompt, deps=deps, model=settings.AGENT_ROUTER_MODEL
            )
            model_version = str(settings.AGENT_ROUTER_MODEL)
        output = result.output
        if model_version and not output.model_version:
            output = output.model_copy(update={"model_version": model_version[:64]})
        return output

    @staticmethod
    async def _run(prompt, *, deps, model, model_settings=None):
        return await practice_generation_agent.run(
            prompt,
            deps=deps,
            model=model,
            model_settings=model_settings,
            usage_limits=UsageLimits(request_limit=2),
        )


practice_generation_runtime = PracticeGenerationRuntime()


def _model_version(model: Model | str) -> str | None:
    model_name = getattr(model, "model_name", None)
    if model_name:
        return str(model_name)
    if isinstance(model, str):
        return model
    return None
