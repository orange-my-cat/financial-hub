"""The service layer.

Services hold every business rule and every calculation, and are callable
without HTTP (§5.2.2). This is where the test suite spends its effort, and it
is the reason there is exactly one place where net worth is defined, one where
translation happens, and one where FIFO is computed.

Stage 0 holds only the shared vocabulary — errors and advisories. The money
primitives, rate lookup, translation and completeness services arrive at
Stage 1; net worth at Stage 2. Nothing is built ahead of that order, because
each stage exists so the next one can be tested.
"""
