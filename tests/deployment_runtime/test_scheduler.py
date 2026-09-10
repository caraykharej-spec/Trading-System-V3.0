from app.deployment_runtime.scheduler import Scheduler, ScheduledTask


def test_scheduler_lifecycle():
    scheduler = Scheduler()
    scheduler.start()
    assert scheduler.state.status == "RUNNING"
    scheduler.stop()
    assert scheduler.state.status == "STOPPED"


def test_task_registration():
    scheduler = Scheduler()
    scheduler.register_task(ScheduledTask(name="health_check", interval_seconds=60))
    assert "health_check" in scheduler.tasks
