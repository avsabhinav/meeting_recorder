# T6 — Echo check: text-overlap between You (mic) and Them (system)

## What was built

`spike/echo_check.py` — scores how many "You" (mic) transcript segments appear
to contain remote-speaker text leaked into the mic (echo), using
`rapidfuzz.fuzz.token_ratio`.

- `echo_check.py <dir>` reads `<dir>/mic.segments.json` (You) and
  `<dir>/system.segments.json` (Them), schema `{"segments":[{start,end,text}]}`.
- Missing file → clear error to stderr, exit 1. Missing/invalid `segments`
  key → treated as empty list.
- For each You segment, `max_ratio` = max `token_ratio(you_text, them_text)`
  over all Them segments that time-overlap it (overlap > 0, `[start,end)`
  seconds). You segments overlapping no Them segment are skipped and counted
  separately.
- Reports (stdout only, no output files):
  - counts: total You, total Them, You overlapping ≥1 Them, overlapping none;
  - # You flagged as likely echo at thresholds **0.5 / 0.6 / 0.7**
    (flag if `max_ratio >= threshold * 100`);
  - up to 10 example pairs above 0.5 (highest first):
    `(start, YOU_text | THEM_text -> ratio)`;
  - distribution of `max_ratio` over overlapping You segments: mean and 90th
    percentile (numpy), plus count with `max_ratio == 100` exactly;
  - one-line heuristic threshold suggestion based on the observed
    distribution (prefers the strictest standard threshold that keeps flagged
    share ≤ 25%, else the loosest one, with all three shares printed).

## Self-check (synthetic test)

Setup in a temp dir (`$TMPDIR`):

```json
// mic.segments.json  (You)
{"segments":[
  {"start":0.0,"end":2.0,"text":"hello there friend"},
  {"start":5.0,"end":7.0,"text":"zebra quantum flux capacitor"}
]}

// system.segments.json  (Them)
{"segments":[
  {"start":1.0,"end":3.0,"text":"hello there friend"},
  {"start":5.5,"end":7.5,"text":"unrelated remote sentence about the quarterly budget review"}
]}
```

Segment 1: You text exactly equals a time-overlapping Them text
(`token_ratio` = 100). Segment 2: You text is token-disjoint from all Them
text (low ratio), but time-overlaps Them segment 2.

Command + output:

```console
$ spike/.venv/bin/python spike/echo_check.py "$D"
=== Echo check: text-overlap between You (mic) and Them (system) ===

Counts:
  total You segments:      2
  total Them segments:     2
  You overlapping >=1:     2
  You overlapping none:    0

Likely-echo You segments (max_ratio >= threshold):
  threshold 0.5: 1
  threshold 0.6: 1
  threshold 0.7: 1

Example pairs above 0.5 (top 1):
  (0.0s) 'hello there friend' | 'hello there friend'  -> 100.0

max_ratio distribution (overlapping You segments):
  mean:            66.1
  90th percentile: 93.2
  max_ratio == 100 exactly: 1

Heuristic suggestion: use threshold 0.5 (flags 50% of overlapping You segments at this bar,
vs 0.5/0.6/0.7 = 50%/50%/50%); raise it if non-echo lines are still being dropped.
exit=0
```

Result: **identical pair flagged at all thresholds (ratio 100); different
pair not flagged (ratio ~32)** — acceptance criteria met.

Also verified:
- missing files → `ERROR: required file not found: .../mic.segments.json`, exit 1;
- `{}` (no `segments` key) / empty `segments` → runs cleanly with zero counts, exit 0.

## Notes / caveats

- `token_ratio` ignores word order and shared function words; a "different"
  sentence sharing common words ("the", "about") can score ~55, so the
  synthetic negative uses token-disjoint text. Real-data threshold choice
  should be reviewed with actual transcript pairs (next step: run on
  `spike/out` capture dirs once transcribed).
- Heuristic is deliberately conservative: it reports the flagged share at
  each standard threshold and only recommends 0.7 when that flags ≤ 25% of
  overlapping You lines.
