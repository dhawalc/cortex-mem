"""Fisher exact tests, so 'the difference means something' is a number."""

from math import comb


def fisher_two_sided(a, b, c, d):
    """2x2: [[a, b], [c, d]]. Returns two-sided p."""
    n = a + b + c + d
    row1, col1 = a + b, a + c

    def prob(x):
        return comb(row1, x) * comb(n - row1, col1 - x) / comb(n, col1)

    observed = prob(a)
    total = 0.0
    low = max(0, col1 - (n - row1))
    high = min(row1, col1)
    for x in range(low, high + 1):
        p = prob(x)
        if p <= observed + 1e-12:
            total += p
    return min(1.0, total)


def report(label, a_hits, a_n, b_hits, b_n):
    p = fisher_two_sided(a_hits, a_n - a_hits, b_hits, b_n - b_hits)
    verdict = "significant" if p < 0.05 else "NOT significant"
    print(
        f"  {label:<44} A {a_hits}/{a_n} ({a_hits / a_n:.0%})  "
        f"B {b_hits}/{b_n} ({b_hits / b_n:.0%})   p={p:.4f}  {verdict}"
    )


print("=" * 92)
print("qwen3:8b  n=20/arm")
print("=" * 92)
report("set claim_key", 0, 20, 7, 20)
report("declared supersedes", 0, 20, 0, 20)
report("left two current values", 20, 20, 19, 20)

print()
print("=" * 92)
print("Claude Code")
print("=" * 92)
print("  (fill from cc_analyze once the extra arm-A trials land)")
