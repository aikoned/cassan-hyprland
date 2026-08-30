#!/usr/bin/env python3
"""Stream read-only Linux memory-pressure history to a Waybar custom module."""

import argparse
from collections import deque
from dataclasses import dataclass
import json
import math
from pathlib import Path
import signal
import sys
import time


SAMPLE_SECONDS = 2.0
HISTORY_SECONDS = 120.0
COLUMNS = 12
BUCKET_SECONDS = HISTORY_SECONDS / COLUMNS
MAX_SAMPLES = int(HISTORY_SECONDS / SAMPLE_SECONDS) + 1
MAX_RATE_GAP = SAMPLE_SECONDS * 3
MAX_FILE_CHARS = 131072
MAX_COUNTER = (1 << 64) - 1
SPARKLINE = "▁▂▃▄▅▆▇█"
EMPTY = "·"


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Averages:
    avg10: float
    avg60: float
    avg300: float
    total: int


@dataclass(frozen=True)
class Pressure:
    some: Averages
    full: Averages


@dataclass(frozen=True)
class MemoryStats:
    total_kib: int | None = None
    available_kib: int | None = None
    swap_total_kib: int | None = None
    swap_used_kib: int | None = None


def unsigned(value):
    if not value or len(value) > 20 or not value.isascii() or not value.isdecimal():
        raise ParseError("invalid unsigned counter")
    number = int(value)
    if number > MAX_COUNTER:
        raise ParseError("counter exceeds uint64")
    return number


def percentage(value):
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise ParseError("invalid percentage") from error
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise ParseError("percentage outside 0–100")
    return number


def parse_psi(text):
    rows = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue
        name = fields[0]
        if name not in {"some", "full"} or name in rows:
            raise ParseError("unexpected or duplicate PSI row")
        values = {}
        for field in fields[1:]:
            key, separator, value = field.partition("=")
            if not separator or key in values:
                raise ParseError("invalid or duplicate PSI field")
            values[key] = value
        try:
            rows[name] = Averages(
                *(percentage(values[key]) for key in ("avg10", "avg60", "avg300")),
                unsigned(values["total"]),
            )
        except KeyError as error:
            raise ParseError("incomplete PSI row") from error
    if set(rows) != {"some", "full"}:
        raise ParseError("missing PSI row")
    return Pressure(rows["some"], rows["full"])


def parse_meminfo(text):
    wanted = {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}
    values = {}
    seen = set()
    for line in text.splitlines():
        key, separator, raw = line.partition(":")
        if key not in wanted:
            continue
        fields = raw.split()
        if key in seen or not separator or len(fields) != 2 or fields[1] != "kB":
            values[key] = None
        else:
            try:
                values[key] = unsigned(fields[0])
            except ParseError:
                values[key] = None
        seen.add(key)
    total = values.get("MemTotal") or None
    available = values.get("MemAvailable")
    if total is not None and available is not None and available > total:
        available = None
    swap_total = values.get("SwapTotal")
    swap_free = values.get("SwapFree")
    swap_used = None
    if swap_total is not None and swap_free is not None and swap_free <= swap_total:
        swap_used = swap_total - swap_free
    return MemoryStats(total, available, swap_total, swap_used)


def parse_vmstat(text):
    counters = {}
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0] not in {"pswpin", "pswpout"}:
            continue
        if len(fields) != 2 or fields[0] in counters:
            raise ParseError("invalid or duplicate swap counter")
        counters[fields[0]] = unsigned(fields[1])
    if set(counters) != {"pswpin", "pswpout"}:
        raise ParseError("missing swap counter")
    return counters["pswpin"], counters["pswpout"]


def pressure_class(pressure):
    if pressure is None:
        return "unknown"
    some, full = pressure.some.avg10, pressure.full.avg10
    if some >= 10 or full >= 1:
        return "high"
    if some >= 1 or full >= 0.1:
        return "moderate"
    return "low"


class History:
    def __init__(self):
        self.samples = deque(maxlen=MAX_SAMPLES)
        self.last_time = None

    def add(self, now, value):
        if not math.isfinite(now):
            raise ValueError("sample time must be finite")
        if self.last_time is not None and now < self.last_time:
            self.samples.clear()
        self.last_time = now
        while self.samples and now - self.samples[0][0] >= HISTORY_SECONDS:
            self.samples.popleft()
        if value is not None:
            self.samples.append((now, percentage(value)))

    def render(self, now):
        maxima = [None] * COLUMNS
        for timestamp, value in self.samples:
            age = now - timestamp
            if not 0 <= age < HISTORY_SECONDS:
                continue
            column = COLUMNS - 1 - int(age / BUCKET_SECONDS)
            maxima[column] = value if maxima[column] is None else max(maxima[column], value)
        return "".join(
            EMPTY if value is None else SPARKLINE[min(
                len(SPARKLINE) - 1, int(min(value, 10) / 10 * (len(SPARKLINE) - 1) + 0.5)
            )]
            for value in maxima
        )


