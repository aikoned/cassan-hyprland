import importlib.util
import io
import json
import math
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "waybar/scripts/memory-pressure.py"
SPEC = importlib.util.spec_from_file_location("cassan_memory_pressure", SCRIPT)
MEMORY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MEMORY
SPEC.loader.exec_module(MEMORY)


def psi(some=0, full=0, *, some60=0, some300=0, full60=0, full300=0):
    return (
        f"some avg10={some} avg60={some60} avg300={some300} total=123456\n"
        f"full avg10={full} avg60={full60} avg300={full300} total=1234\n"
    )


MEMINFO = (
    "MemTotal:       16777216 kB\n"
    "MemFree:        1048576 kB\n"
    "MemAvailable:  12582912 kB\n"
    "SwapTotal:      2097152 kB\n"
    "SwapFree:       1572864 kB\n"
)
VMSTAT = "nr_free_pages 1234\npswpin 100\npswpout 200\n"


class Reader:
    root = Path("/isolated-proc-fixture")

    def __init__(self, **changes):
        self.files = {"pressure/memory": psi(), "meminfo": MEMINFO, "vmstat": VMSTAT}
        self.files.update(changes)
        self.calls = []

    def __call__(self, path):
        relative = path.relative_to(self.root).as_posix()
        self.calls.append(relative)
        value = self.files.get(relative)
        if isinstance(value, BaseException):
            raise value
        if value is None:
            raise FileNotFoundError(relative)
        return value

    def monitor(self):
        return MEMORY.PressureMonitor(self.root, self)


class Output(io.StringIO):
    def __init__(self):
        super().__init__()
        self.flushes = 0

    def flush(self):
        self.flushes += 1
        super().flush()


