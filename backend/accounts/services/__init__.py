"""Account services.

`net_worth` is the single implementation of BR-04. `slices` partitions its
output rather than summing anything itself, so every slice totals to the same
figure by construction. `lifecycle` holds the rules about an account's own
state: dormancy, closure, reclassification and the one case where deletion is
permitted.
"""
