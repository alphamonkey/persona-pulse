"""publish — pluggable publishers behind one interface.

Bluesky (atproto) first; X / Threads / Mastodon drop in behind the same interface.
Idempotent: never double-post the same event (key on a stable event id).
"""
