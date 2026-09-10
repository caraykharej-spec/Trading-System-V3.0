from app.deployment_runtime.storage_backup_foundation import (
    StorageBackupManager,
    StorageProfile,
    BackupPolicy,
)


def test_storage_registration():
    manager = StorageBackupManager()
    manager.register_storage(StorageProfile("trade-data", "volume", 100))

    assert len(manager.list_storage()) == 1


def test_backup_policy_registration():
    manager = StorageBackupManager()
    manager.register_backup_policy(BackupPolicy("daily-backup", "daily", 30))

    assert len(manager.list_backup_policies()) == 1


def test_storage_health():
    manager = StorageBackupManager()

    health = manager.health()

    assert health["status"] == "healthy"
