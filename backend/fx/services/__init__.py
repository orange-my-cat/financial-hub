"""FX services.

Rate lookup and translation deliberately do **not** live here — they are in
`core`, because resolving a rate is a primitive every module reaches through and
must reach through (HLD §5.2.1). What belongs to `fx` is the rate table itself:
recording rates, charting them, and reporting which are missing or stale.
"""
