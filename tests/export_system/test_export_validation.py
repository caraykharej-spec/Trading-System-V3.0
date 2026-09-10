from app.export_system.export_validation import ExportValidator


def test_valid_export_payload():
    result = ExportValidator().validate({
        "export_type": "json",
        "data": {}
    })
    assert result.valid is True


def test_invalid_export_payload():
    result = ExportValidator().validate({})
    assert result.valid is False
