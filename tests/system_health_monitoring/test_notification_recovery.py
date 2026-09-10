from app.system_health_monitoring.notification_interface import Notification, NotificationInterface
from app.system_health_monitoring.recovery_status import RecoveryStatus, RecoveryTracker


def test_notification_delivery():
    result = NotificationInterface().send(Notification(channel="system", message="health alert"))
    assert result.status == "sent"


def test_recovery_tracking():
    tracker = RecoveryTracker()
    result = tracker.record(RecoveryStatus(component="api", state="recovered"))
    assert result.state == "recovered"
    assert len(tracker.get_history()) == 1