class ParserTests(unittest.TestCase):
    def test_psi_parses_all_windows_and_microsecond_totals(self):
        pressure = MEMORY.parse_psi(psi(2.5, 0.25, some60=1.5, some300=0.5, full60=0.2, full300=0.1))
        self.assertEqual(pressure.some, MEMORY.Averages(2.5, 1.5, 0.5, 123456))
        self.assertEqual(pressure.full, MEMORY.Averages(0.25, 0.2, 0.1, 1234))

    def test_psi_accepts_shuffled_fields_rows_and_whitespace(self):
        pressure = MEMORY.parse_psi(
            "\n full total=20 avg300=0.03\tavg10=0.01 avg60=0.02\n"
            " some avg60=0.2 total=100 avg300=0.3 avg10=0.1\n"
        )
        self.assertEqual(pressure.some.avg10, 0.1)
        self.assertEqual(pressure.full.avg300, 0.03)

    def test_psi_rejects_missing_duplicate_or_malformed_fields(self):
        cases = (
            "", psi().splitlines()[0], psi().splitlines()[1],
            psi().replace("avg300=0 ", "", 1),
            psi().replace("total=123456", "total=-1"),
            psi().replace("avg10=0", "avg10=0 avg10=0", 1),
            psi() + psi().splitlines()[0],
            psi().replace("some", "other", 1),
            psi().replace("avg10=0", "avg10", 1),
        )
        for text in cases:
            with self.subTest(text=text), self.assertRaises(MEMORY.ParseError):
                MEMORY.parse_psi(text)

    def test_psi_rejects_nonfinite_out_of_range_or_nonnumeric_percentages(self):
        for value in ("nan", "NaN", "inf", "-inf", "1e309", "-0.01", "100.01", "unknown"):
            with self.subTest(value=value), self.assertRaises(MEMORY.ParseError):
                MEMORY.parse_psi(psi(value))
        self.assertEqual(MEMORY.parse_psi(psi(100, 100)).some.avg10, 100)

    def test_uint64_counter_validation(self):
        self.assertEqual(MEMORY.unsigned(str((1 << 64) - 1)), (1 << 64) - 1)
        for value in ("", "-1", "+1", "1.0", "nan", "１２", str(1 << 64), "9" * 100):
            with self.subTest(value=value), self.assertRaises(MEMORY.ParseError):
                MEMORY.unsigned(value)

    def test_every_pressure_threshold_and_boundary(self):
        cases = (
            (0, 0, "low"), (0.9999, 0.09999, "low"),
            (1, 0, "moderate"), (0, 0.1, "moderate"),
            (9.9999, 0.99999, "moderate"),
            (10, 0, "high"), (0, 1, "high"), (100, 100, "high"),
        )
        for some, full, expected in cases:
            with self.subTest(some=some, full=full):
                self.assertEqual(MEMORY.pressure_class(MEMORY.parse_psi(psi(some, full))), expected)
        self.assertEqual(MEMORY.pressure_class(None), "unknown")

    def test_old_averages_do_not_override_current_class(self):
        pressure = MEMORY.parse_psi(psi(0, 0, some60=100, some300=100, full60=100, full300=100))
        self.assertEqual(MEMORY.pressure_class(pressure), "low")

    def test_meminfo_uses_available_and_computes_swap_occupancy(self):
        self.assertEqual(MEMORY.parse_meminfo(MEMINFO), MEMORY.MemoryStats(
            total_kib=16777216, available_kib=12582912,
            swap_total_kib=2097152, swap_used_kib=524288,
        ))

    def test_meminfo_partial_or_absent_fields_stay_unknown(self):
        self.assertEqual(MEMORY.parse_meminfo(""), MEMORY.MemoryStats())
        memory = MEMORY.parse_meminfo("MemTotal: 1024 kB\nMemFree: 999 kB\nSwapTotal: 2048 kB\n")
        self.assertEqual(memory.total_kib, 1024)
        self.assertIsNone(memory.available_kib)
        self.assertEqual(memory.swap_total_kib, 2048)
        self.assertIsNone(memory.swap_used_kib)

    def test_meminfo_rejects_bad_units_duplicates_and_impossible_values(self):
        cases = (
            "MemAvailable: -1 kB\n", "MemAvailable: 1 MB\n",
            "MemAvailable: 1.5 kB\n", "MemAvailable: 1 kB extra\n",
            "MemAvailable: 1 kB\nMemAvailable: 2 kB\n",
            "MemTotal: 1 kB\nMemAvailable: 2 kB\n",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(MEMORY.parse_meminfo(text).available_kib)
        self.assertIsNone(MEMORY.parse_meminfo("MemTotal: 0 kB\n").total_kib)
        self.assertIsNone(MEMORY.parse_meminfo("SwapTotal: 1 kB\nSwapFree: 2 kB\n").swap_used_kib)

    def test_zero_swap_is_distinct_from_missing_swap(self):
        memory = MEMORY.parse_meminfo("SwapTotal: 0 kB\nSwapFree: 0 kB\n")
        self.assertEqual((memory.swap_total_kib, memory.swap_used_kib), (0, 0))
        self.assertIsNone(MEMORY.parse_meminfo("").swap_used_kib)

    def test_vmstat_requires_both_valid_cumulative_page_counters(self):
        self.assertEqual(MEMORY.parse_vmstat(VMSTAT), (100, 200))
        for text in ("", "pswpin 2\n", "pswpin -1\npswpout 2\n", "pswpin 2 extra\npswpout 3\n",
                     VMSTAT + "pswpin 1\n", VMSTAT.replace("100", str(1 << 64))):
            with self.subTest(text=text), self.assertRaises(MEMORY.ParseError):
                MEMORY.parse_vmstat(text)


class HistoryTests(unittest.TestCase):
    def test_startup_has_only_observed_sample_not_fabricated_zeros(self):
        history = MEMORY.History()
        self.assertEqual(history.render(0), MEMORY.EMPTY * 12)
        history.add(0, 0)
        self.assertEqual(history.render(0), MEMORY.EMPTY * 11 + "▁")

    def test_bin_keeps_recent_high_peak_after_current_pressure_falls(self):
        history = MEMORY.History()
        history.add(0, 10)
        history.add(2, 0)
        self.assertEqual(history.render(2), MEMORY.EMPTY * 11 + "█")
        history.add(10, 0)
        self.assertEqual(history.render(10), MEMORY.EMPTY * 10 + "█▁")
        history.add(118, 0)
        self.assertEqual(history.render(118)[0], "█")
        history.add(120, 0)
        self.assertNotIn("█", history.render(120))

    def test_fixed_scale_clips_at_ten_percent(self):
        for value, symbol in ((0, "▁"), (5, "▅"), (10, "█"), (100, "█")):
            with self.subTest(value=value):
                history = MEMORY.History()
                history.add(0, value)
                self.assertEqual(history.render(0)[-1], symbol)

    def test_partial_gap_is_unmeasured_not_interpolated(self):
        history = MEMORY.History()
        history.add(0, 10)
        history.add(50, 0)
        graph = history.render(50)
        self.assertEqual(len(graph), 12)
        self.assertEqual(graph[6], "█")
        self.assertEqual(graph[-1], "▁")
        self.assertEqual(graph.count(MEMORY.EMPTY), 10)

    def test_suspend_sized_gap_expires_old_history(self):
        history = MEMORY.History()
        history.add(0, 10)
        history.add(121, None)
        self.assertEqual(history.render(121), MEMORY.EMPTY * 12)
        self.assertEqual(len(history.samples), 0)
        history.add(122, 0)
        self.assertEqual(history.render(122), MEMORY.EMPTY * 11 + "▁")

    def test_unknown_sample_preserves_prior_observations_without_adding_zero(self):
        history = MEMORY.History()
        history.add(0, 10)
        history.add(12, None)
        self.assertEqual(history.render(12), MEMORY.EMPTY * 10 + "█" + MEMORY.EMPTY)
        self.assertEqual(len(history.samples), 1)

    def test_history_has_constant_bound_and_prunes_by_elapsed_time(self):
        history = MEMORY.History()
        for sample in range(10000):
            history.add(sample * 2, sample % 11)
        self.assertLessEqual(len(history.samples), MEMORY.MAX_SAMPLES)
        self.assertTrue(all(19998 - timestamp < MEMORY.HISTORY_SECONDS for timestamp, _ in history.samples))
        self.assertEqual(len(history.render(19998)), 12)

    def test_backward_clock_clears_stale_history(self):
        history = MEMORY.History()
        history.add(100, 10)
        history.add(99, 0)
        self.assertEqual(history.render(99), MEMORY.EMPTY * 11 + "▁")

    def test_nonfinite_times_or_values_are_rejected(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MEMORY.History().add(value, 0)
            with self.subTest(value=value), self.assertRaises(ValueError):
                MEMORY.History().add(0, value)

    def test_linux_clock_includes_suspend_when_available(self):
        with mock.patch.object(MEMORY.time, "CLOCK_BOOTTIME", 77, create=True), \
                mock.patch.object(MEMORY.time, "clock_gettime", return_value=123.5) as clock:
            self.assertEqual(MEMORY.elapsed_clock(), 123.5)
            clock.assert_called_once_with(77)


class SwapRateTests(unittest.TestCase):
    def test_rates_require_two_samples_and_use_actual_elapsed_seconds(self):
        rates = MEMORY.SwapRates()
        self.assertIsNone(rates.update(0, (100, 200)))
        self.assertEqual(rates.update(2, (104, 206)), (2.0, 3.0, 2))
        self.assertEqual(rates.update(5, (110, 215)), (2.0, 3.0, 3))

    def test_cumulative_swap_counts_do_not_become_first_sample_rates(self):
        self.assertIsNone(MEMORY.SwapRates().update(0, (1000000, 2000000)))

    def test_unchanged_valid_counters_give_measured_zero_rates(self):
        rates = MEMORY.SwapRates()
        rates.update(0, (100, 200))
        self.assertEqual(rates.update(2, (100, 200)), (0.0, 0.0, 2))

    def test_reset_in_either_counter_drops_interval_and_recovers(self):
        for reset in ((1, 202), (102, 1)):
            with self.subTest(reset=reset):
                rates = MEMORY.SwapRates()
                rates.update(0, (100, 200))
                self.assertIsNone(rates.update(2, reset))
                self.assertEqual(rates.update(4, (reset[0] + 2, reset[1] + 4)), (1.0, 2.0, 2))

    def test_missing_sample_breaks_rate_chain(self):
        rates = MEMORY.SwapRates()
        rates.update(0, (100, 200))
        self.assertIsNone(rates.update(2, None))
        self.assertIsNone(rates.update(4, (108, 212)))
        self.assertEqual(rates.update(6, (110, 216)), (1.0, 2.0, 2))

    def test_long_gap_or_nonpositive_elapsed_resets_rate_baseline(self):
        for when in (0, -1, MEMORY.MAX_RATE_GAP + 0.01, 3600):
            with self.subTest(when=when):
                rates = MEMORY.SwapRates()
                rates.update(0, (100, 200))
                self.assertIsNone(rates.update(when, (110, 220)))
                self.assertEqual(rates.update(when + 2, (112, 224)), (1.0, 2.0, 2))


class MonitorTests(unittest.TestCase):
    def test_payload_has_fixed_width_graph_and_explicit_units_and_heuristics(self):
        reader = Reader()
        payload = reader.monitor().sample(0)
        self.assertEqual(payload["text"], "MEM " + MEMORY.EMPTY * 11 + "▁")
        self.assertEqual(len(payload["text"]), 16)
        self.assertEqual(payload["class"], "low")
        tooltip = payload["tooltip"]
        for phrase in ("10s 0.00%", "60s 0.00%", "300s 0.00%", "last 120s", "12 × 10s",
                       "maximum observed some avg10", "0–10%", "clipped", "no valid samples",
                       "heuristics", "not Apple's", "History resets on bar reload, including wallpaper changes",
                       "12.00 GiB / 16.00 GiB", "512.00 MiB / 2.00 GiB",
                       "Swap I/O: unavailable", "Click to open btop"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, tooltip)
        self.assertEqual(reader.calls, ["pressure/memory", "meminfo", "vmstat"])

    def test_tooltip_lines_fit_a_laptop_hover_popup(self):
        reader = Reader()
        for source in (psi(10, 1), None):
            with self.subTest(source=source):
                reader.files["pressure/memory"] = source
                payload = reader.monitor().sample(0)
                self.assertTrue(all(len(line) <= 95 for line in payload["tooltip"].splitlines()))

    def test_ram_usage_and_swap_occupancy_never_determine_pressure_class(self):
        reader = Reader(meminfo="MemTotal: 1000 kB\nMemAvailable: 1 kB\nSwapTotal: 999 kB\nSwapFree: 0 kB\n")
        self.assertEqual(reader.monitor().sample(0)["class"], "low")

    def test_missing_unreadable_partial_or_malformed_psi_is_unknown_and_recovers(self):
        for missing in (None, PermissionError("no access"), "", psi().splitlines()[0], psi("nan"), "bad"):
            with self.subTest(missing=missing):
                reader = Reader()
                reader.files["pressure/memory"] = missing
                monitor = reader.monitor()
                payload = monitor.sample(0)
                self.assertEqual(payload["class"], "unknown")
                self.assertEqual(payload["text"], "MEM?" + MEMORY.EMPTY * 12)
                self.assertIn("Current PSI unavailable", payload["tooltip"])
                reader.files["pressure/memory"] = psi(1)
                recovered = monitor.sample(2)
                self.assertEqual(recovered["class"], "moderate")
                self.assertTrue(recovered["text"].startswith("MEM "))

    def test_unknown_prefix_is_visible_while_old_high_history_remains(self):
        reader = Reader()
        reader.files["pressure/memory"] = psi(10)
        monitor = reader.monitor()
        monitor.sample(0)
        reader.files["pressure/memory"] = None
        payload = monitor.sample(2)
        self.assertEqual(payload["class"], "unknown")
        self.assertEqual(payload["text"], "MEM?" + MEMORY.EMPTY * 11 + "█")
        self.assertIn("Earlier valid history may remain", payload["tooltip"])

    def test_missing_optional_files_do_not_mask_valid_pressure(self):
        reader = Reader(meminfo=None, vmstat=None)
        payload = reader.monitor().sample(0)
        self.assertEqual(payload["class"], "low")
        self.assertIn("Available RAM: unavailable / unavailable", payload["tooltip"])
        self.assertIn("Swap used: unavailable / unavailable", payload["tooltip"])
        self.assertIn("Swap I/O: unavailable", payload["tooltip"])

    def test_no_swap_and_valid_zero_rates_are_reported_separately(self):
        reader = Reader(meminfo="SwapTotal: 0 kB\nSwapFree: 0 kB\n", vmstat="pswpin 0\npswpout 0\n")
        monitor = reader.monitor()
        first = monitor.sample(0)
        self.assertIn("none configured (0 KiB total)", first["tooltip"])
        self.assertIn("Swap I/O: unavailable", first["tooltip"])
        second = monitor.sample(2)
        self.assertIn("in 0.00 pages/s | out 0.00 pages/s over 2.00s", second["tooltip"])

    def test_swap_rates_use_page_units_and_reset_across_resume(self):
        reader = Reader()
        monitor = reader.monitor()
        monitor.sample(0)
        reader.files["vmstat"] = "pswpin 104\npswpout 206\n"
        payload = monitor.sample(2)
        self.assertIn("in 2.00 pages/s | out 3.00 pages/s over 2.00s", payload["tooltip"])
        resumed = monitor.sample(130)
        self.assertIn("Swap I/O: unavailable", resumed["tooltip"])
        self.assertEqual(resumed["text"], "MEM " + MEMORY.EMPTY * 11 + "▁")

    def test_oversized_or_non_text_injected_files_fail_closed(self):
        for source in ("x" * (MEMORY.MAX_FILE_CHARS + 1), b"not decoded", 123):
            with self.subTest(source_type=type(source)):
                reader = Reader()
                reader.files["pressure/memory"] = source
                self.assertEqual(reader.monitor().sample(0)["class"], "unknown")

    def test_kernel_reader_caps_input_and_rejects_non_ascii(self):
        with tempfile.TemporaryDirectory(prefix="memory-pressure-read-") as temporary:
            path = Path(temporary) / "input"
            path.write_text("x" * (MEMORY.MAX_FILE_CHARS + 1), encoding="ascii")
            with self.assertRaises(MEMORY.ParseError):
                MEMORY.kernel_text(path)
            path.write_bytes(b"\xff")
            with self.assertRaises(UnicodeError):
                MEMORY.kernel_text(path)


class StreamTests(unittest.TestCase):
    def test_once_emits_single_flushed_json_line_and_never_sleeps(self):
        output = Output()
        sleep = mock.Mock(side_effect=AssertionError("must not sleep"))
        result = MEMORY.stream(Reader().monitor(), output, once=True, clock=lambda: 0, sleep=sleep)
        self.assertEqual(result, 0)
        self.assertEqual(output.flushes, 1)
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertEqual(json.loads(output.getvalue())["class"], "low")
        self.assertIn("\\n", output.getvalue())
        self.assertNotIn("NaN", output.getvalue())
        sleep.assert_not_called()

    def test_continuous_output_flushes_every_two_second_sample_and_interrupts_cleanly(self):
        output = Output()
        clock = iter((0, 2, 4))
        sleeps = []

        def sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 3:
                raise KeyboardInterrupt

        result = MEMORY.stream(Reader().monitor(), output, clock=lambda: next(clock), sleep=sleep)
        self.assertEqual(result, 0)
        self.assertEqual(output.flushes, 3)
        self.assertEqual(sleeps, [2.0, 2.0, 2.0])
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(len(json.loads(line)["text"]) == 16 for line in lines))

    def test_broken_pipe_during_write_or_flush_closes_output_and_exits(self):
        for method in ("write", "flush"):
            with self.subTest(method=method):
                output = mock.Mock()
                getattr(output, method).side_effect = BrokenPipeError
                output.close.side_effect = BrokenPipeError
                result = MEMORY.stream(Reader().monitor(), output, once=True, clock=lambda: 0)
                self.assertEqual(result, 0)
                output.close.assert_called_once()

    def fixture_root(self, temporary):
        root = Path(temporary) / "proc"
        (root / "pressure").mkdir(parents=True)
        (root / "pressure/memory").write_text(psi(), encoding="ascii")
        (root / "meminfo").write_text(MEMINFO, encoding="ascii")
        (root / "vmstat").write_text(VMSTAT, encoding="ascii")
        return root

    def test_cli_once_reads_only_fixture_files_and_handles_missing_root(self):
        with tempfile.TemporaryDirectory(prefix="memory-pressure-cli-") as temporary:
            root = self.fixture_root(temporary)
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            result = subprocess.run([sys.executable, str(SCRIPT), "--once", "--proc-root", str(root)],
                                    capture_output=True, text=True, check=False, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertEqual(len(result.stdout.splitlines()), 1)
            self.assertEqual(json.loads(result.stdout)["class"], "low")
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(after, before)
            result = subprocess.run([sys.executable, str(SCRIPT), "--once", "--proc-root", str(root / "absent")],
                                    capture_output=True, text=True, check=False, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["class"], "unknown")

    def test_cli_flushes_before_exit_and_terminates_cleanly_on_sigterm(self):
        with tempfile.TemporaryDirectory(prefix="memory-pressure-term-") as temporary:
            root = self.fixture_root(temporary)
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--proc-root", str(root)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                ready, _, _ = select.select([process.stdout], [], [], 5)
                self.assertTrue(ready, "first JSON sample was not flushed")
                self.assertEqual(json.loads(process.stdout.readline())["class"], "low")
                process.terminate()
                _, errors = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, errors)
                self.assertEqual(errors, "")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate(timeout=5)

    def test_cli_broken_stdout_exits_without_shutdown_traceback(self):
        with tempfile.TemporaryDirectory(prefix="memory-pressure-pipe-") as temporary:
            root = self.fixture_root(temporary)
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--proc-root", str(root)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                ready, _, _ = select.select([process.stdout], [], [], 5)
                self.assertTrue(ready)
                json.loads(process.stdout.readline())
                process.stdout.close()
                process.wait(timeout=5)
                errors = process.stderr.read()
                process.stderr.close()
                self.assertEqual(process.returncode, 0, errors)
                self.assertEqual(errors, "")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
