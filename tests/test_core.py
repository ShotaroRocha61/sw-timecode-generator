import unittest

from sw_timecode_generator.core import (
    Timecode,
    parse_timecode,
    frames_to_timecode,
    timecode_to_frames,
)


class TestBasicConstruction(unittest.TestCase):
    def test_zero(self):
        tc = Timecode(0, 0, 0, 0, frame_rate=24, drop_frame=False)
        self.assertEqual(str(tc), "00:00:00:00")

    def test_simple_display_24(self):
        tc = Timecode(1, 2, 3, 4, frame_rate=24, drop_frame=False)
        self.assertEqual(str(tc), "01:02:03:04")

    def test_drop_frame_uses_semicolon(self):
        tc = Timecode(0, 1, 0, 0, frame_rate=29.97, drop_frame=True)
        self.assertEqual(str(tc), "00:01:00;00")


class TestValidation(unittest.TestCase):
    def test_hours_out_of_range(self):
        with self.assertRaises(ValueError):
            Timecode(24, 0, 0, 0, frame_rate=24, drop_frame=False)

    def test_minutes_out_of_range(self):
        with self.assertRaises(ValueError):
            Timecode(0, 60, 0, 0, frame_rate=24, drop_frame=False)

    def test_seconds_out_of_range(self):
        with self.assertRaises(ValueError):
            Timecode(0, 0, 60, 0, frame_rate=24, drop_frame=False)

    def test_frames_out_of_range_24(self):
        with self.assertRaises(ValueError):
            Timecode(0, 0, 0, 24, frame_rate=24, drop_frame=False)

    def test_frames_out_of_range_25(self):
        with self.assertRaises(ValueError):
            Timecode(0, 0, 0, 25, frame_rate=25, drop_frame=False)

    def test_unsupported_rate(self):
        with self.assertRaises(ValueError):
            Timecode(0, 0, 0, 0, frame_rate=48, drop_frame=False)

    def test_drop_unsupported_rate(self):
        with self.assertRaises(ValueError):
            Timecode(0, 0, 0, 0, frame_rate=24, drop_frame=True)


class TestRoundTripNonDrop(unittest.TestCase):
    def test_24_round_trip(self):
        for total in [0, 1, 23, 24, 47, 48, 1439, 1440, 86400 - 1]:
            tc = frames_to_timecode(total, 24, drop_frame=False)
            self.assertEqual(timecode_to_frames(tc), total, f"failed at {total}")

    def test_25_round_trip(self):
        for total in [0, 1, 25, 1500, 3600 * 25 - 1]:
            tc = frames_to_timecode(total, 25, drop_frame=False)
            self.assertEqual(timecode_to_frames(tc), total)

    def test_30_nondrop_round_trip(self):
        for total in [0, 30, 1800, 64800]:
            tc = frames_to_timecode(total, 30, drop_frame=False)
            self.assertEqual(timecode_to_frames(tc), total)


class TestDropFrame(unittest.TestCase):
    def test_minute_boundary_skips_two_frames(self):
        # At 29.97 drop, 00:01:00;00 is 2 frames "earlier" than the naive count.
        tc = parse_timecode("00:01:00;00", 29.97, drop_frame=True)
        naive = 1 * 60 * 30  # one minute at 30 fps
        self.assertEqual(timecode_to_frames(tc), naive - 2)

    def test_tenth_minute_no_drop(self):
        # 00:10:00;00 should have dropped 9*2 = 18 frames total.
        tc = parse_timecode("00:10:00;00", 29.97, drop_frame=True)
        naive = 10 * 60 * 30
        self.assertEqual(timecode_to_frames(tc), naive - 18)

    def test_round_trip_2997_drop(self):
        # Check a representative set including minute and 10-minute boundaries.
        totals = [0, 1, 1798, 1799, 1800, 1801, 1802, 17982, 17983, 17984, 17985]
        for total in totals:
            tc = frames_to_timecode(total, 29.97, drop_frame=True)
            self.assertEqual(timecode_to_frames(tc), total, f"failed at {total}")


class TestParse(unittest.TestCase):
    def test_parse_basic(self):
        tc = parse_timecode("01:02:03:04", 24)
        self.assertEqual((tc.hours, tc.minutes, tc.seconds, tc.frames), (1, 2, 3, 4))

    def test_parse_accepts_semicolon_separator(self):
        tc = parse_timecode("01;02;03;04", 24)
        self.assertEqual((tc.hours, tc.minutes, tc.seconds, tc.frames), (1, 2, 3, 4))

    def test_parse_strips_whitespace(self):
        tc = parse_timecode("  01:02:03:04  ", 24)
        self.assertEqual(tc.hours, 1)

    def test_parse_bad_field_count(self):
        with self.assertRaises(ValueError):
            parse_timecode("01:02:03", 24)

    def test_parse_non_integer(self):
        with self.assertRaises(ValueError):
            parse_timecode("01:02:03:0x", 24)

    def test_parse_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_timecode("00:00:00:24", 24)

    def test_parse_non_string(self):
        with self.assertRaises(TypeError):
            parse_timecode(1234, 24)


class TestArithmetic(unittest.TestCase):
    def test_add_frames_simple(self):
        tc = Timecode(0, 0, 0, 0, frame_rate=24, drop_frame=False)
        result = tc.add_frames(25)
        self.assertEqual(str(result), "00:00:01:01")

    def test_subtract_frames_simple(self):
        tc = Timecode(0, 0, 1, 0, frame_rate=24, drop_frame=False)
        result = tc.subtract_frames(1)
        self.assertEqual(str(result), "00:00:00:23")

    def test_subtract_below_zero_raises(self):
        tc = Timecode(0, 0, 0, 0, frame_rate=24, drop_frame=False)
        with self.assertRaises(ValueError):
            tc.subtract_frames(1)

    def test_add_frames_exceeds_day_raises(self):
        tc = Timecode(23, 59, 59, 23, frame_rate=24, drop_frame=False)
        with self.assertRaises(ValueError):
            tc.add_frames(1)


class TestImmutability(unittest.TestCase):
    def test_frozen_dataclass(self):
        tc = Timecode(0, 0, 0, 0, frame_rate=24, drop_frame=False)
        with self.assertRaises(Exception):
            tc.hours = 1  # type: ignore[misc]


class TestFramesToTimecodeValidation(unittest.TestCase):
    def test_negative_total_raises(self):
        with self.assertRaises(ValueError):
            frames_to_timecode(-1, 24)

    def test_non_int_total_raises(self):
        with self.assertRaises(TypeError):
            frames_to_timecode(1.0, 24)  # type: ignore[arg-type]

    def test_exceeds_24h_raises(self):
        # 24 * 3600 * 24 = 8294400 frames is exactly 24 hours at 24 fps.
        with self.assertRaises(ValueError):
            frames_to_timecode(24 * 3600 * 24, 24)


if __name__ == "__main__":
    unittest.main()
