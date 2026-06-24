"""writer — turns a detected event into post copy via Claude (the one LLM step).

Takes a structured, already-verified datapoint and writes a punchy, accurate post. Must
never invent numbers — it only phrases what the detector found.
"""
