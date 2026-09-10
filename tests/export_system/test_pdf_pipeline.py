from app.export_system.pdf_report_pipeline import PDFReportPipeline


def test_pdf_report_creation():
    pipeline = PDFReportPipeline()
    report = pipeline.create_report("risk_report", {"risk": "normal"})

    assert report.report_type == "risk_report"
    assert pipeline.validate(report)
