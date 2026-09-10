from app.export_system.export_manager import ExportManager
from app.export_system.report_archive import ReportArchive


def test_export_manager():
    result = ExportManager().export("json", {"status": "ok"}, "reports")
    assert result.success is True


def test_report_archive():
    report = ReportArchive().archive("001", "daily")
    assert report.report_type == "daily"