class SwapRates:
    def __init__(self):
        self.previous = None

    def update(self, now, counters):
        previous, self.previous = self.previous, None
        if counters is None:
            return None
        self.previous = (now, counters)
        if previous is None:
            return None
        elapsed = now - previous[0]
        deltas = tuple(value - old for value, old in zip(counters, previous[1]))
        if not 0 < elapsed <= MAX_RATE_GAP or any(delta < 0 for delta in deltas):
            return None
        return deltas[0] / elapsed, deltas[1] / elapsed, elapsed


def kernel_text(path):
    with path.open(encoding="ascii") as handle:
        text = handle.read(MAX_FILE_CHARS + 1)
    if len(text) > MAX_FILE_CHARS:
        raise ParseError("kernel file exceeds read limit")
    return text


def elapsed_clock():
    if hasattr(time, "CLOCK_BOOTTIME"):
        return time.clock_gettime(time.CLOCK_BOOTTIME)
    return time.monotonic()


def format_kib(value):
    if value is None:
        return "unavailable"
    amount = float(value)
    for unit in ("KiB", "MiB", "GiB", "TiB", "PiB", "EiB"):
        if amount < 1024 or unit == "EiB":
            return f"{amount:.2f} {unit}"
        amount /= 1024


def tooltip(pressure, category, memory, rates, psi_issue):
    lines = [
        f"Memory pressure: {category}",
        "Linux PSI measures time tasks stall waiting for memory, not RAM used.",
        "some: at least one task stalled.",
        "full: all non-idle tasks stalled together.",
    ]
    if pressure is None:
        lines.extend((f"Current PSI unavailable: {psi_issue}.", "Earlier valid history may remain."))
    else:
        for name, averages in (("some", pressure.some), ("full", pressure.full)):
            lines.append(
                f"{name} stall time: 10s {averages.avg10:.2f}% | "
                f"60s {averages.avg60:.2f}% | 300s {averages.avg300:.2f}%"
            )
    lines.extend((
        "History: last 120s, oldest → newest; 12 × 10s bins, sampled every 2s.",
        "Each bar keeps the maximum observed some avg10 in its bin (not an average).",
        "Fixed scale: 0–10% stall time; above 10% is clipped. · = no valid samples.",
        "History resets on bar reload, including wallpaper changes.",
        "Current 10s thresholds (heuristics):",
        "Moderate: some ≥1% or full ≥0.1%.",
        "High: some ≥10% or full ≥1%.",
        "These are not Apple's memory-pressure algorithm.",
        f"Available RAM: {format_kib(memory.available_kib)} / {format_kib(memory.total_kib)} total.",
    ))
    if memory.swap_total_kib == 0 and memory.swap_used_kib == 0:
        lines.append("Swap: none configured (0 KiB total).")
    else:
        lines.append(
            f"Swap used: {format_kib(memory.swap_used_kib)} / {format_kib(memory.swap_total_kib)} total "
            "(occupancy is not pressure)."
        )
    if rates is None:
        lines.append("Swap I/O: unavailable; needs consecutive valid samples (no reset or long gap).")
    else:
        lines.append(f"Swap I/O: in {rates[0]:.2f} pages/s | out {rates[1]:.2f} pages/s over {rates[2]:.2f}s.")
    lines.append("Click to open btop.")
    return "\n".join(lines)


class PressureMonitor:
    def __init__(self, proc_root=Path("/proc"), reader=kernel_text):
        self.proc_root = Path(proc_root)
        self.reader = reader
        self.history = History()
        self.swap_rates = SwapRates()

    def read(self, relative):
        try:
            text = self.reader(self.proc_root / relative)
            return text if isinstance(text, str) and len(text) <= MAX_FILE_CHARS else None
        except (OSError, UnicodeError, ValueError):
            return None

    def sample(self, now):
        source = self.read("pressure/memory")
        issue = "missing or unreadable kernel data"
        pressure = None
        if source is not None:
            try:
                pressure = parse_psi(source)
            except ParseError:
                issue = "malformed or incomplete kernel data"
        memory = parse_meminfo(self.read("meminfo") or "")
        try:
            counters = parse_vmstat(self.read("vmstat") or "")
        except ParseError:
            counters = None
        rates = self.swap_rates.update(now, counters)
        self.history.add(now, pressure.some.avg10 if pressure is not None else None)
        category = pressure_class(pressure)
        prefix = "MEM?" if category == "unknown" else "MEM "
        return {
            "text": prefix + self.history.render(now),
            "class": category,
            "tooltip": tooltip(pressure, category, memory, rates, issue),
        }


def stream(monitor, output, *, once=False, clock=elapsed_clock, sleep=time.sleep):
    try:
        while True:
            payload = monitor.sample(clock())
            output.write(json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")
            output.flush()
            if once:
                return 0
            sleep(SAMPLE_SECONDS)
    except BrokenPipeError:
        try:
            output.close()
        except OSError:
            pass
        return 0
    except KeyboardInterrupt:
        return 0


def stop(_signum, _frame):
    raise KeyboardInterrupt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="print one JSON sample without inventing earlier history")
    parser.add_argument("--proc-root", type=Path, default=Path("/proc"), help="kernel proc directory (default: /proc)")
    arguments = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, stop)
    return stream(PressureMonitor(arguments.proc_root), sys.stdout, once=arguments.once)


if __name__ == "__main__":
    raise SystemExit(main())
