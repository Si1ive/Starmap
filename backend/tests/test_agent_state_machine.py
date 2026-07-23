"""Tests for agent run state machine."""

import pytest
from datetime import datetime

from app.modules.agent.state_machine import (
    RunStatus,
    StateMachine,
    TransitionError,
    VALID_TRANSITIONS,
    state_machine,
)


class FakeRun:
    def __init__(self, status="queued"):
        self.id = "run_test"
        self.status = status
        self.updated_at = datetime.utcnow()


class TestRunStatus:
    def test_status_values(self):
        assert RunStatus.QUEUED.value == "queued"
        assert RunStatus.RUNNING.value == "running"
        assert RunStatus.COMPLETED.value == "completed"
        assert RunStatus.FAILED.value == "failed"
        assert RunStatus.WAITING_FOR_USER.value == "waiting_for_user"
        assert RunStatus.WAITING_FOR_APPROVAL.value == "waiting_for_approval"


class TestStateMachineTransitions:
    def test_can_transition_queued_to_running(self):
        assert state_machine.can_transition(RunStatus.QUEUED, RunStatus.RUNNING) is True

    def test_can_transition_queued_to_completed_is_false(self):
        assert state_machine.can_transition(RunStatus.QUEUED, RunStatus.COMPLETED) is False

    def test_can_transition_running_to_terminal_states(self):
        assert state_machine.can_transition(RunStatus.RUNNING, RunStatus.COMPLETED) is True
        assert state_machine.can_transition(RunStatus.RUNNING, RunStatus.FAILED) is True
        assert state_machine.can_transition(RunStatus.RUNNING, RunStatus.WAITING_FOR_USER) is True
        assert state_machine.can_transition(RunStatus.RUNNING, RunStatus.WAITING_FOR_APPROVAL) is True

    def test_can_transition_waiting_to_running(self):
        assert state_machine.can_transition(RunStatus.WAITING_FOR_USER, RunStatus.RUNNING) is True
        assert state_machine.can_transition(RunStatus.WAITING_FOR_APPROVAL, RunStatus.RUNNING) is True

    def test_terminal_states_have_no_outgoing_transitions(self):
        assert state_machine.can_transition(RunStatus.COMPLETED, RunStatus.RUNNING) is False
        assert state_machine.can_transition(RunStatus.COMPLETED, RunStatus.QUEUED) is False
        assert state_machine.can_transition(RunStatus.FAILED, RunStatus.RUNNING) is False

    def test_transition_success(self):
        run = FakeRun("queued")
        state_machine.transition(run, RunStatus.RUNNING)
        assert run.status == "running"

    def test_transition_failure_raises(self):
        run = FakeRun("queued")
        with pytest.raises(TransitionError):
            state_machine.transition(run, RunStatus.COMPLETED)
        assert run.status == "queued"

    def test_transition_updates_timestamp(self):
        run = FakeRun("running")
        before = run.updated_at
        state_machine.transition(run, RunStatus.COMPLETED)
        assert run.updated_at > before

    def test_is_terminal(self):
        assert state_machine.is_terminal(RunStatus.COMPLETED) is True
        assert state_machine.is_terminal(RunStatus.FAILED) is True
        assert state_machine.is_terminal(RunStatus.RUNNING) is False
        assert state_machine.is_terminal(RunStatus.QUEUED) is False

    def test_is_active(self):
        assert state_machine.is_active(RunStatus.QUEUED) is True
        assert state_machine.is_active(RunStatus.RUNNING) is True
        assert state_machine.is_active(RunStatus.COMPLETED) is False
        assert state_machine.is_active(RunStatus.FAILED) is False


class TestStateMachineHooks:
    def test_hook_fires_on_transition(self):
        sm = StateMachine()
        called = []

        def hook(run, old_status, new_status, reason):
            called.append((old_status, new_status, reason))

        sm.add_hook("queued", "running", hook)
        run = FakeRun("queued")
        sm.transition(run, RunStatus.RUNNING, reason="test")
        assert len(called) == 1
        assert called[0] == ("queued", "running", "test")

    def test_hook_does_not_fire_on_illegal_transition(self):
        sm = StateMachine()
        called = []

        def hook(run, old_status, new_status, reason):
            called.append(True)

        sm.add_hook("queued", "completed", hook)
        run = FakeRun("queued")
        with pytest.raises(TransitionError):
            sm.transition(run, RunStatus.COMPLETED)
        assert len(called) == 0


class TestValidTransitionsCompleteness:
    def test_all_non_terminal_have_at_least_one_exit(self):
        for status in RunStatus:
            if status in {RunStatus.COMPLETED, RunStatus.FAILED}:
                assert VALID_TRANSITIONS[status] == set()
            else:
                assert len(VALID_TRANSITIONS[status]) > 0
