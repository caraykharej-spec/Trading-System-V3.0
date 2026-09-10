from app.production_operation.production_checklist import (
    ChecklistItem,
    ProductionChecklistEngine,
)


def test_checklist_registration():
    engine = ProductionChecklistEngine()
    engine.register_item(
        ChecklistItem(
            name="Runtime Check",
            category="Runtime",
            passed=True
        )
    )

    report = engine.validate()

    assert len(report.items) == 1
    assert report.passed is True


def test_checklist_health():
    engine = ProductionChecklistEngine()
    status = engine.health()

    assert status["component"] == "Production Checklist"
