import pytest

from receipts import discount_applied


@pytest.mark.parametrize(
    "fare, paid, expected",
    [
        (12620, 11358, 1262),
        (12620, 12620, 0),
        (12620, 50, 12570),
        (100, 200, 0),
    ],
)
def test_discount_applied(fare, paid, expected):
    assert discount_applied(fare, paid) == expected