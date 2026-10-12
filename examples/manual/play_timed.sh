#!/bin/bash
# Timed Them-side playback with real pauses for the manual conversation test.
# Plays the 5 per-line Alex clips, waiting AFTER each one for you to read the
# matching "You" line aloud. Ctrl-C stops playback.
#
# You read these lines aloud in the gaps:
#   1. Good to talk to you too.
#   2. Sure, happy to help.
#   3. I think the colors look good, but the blue one could be a bit darker.  (overlap Alex's 3rd)
#   4. I'll check the mobile spacing and send you notes after this.
#   5. Sounds good, talk tomorrow.

set -euo pipefail
OUT="spike/out/manual"

echo "== (1/5) Alex: design team intro — THEN YOU SPEAK =="
afplay "$OUT/them_1.wav"
echo ">>> Your turn: 'Good to talk to you too.'"; sleep 6

echo "== (2/5) Alex: thoughts on dashboard layout — THEN YOU SPEAK =="
afplay "$OUT/them_2.wav"
echo ">>> Your turn: 'Sure, happy to help.'"; sleep 6

echo "== (3/5) Alex: chart colors — SPEAK OVER THIS ONE =="
afplay "$OUT/them_3.wav" &
PID3=$!
echo ">>> Your turn (overlap Alex): 'I think the colors look good, but the blue one could be a bit darker.'"
wait "$PID3"; sleep 1

echo "== (4/5) Alex: mobile spacing — THEN YOU SPEAK =="
afplay "$OUT/them_4.wav"
echo ">>> Your turn: 'I'll check the mobile spacing and send you notes after this.'"; sleep 6

echo "== (5/5) Alex: really helpful, finalize tomorrow — THEN YOU SPEAK =="
afplay "$OUT/them_5.wav"
echo ">>> Your turn: 'Sounds good, talk tomorrow.'"; sleep 4

echo "done — you can stop the capture now (Ctrl-C in the recording window)."
