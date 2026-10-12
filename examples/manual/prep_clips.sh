#!/bin/bash
# Timed Them-side playback for the manual conversation test.
# Plays the 5 "Alex" lines one at a time with a pause after each, so you can
# read your matching "You" line aloud in the gap. Ctrl-C stops playback.
#
# The TTS is one continuous m4a; we slice it by line offsets. To keep it simple
# and robust, we play the whole file once per "round" is wrong (back-to-back),
# so instead we extract/split into 5 short clips at fixed times.
# Simplest reliable approach: stop between rounds by playing the full file but
# pausing a fixed budget. Since we cannot count on exact slicing, we instead
# let you drive timing: this script prints which line is playing and waits.
#
# This file just plays the full clip and relies on the operator to time responses
# during the natural sentence breaks — but the clip has NO internal gaps either.
# To create real gaps we need per-line audio. We'll generate 5 short wavs now.

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
OUT="spike/out/manual"

echo "Building 5 per-line Alex clips with say ..."
L1="Hi, this is Alex from the design team. Thanks for making time today."
L2="I wanted to get your thoughts on the new dashboard layout before we ship it on Friday."
L3="Do you think the chart colors are clear enough, or should we make them stronger?"
L4="One more thing, could you also look at the spacing on the mobile view?"
L5="Great, that's really helpful. I'll pass that on and we can finalize tomorrow."

i=1
for line in "$L1" "$L2" "$L3" "$L4" "$L5"; do
  say -v Samantha -o "$OUT/them_$i.wav" --data-format=LEI16@16000 "$line"
  i=$((i+1))
done
echo "Built them_1..them_5.wav in $OUT"
