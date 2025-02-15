def test_create_training():
    training = Training(
        id=1,
        date_time=datetime.now(),
        duration=60,
        kind="Силовая",
        location="Зал 1",
        status="OPEN",
        max_participants=10
    ) 