from app.journal.execution_journal import ExecutionJournal, ExecutionRecord


def test_execution_journal_record():
    journal = ExecutionJournal()

    record = ExecutionRecord(
        request_id="test-001",
        symbol="BTC",
        status="FILLED",
        quantity=1.0,
        price=100000.0,
        timestamp="2026-09-10T00:00:00"
    )

    journal.record(record)

    assert journal.latest().symbol == "BTC"
    assert journal.latest().status == "FILLED"
