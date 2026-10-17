# SW Timecode Generator

Generate and parse SMPTE timecodes for 24, 25, 30, and 29.97 fps, with drop-frame support for the two 30 Hz rates. Standard library only.

## Usage

```python
from sw_timecode_generator import Timecode, parse_timecode, frames_to_timecode

tc = Timecode(1, 2, 3, 4, frame_rate=24, drop_frame=False)
print(str(tc))  # 01:02:03:04

parsed = parse_timecode("00:01:00;00", 29.97, drop_frame=True)
print(parsed.total_frames())  # 1798

offset = parsed.add_frames(2)
print(str(offset))  # 00:01:00;02
```

The library exports: `Timecode`, `parse_timecode`, `frames_to_timecode`, `timecode_to_frames`.

## Why this exists

Syncing audio to video requires counting frames, not seconds. A 29.97 fps drop-frame timecode is not the same as counting 29.97 frames per second linearly -- the drop pattern keeps the displayed time within about 3.6 frames per hour of wall-clock time. This library does that bookkeeping exactly and nothing else.

The trade-off: only four frame rates are supported (24, 25, 30, 29.97). Drop-frame is only supported for 29.97 and 30 fps because those are the only rates whose drop cadence is implemented. If you need 59.94 or 23.98, this library will refuse rather than guess.

## Edge cases you will hit

- Timecodes above `23:59:59:<last frame>` raise `ValueError`. The library does not wrap past midnight.
- `parse_timecode` accepts both `:` and `;` as separators, but the `drop_frame` flag is set by the argument, not inferred from the separator. A drop-frame timecode parsed as non-drop will still parse -- it just won't apply drop-frame arithmetic.
- Frame rates are matched as dict keys, so pass `29.97` (a float) or `24`/`25`/`30` (ints) exactly. `29.970000001` is not recognized.
- Negative frame offsets raise rather than wrap to the previous day.

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

## Performance

The window keeps a bounded buffer, so `push` is constant time and memory does not
grow with the length of the stream. `peak` and `trough` are linear in the window
size, which is the trade that keeps `push` cheap.

