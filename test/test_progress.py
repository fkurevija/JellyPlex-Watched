from src import progress


def test_progress_logger_reports_estimated_time_remaining(monkeypatch):
    messages = []
    current_time = 0.0
    monkeypatch.setattr(progress.logger, "info", lambda *args: messages.append(args))
    monkeypatch.setattr(progress, "monotonic", lambda: current_time)
    reporter = progress.ProgressLogger("plex-moria", "Scanning Movies", 10)

    reporter.update(0)
    current_time = 2.0
    reporter.update(2)
    current_time = 5.0
    reporter.update(5)
    reporter.update(10)

    assert messages == [
        (
            "{}: {} progress: {}/{} (time remaining: {})",
            "plex-moria",
            "Scanning Movies",
            0,
            10,
            "calculating",
        ),
        (
            "{}: {} progress: {}/{} (time remaining: {})",
            "plex-moria",
            "Scanning Movies",
            2,
            10,
            "~8 sec",
        ),
        (
            "{}: {} progress: {}/{} (time remaining: {})",
            "plex-moria",
            "Scanning Movies",
            5,
            10,
            "~5 sec",
        ),
        (
            "{}: {} progress: {}/{} (time remaining: {})",
            "plex-moria",
            "Scanning Movies",
            10,
            10,
            "~0 sec",
        ),
    ]


def test_progress_logger_formats_minutes_and_seconds(monkeypatch):
    messages = []
    monkeypatch.setattr(progress.logger, "info", lambda *args: messages.append(args))
    monkeypatch.setattr(progress, "monotonic", lambda: 0.0)
    reporter = progress.ProgressLogger("plex-scottflix", "Scanning Movies", 100)

    reporter.update(0)
    monkeypatch.setattr(progress, "monotonic", lambda: 10.0)
    reporter.update(10)

    assert messages[-1][-1] == "~1 min, 30 sec"


def test_progress_logger_marks_empty_work_complete(monkeypatch):
    messages = []
    monkeypatch.setattr(progress.logger, "info", lambda *args: messages.append(args))
    reporter = progress.ProgressLogger("jellyfin-main", "Scanning Shows", 0)

    reporter.update(0)

    assert messages == [
        (
            "{}: {} progress: {}/{} (time remaining: {})",
            "jellyfin-main",
            "Scanning Shows",
            0,
            0,
            "~0 sec",
        )
    ]
