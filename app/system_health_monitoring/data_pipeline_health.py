"""Data Pipeline Health Monitor"""

from dataclasses import dataclass


@dataclass
class PipelineHealth:
    source: str
    status: str


class DataPipelineHealth:
    def check(self, source: str) -> PipelineHealth:
        return PipelineHealth(
            source=source,
            status="UNKNOWN",
        )
