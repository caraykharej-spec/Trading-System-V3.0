from app.export_system.json_export import JsonExporter
from app.export_system.csv_export import CsvExporter


def test_json_export():
    assert JsonExporter().export({"status": "ok"}, "test_output/report.json").endswith("report.json")


def test_csv_export():
    assert CsvExporter().export([{"symbol": "BTC"}], "test_output/report.csv").endswith("report.csv")
