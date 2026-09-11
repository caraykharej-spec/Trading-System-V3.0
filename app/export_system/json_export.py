"""JSON export layer for trading system reports."""

import json
from pathlib import Path
from typing import Any, Mapping


class JsonExporter:
    def export(self, data: Mapping[str, Any], destination: str) -> str:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(data), indent=4, default=str), encoding="utf-8")
        return str(path)
