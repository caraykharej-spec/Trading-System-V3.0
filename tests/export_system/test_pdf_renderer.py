from app.export_system.pdf_renderer import PDFRenderer


def test_pdf_renderer_creates_document():
    renderer = PDFRenderer()
    result = renderer.render("performance", "performance_report.pdf")

    assert result.report_type == "performance"
    assert result.filename == "performance_report.pdf"
