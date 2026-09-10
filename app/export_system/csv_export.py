"""CSV export layer for trading system reports."""

import csv
from pathlib import Path


class CsvExporter:
    def export(self, rows: list[dict], destination: str) -> str:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8")
            return str(path)
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return str(path)
