from playlist import get_last_n


def test_get_last_two():
    assert get_last_n([1, 2, 3, 4, 5], 2) == [4, 5]


def test_get_last_one():
    assert get_last_n(["a", "b", "c"], 1) == ["c"]


def test_get_last_n_larger_than_list():
    assert get_last_n([1, 2], 5) == [1, 2]
