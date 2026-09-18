"""Shared statistics helpers: mean and median.

Stdlib only. Contract (task t-stats spec §3):
- mean(values): empty sequence -> ValueError; otherwise sum/len as float.
- median(values): does not modify the input; empty -> ValueError;
  odd length -> middle element (original type preserved);
  even length -> mean of the two middle elements (float).
"""


def mean(values):
    """Arithmetic mean of a numeric sequence as a float."""
    count = len(values)
    if count == 0:
        raise ValueError("mean of empty sequence is undefined")
    return sum(values) / count


def median(values):
    """Median of a numeric sequence without modifying the input."""
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("median of empty sequence is undefined")
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2
