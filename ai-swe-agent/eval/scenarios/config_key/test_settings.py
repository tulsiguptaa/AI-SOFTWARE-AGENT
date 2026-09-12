from settings import get_timeout


def test_get_timeout_default():
    assert get_timeout() == 30


def test_get_timeout_override():
    assert get_timeout({"timeout_seconds": 5}) == 5
