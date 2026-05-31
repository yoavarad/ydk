"""Tests for buffer management with green/yellow/red health tracking."""

from odk.core.buffer_manager import BufferManager
from odk.models.buffer import BufferStatus, BufferZone
from odk.models.pm import TaskSummary


def _make_tasks(
    total: int,
    done: int = 0,
    in_progress: int = 0,
    blocked: int = 0,
) -> list[TaskSummary]:
    tasks: list[TaskSummary] = []
    idx = 0
    for _ in range(done):
        idx += 1
        tasks.append(TaskSummary(id=f"T-{idx:03d}", title=f"Task {idx}", status="done"))
    for _ in range(in_progress):
        idx += 1
        tasks.append(TaskSummary(id=f"T-{idx:03d}", title=f"Task {idx}", status="in-progress"))
    for _ in range(blocked):
        idx += 1
        tasks.append(TaskSummary(id=f"T-{idx:03d}", title=f"Task {idx}", status="blocked-by-code"))
    remaining = total - done - in_progress - blocked
    for _ in range(remaining):
        idx += 1
        tasks.append(TaskSummary(id=f"T-{idx:03d}", title=f"Task {idx}", status="open"))
    return tasks


class TestBufferZoneClassification:
    def test_green_zone_early_sprint(self):
        tasks = _make_tasks(total=10, done=3)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=10)
        assert status.zone == BufferZone.GREEN
        assert status.buffer_consumption_pct < 0.33
        assert status.on_track is True

    def test_yellow_zone_mid_sprint(self):
        tasks = _make_tasks(total=10, done=3)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=6)
        assert status.zone == BufferZone.YELLOW
        assert 0.33 <= status.buffer_consumption_pct <= 0.66

    def test_red_zone_late_sprint(self):
        # 7/10 done with 10 waves => elapsed=7, consumption=0.7 => RED
        tasks = _make_tasks(total=10, done=7)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=10)
        assert status.zone == BufferZone.RED
        assert status.buffer_consumption_pct > 0.66

    def test_all_tasks_done(self):
        tasks = _make_tasks(total=5, done=5)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=5)
        assert status.completed_tasks == 5
        assert status.on_track is True
        assert status.zone == BufferZone.GREEN

    def test_no_tasks(self):
        mgr = BufferManager()
        status = mgr.calculate_status([], planned_waves=5)
        assert status.total_tasks == 0
        assert status.completed_tasks == 0
        assert status.zone == BufferZone.GREEN
        assert status.on_track is True

    def test_boundary_just_below_33_percent(self):
        """Consumption just below 33% should be GREEN."""
        # 3/10 done, planned=10 => elapsed=3, consumption=0.3 => GREEN
        tasks = _make_tasks(total=10, done=3)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=10)
        assert status.buffer_consumption_pct < 0.33
        assert status.zone == BufferZone.GREEN

    def test_boundary_at_33_percent(self):
        """Consumption at exactly 1/3 should be YELLOW."""
        # 1/3 done, planned=3 => elapsed=1, consumption=1/3 => YELLOW
        tasks = _make_tasks(total=3, done=1)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=3)
        assert abs(status.buffer_consumption_pct - 1 / 3) < 1e-9
        assert status.zone == BufferZone.YELLOW

    def test_boundary_at_66_percent(self):
        """Consumption at exactly 2/3 should be RED."""
        # 2/3 done, planned=3 => elapsed=2, consumption=2/3 => RED
        tasks = _make_tasks(total=3, done=2)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=3)
        assert abs(status.buffer_consumption_pct - 2 / 3) < 1e-9
        assert status.zone == BufferZone.RED


class TestBufferStatusFields:
    def test_task_counts(self):
        tasks = _make_tasks(total=10, done=3, in_progress=2, blocked=1)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=10)
        assert status.total_tasks == 10
        assert status.completed_tasks == 3
        assert status.in_progress_tasks == 2
        assert status.blocked_tasks == 1

    def test_summary_is_nonempty(self):
        tasks = _make_tasks(total=5, done=2)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=5)
        assert isinstance(status.summary, str)
        assert len(status.summary) > 0

    def test_planned_waves_stored(self):
        tasks = _make_tasks(total=6, done=2)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=8)
        assert status.planned_waves == 8

    def test_returns_buffer_status_type(self):
        tasks = _make_tasks(total=3, done=1)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=5)
        assert isinstance(status, BufferStatus)


class TestOnTrackCalculation:
    def test_on_track_when_ahead(self):
        tasks = _make_tasks(total=10, done=5)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=10)
        assert status.on_track is True

    def test_not_on_track_when_behind(self):
        # 2/10 done, planned_waves=4 => elapsed=round(2/10*4)=1, consumption=0.25
        # But completion=0.2, elapsed_pct=0.25 => not on track
        tasks = _make_tasks(total=10, done=2)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=4)
        assert status.on_track is False

    def test_on_track_all_done_early(self):
        tasks = _make_tasks(total=5, done=5)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=10)
        assert status.on_track is True


class TestElapsedWavesEstimation:
    def test_elapsed_waves_from_completion(self):
        tasks = _make_tasks(total=10, done=5)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=10)
        assert status.elapsed_waves == 5

    def test_elapsed_waves_zero_when_no_done(self):
        tasks = _make_tasks(total=10, done=0)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=10)
        assert status.elapsed_waves == 0


class TestDefaultPlannedWaves:
    def test_defaults_to_total_tasks_when_none(self):
        tasks = _make_tasks(total=8, done=2)
        mgr = BufferManager()
        status = mgr.calculate_status(tasks, planned_waves=None)
        assert status.planned_waves == 8
