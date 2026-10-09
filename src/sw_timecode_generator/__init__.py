"""SW Timecode Generator.

A focused, dependency-free SMPTE timecode library.
"""

from .core import Timecode, parse_timecode, frames_to_timecode, timecode_to_frames

__all__ = [
    "Timecode",
    "parse_timecode",
    "frames_to_timecode",
    "timecode_to_frames",
]

__version__ = "1.0.0"
