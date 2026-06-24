"""scheduler — the loop and cadence.

Runs detect -> write -> publish on a schedule with a per-day rate cap; pulls engagement
back. Deploy via systemd, like kalshi-edge.
"""
