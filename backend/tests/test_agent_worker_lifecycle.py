"""Agent Worker 后台任务生命周期测试。"""

import asyncio

import pytest

from app.modules.agent import worker


@pytest.mark.asyncio
async def test_worker_task_is_retained_and_stopped(monkeypatch):
    async def fake_start(self, interval):
        self.running = True
        while self.running:
            await asyncio.sleep(0)

    monkeypatch.setattr(worker.AgentWorker, "start", fake_start)
    await worker.start_worker(interval=0)
    task = worker._worker_task

    assert task is not None
    assert task.get_name() == "agent-worker"
    assert not task.done()

    await worker.stop_worker()

    assert task.done()
    assert worker.get_worker() is None
    assert worker._worker_task is None
