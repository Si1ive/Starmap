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


@pytest.mark.asyncio
async def test_worker_loop_scans_run_and_memory_outboxes(monkeypatch):
    agent_worker = worker.AgentWorker()
    calls: list[tuple[str, int]] = []

    async def fake_scan_runs(limit):
        calls.append(("run", limit))
        return 0

    async def fake_scan_memory(*, limit):
        calls.append(("memory", limit))
        agent_worker.running = False
        return 1

    async def fake_sleep(_interval):
        return None

    monkeypatch.setattr(agent_worker, "scan_and_process", fake_scan_runs)
    monkeypatch.setattr(
        worker.memory_outbox_consumer,
        "scan_and_process",
        fake_scan_memory,
    )
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    await agent_worker.start(interval=0)

    assert calls == [("run", 10), ("memory", 10)]
