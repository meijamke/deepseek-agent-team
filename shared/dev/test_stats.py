"""Self-tests for shared/dev/stats.py (stdlib only).

Run directly:  python3.10 shared/dev/test_stats.py
All assertions pass and the process exits with code 0.
"""

import stats


def test_empty_raises():
    """Empty list: both mean and median must raise ValueError."""
    for fn in (stats.mean, stats.median):
        try:
            fn([])
        except ValueError:
            pass
        else:
            raise AssertionError("%s([]) should raise ValueError" % fn.__name__)


def test_mean():
    assert stats.mean([1, 2, 3, 4]) == 2.5
    assert stats.mean([2, 4]) == 3.0
    assert stats.mean([1, 2, 3]) == 2.0
    assert stats.mean([5]) == 5.0


def test_median_odd():
    assert stats.median([1, 2, 3]) == 2
    assert stats.median([3, 1, 2]) == 2
    assert stats.median([5]) == 5


def test_median_even():
    assert stats.median([1, 2, 3, 4]) == 2.5
    assert stats.median([1, 2]) == 1.5
    assert stats.median([4, 1, 3, 2]) == 2.5


def test_median_does_not_mutate_input():
    values = [3, 1, 2]
    stats.median(values)
    assert values == [3, 1, 2]


def main():
    tests = [
        test_empty_raises,
        test_mean,
        test_median_odd,
        test_median_even,
        test_median_does_not_mutate_input,
    ]
    for t in tests:
        t()
    print("all %d test groups passed" % len(tests))


if __name__ == "__main__":
    main()
