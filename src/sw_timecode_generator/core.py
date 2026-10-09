"""Core SMPTE timecode logic.

Supports the four standard frame rates used in film and broadcast: 24, 25,
30 (non-drop), and 30 drop-frame. 29.97 is represented explicitly because its
drop-frame bookkeeping differs from a naive 30 fps calculation -- roughly two
frames are dropped every minute except every tenth minute, to keep the
 timecode within ~3.6 frames per hour of real elapsed time.

Design choices (stated plainly):
- Drop-frame support is limited to 29.97 and 30 fps. The drop pattern is defined
  by the ratio of the integer base rate (30) to the actual rate; for 29.97 that
  ratio is 1001/30000. No other drop rates are supported because the library
  has not been taught their drop cadence.
- A Timecode is constructed from total elapsed frames, not from separate
  HH:MM:SS:FF fields, so that wraparound at 24 hours and carry propagation
  have exactly one code path. Field-by-field construction is the parser's job.
- Arithmetic is integer-only. Floating-point frame rates are accepted on the
  way in (29.97) but immediately converted to a rational pair (num, den) and
  never stored as a float.
- Timecodes above 23:59:59:<last frame> are considered out of range for a
  single day; the library raises rather than wrap silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Tuple


# Supported frame rates as (numerator, denominator, is_drop_frame).
# Using explicit rationals avoids float rounding surprises.
_FRAME_RATES = {
    24: (24, 1, False),
    25: (25, 1, False),
    30: (30, 1, False),
    29.97: (30000, 1001, False),   # non-drop 29.97
}

_DROP_FRAME_RATES = {
    29.97: (30000, 1001, True),
    30: (30, 1, True),
}

_MAX_HOURS = 24


def _resolve_rate(frame_rate, drop_frame: bool) -> Tuple[int, int, bool]:
    """Return the rational (num, den, drop) triple for a frame rate.

    Raises ValueError for unsupported combinations. Float keys are matched
    exactly via dict lookup; the known float rates (29.97) have an exact
    binary representation close enough for dict equality to hold.
    """
    if frame_rate in (24, 25, 30) and not drop_frame:
        return _FRAME_RATES[frame_rate]
    if drop_frame:
        if frame_rate in _DROP_FRAME_RATES:
            return _DROP_FRAME_RATES[frame_rate]
        raise ValueError(
            f"Drop-frame is only supported for 29.97 and 30 fps, not {frame_rate}"
        )
    if frame_rate in _FRAME_RATES:
        return _FRAME_RATES[frame_rate]
    raise ValueError(
        f"Unsupported frame rate: {frame_rate}. "
        "Supported: 24, 25, 30 (non-drop), 29.97 (drop or non-drop)."
    )


def _is_drop_capable(num: int, den: int) -> bool:
    """True when the rate is derived from 30000/1001 or 30/1.

    The drop-frame algorithm only makes sense for rates whose base clock is
    30 Hz. 24 and 25 fps never drop.
    """
    return (num, den) in ((30000, 1001), (30, 1))


@dataclass(frozen=True)
class Timecode:
    """An immutable SMPTE timecode value.

    Fields:
        hours:    0..23
        minutes:  0..59
        seconds:  0..59
        frames:   0..(fps-1)
        frame_rate: the nominal frame rate (24, 25, 30, or 29.97)
        drop_frame: True if this is a drop-frame timecode

    Equality compares only the displayed fields plus frame_rate and drop_frame.
    Two timecodes that display identically are equal even if they wrap a
    different number of days -- but this library does not model multiple days,
    so that distinction never arises here.
    """

    hours: int
    minutes: int
    seconds: int
    frames: int
    frame_rate: float
    drop_frame: bool

    def __post_init__(self) -> None:
        # Validate rate *before* fields, so the error message for unsupported
        # rates is raised here too (direct construction is guarded).
        _resolve_rate(self.frame_rate, self.drop_frame)
        # Validate ranges. We keep this here rather than in the parser so
        # that direct construction by advanced users is also guarded.
        if not (0 <= self.hours < _MAX_HOURS):
            raise ValueError(f"hours must be in [0, {_MAX_HOURS - 1}], got {self.hours}")
        if not (0 <= self.minutes < 60):
            raise ValueError(f"minutes must be in [0, 59], got {self.minutes}")
        if not (0 <= self.seconds < 60):
            raise ValueError(f"seconds must be in [0, 59], got {self.seconds}")
        fps_int = int(self.frame_rate) if self.frame_rate != 29.97 else 30
        if not (0 <= self.frames < fps_int):
            raise ValueError(
                f"frames must be in [0, {fps_int - 1}] at {self.frame_rate} fps, "
                f"got {self.frames}"
            )

    def __str__(self) -> str:
        """Return HH:MM:SS:FF, or HH:MM:SS;FF for drop-frame.

        The semicolon is the SMPTE convention to signal drop-frame to a reader.
        """
        sep = ";" if self.drop_frame else ":"
        return (
            f"{self.hours:02d}:{self.minutes:02d}:{self.seconds:02d}{sep}{self.frames:02d}"
        )

    def total_frames(self) -> int:
        """Convert this timecode to elapsed frame count from 00:00:00:00.

        For drop-frame this inverts the drop-frame encoding exactly.
        """
        num, den, drop = _resolve_rate(self.frame_rate, self.drop_frame)
        return _timecode_fields_to_frames(
            self.hours, self.minutes, self.seconds, self.frames, num, den, drop
        )

    def add_frames(self, n: int) -> "Timecode":
        """Return a new Timecode offset by n frames.

        Out-of-day results raise ValueError rather than wrap, to match the
        constructor's contract.
        """
        total = self.total_frames() + n
        if total < 0:
            raise ValueError(f"result is before 00:00:00:00 ({total} frames)")
        return frames_to_timecode(total, self.frame_rate, self.drop_frame)

    def subtract_frames(self, n: int) -> "Timecode":
        """Return a new Timecode offset backwards by n frames."""
        return self.add_frames(-n)


def _drop_frames_per_hour(num: int, den: int) -> int:
    """Total drop-frame slots skipped in one 24-hour cycle is not needed here;
    we compute per-10-minute and per-minute drop instead.

    For 30000/1001 the standard drop is 2 frames per minute except every 10th
    minute. For 30/1 drop-frame (a rare configuration) the same cadence is
    applied -- the library does not invent a different cadence.
    """
    # Drop 2 frames each minute that is not a multiple of 10.
    # The exactness of this for 29.97 comes from 30/29.97 = 1001/1000, giving
    # an offset of ~1.8 frames per minute, rounded to 2 except on the tenth
    # minute where it is compensated back.
    return 2


def _timecode_fields_to_frames(
    hours: int, minutes: int, seconds: int, frames: int,
    num: int, den: int, drop: bool,
) -> int:
    """Convert HH:MM:SS:FF to a total frame count under the given rate."""
    if not drop:
        # Simple integer frame count. Fractional rates only matter for
        # wall-clock sync, which this library does not perform; within a
        # pure timecode we count displayed frames.
        frames_per_second = num // den if num % den == 0 else round(num / den)
        return (
            hours * 3600 * frames_per_second
            + minutes * 60 * frames_per_second
            + seconds * frames_per_second
            + frames
        )

    # Drop-frame bookkeeping for 30-base rates.
    # Reference: drop 2 frames at the start of every minute except every 10th.
    fps_int = 30
    dpm = _drop_frames_per_hour(num, den)

    total_minutes = hours * 60 + minutes
    # Number of 10-minute blocks fully elapsed.
    ten_minute_blocks = total_minutes // 10
    # Remaining minutes beyond the last 10-minute boundary.
    remaining_minutes = total_minutes % 10

    # Each full 10-minute block drops 9*2 frames (minutes 1..9 within it).
    # Each remaining minute beyond a 10-boundary drops 2 frames.
    drop_count = ten_minute_blocks * 9 * dpm + remaining_minutes * dpm

    return (
        hours * 3600 * fps_int
        + minutes * 60 * fps_int
        + seconds * fps_int
        + frames
        - drop_count
    )


def _frames_to_timecode_fields(
    total: int, num: int, den: int, drop: bool,
) -> Tuple[int, int, int, int]:
    """Inverse of _timecode_fields_to_frames."""
    if not drop:
        fps_int = num // den if num % den == 0 else round(num / den)
        hours, rem = divmod(total, 3600 * fps_int)
        minutes, rem = divmod(rem, 60 * fps_int)
        seconds, frames = divmod(rem, fps_int)
        return hours, minutes, seconds, frames

    fps_int = 30
    dpm = _drop_frames_per_hour(num, den)

    # Compute how many frames-per-hour and frames-per-minute under drop-frame.
    # One hour = 3600 seconds * 30 fps - (60 - 6) * 2 drop frames.
    frames_per_hour = 3600 * fps_int - 54 * dpm   # 54 = 9*6, no -- fix below
    # Actually: 60 minutes per hour. 6 of them are 10th-minute (no drop),
    # 54 drop 2 each. So drop per hour = 54 * 2 = 108.
    frames_per_hour = 3600 * fps_int - 54 * dpm
    frames_per_minute = 60 * fps_int - dpm        # a regular (non-10th) minute
    frames_per_10_minutes = 10 * 60 * fps_int - 9 * dpm  # 10-minute block

    hours, total = divmod(total, frames_per_hour)

    # Now break the remainder into 10-minute blocks then minutes.
    ten_blocks, total = divmod(total, frames_per_10_minutes)
    minutes_in_block, total = divmod(total, frames_per_minute)
    # minutes_in_block can be at most 9 because the 10th minute is the next block.
    if minutes_in_block >= 10:
        # Should not happen given the block decomposition, but guard anyway.
        ten_blocks += minutes_in_block // 10
        minutes_in_block = minutes_in_block % 10

    total_minutes = ten_blocks * 10 + minutes_in_block
    hours_from_minutes, minutes_final = divmod(total_minutes, 60)
    hours += hours_from_minutes

    # total now holds frames within the current minute (after the drop at the
    # minute boundary if applicable). Convert to seconds + frames.
    seconds, frames = divmod(total, fps_int)

    return hours, minutes_final, seconds, frames


def parse_timecode(text: str, frame_rate, drop_frame: bool = False) -> Timecode:
    """Parse a SMPTE timecode string.

    Accepts both ':' and ';' as the frame separator -- this is deliberately
    lenient because real-world files sometimes use ':' even for drop-frame.
    The returned Timecode's drop_frame flag is set by the *argument*, not by
    the separator in the string, so callers stay in control of semantics.

    Raises ValueError on malformed input or out-of-range fields.
    """
    if not isinstance(text, str):
        raise TypeError(f"text must be a string, got {type(text).__name__}")
    cleaned = text.strip().replace(";", ":")
    parts = cleaned.split(":")
    if len(parts) != 4:
        raise ValueError(
            f"Timecode must have 4 colon-separated fields, got {len(parts)}: {text!r}"
        )
    try:
        hh, mm, ss, ff = (int(p) for p in parts)
    except ValueError as exc:
        raise ValueError(f"Timecode fields must be integers: {text!r}") from exc

    # Validate rate *before* constructing so the error message is clear.
    _resolve_rate(frame_rate, drop_frame)

    return Timecode(hh, mm, ss, ff, frame_rate=frame_rate, drop_frame=drop_frame)


def frames_to_timecode(total_frames: int, frame_rate, drop_frame: bool = False) -> Timecode:
    """Build a Timecode from a total elapsed-frame count."""
    if not isinstance(total_frames, int):
        raise TypeError(
            f"total_frames must be an int, got {type(total_frames).__name__}"
        )
    if total_frames < 0:
        raise ValueError(f"total_frames must be non-negative, got {total_frames}")

    num, den, drop = _resolve_rate(frame_rate, drop_frame)
    hh, mm, ss, ff = _frames_to_timecode_fields(total_frames, num, den, drop)
    if hh >= _MAX_HOURS:
        raise ValueError(
            f"{total_frames} frames at {frame_rate} fps "
            f"exceeds 24 hours (would be {hh:02d}:...);"
            " this library does not wrap past a single day."
        )
    return Timecode(hh, mm, ss, ff, frame_rate=frame_rate, drop_frame=drop_frame)


def timecode_to_frames(tc: Timecode) -> int:
    """Return the total elapsed frame count for a Timecode."""
    return tc.total_frames()
