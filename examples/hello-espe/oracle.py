#!/usr/bin/env python3
"""Show the hello-ESPE schedule, and check xretractor output when asked.

The arithmetic is the formal definition in src/include/SOperations.hpp
(Hash and Add), not a second engine. The z=2/3 vector is the one locked by
test/IntegrationTest/deinterleave_roundtrip/verify.sh.
"""

import struct
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent

WHEEL_DELTA = Fraction(1, 10)
IMU_DELTA = Fraction(1, 20)


def floor_frac(value: Fraction) -> int:
    """floor for a non-negative rational. Matches floorR in SOperations.hpp."""
    if value < 0:
        raise ValueError("floor_frac is only used for non-negative rates")
    return value.numerator // value.denominator


def hash_pick(delta_a: Fraction, delta_b: Fraction, index: int) -> tuple[str, int]:
    """Return ('A' or 'B', source index) for output slot `index` of A#B."""
    if delta_a <= 0 or delta_b <= 0:
        raise ValueError("deltas must be > 0")
    zet = delta_b / (delta_a + delta_b)
    pick_b = floor_frac(zet * index) == floor_frac(zet * (index + 1))
    if pick_b:
        return "B", index - floor_frac(zet * index)
    return "A", floor_frac(zet * index)


def interleave(left: list[int], delta_a: Fraction, right: list[int], delta_b: Fraction) -> list[int]:
    """A#B until one source index would run past the end of that list."""
    out: list[int] = []
    index = 0
    while True:
        side, pos = hash_pick(delta_a, delta_b, index)
        seq = right if side == "B" else left
        if pos >= len(seq):
            break
        out.append(seq[pos])
        index += 1
    return out


def add_pairs(left: list[int], delta_a: Fraction, right: list[int], delta_b: Fraction) -> list[tuple[int, int]]:
    """A+B. Output delta is min(delta_a, delta_b). Slower side uses floor."""
    delta_out = min(delta_a, delta_b)
    out: list[tuple[int, int]] = []
    index = 0
    while True:
        left_pos = index if delta_out == delta_a else floor_frac(index * delta_out / delta_a)
        right_pos = index if delta_out == delta_b else floor_frac(index * delta_out / delta_b)
        if left_pos >= len(left) or right_pos >= len(right):
            break
        out.append((left[left_pos], right[right_pos]))
        index += 1
    return out


def load_column(path: Path) -> list[int]:
    values: list[int] = []
    for line in path.read_text(encoding="ascii").splitlines():
        text = line.strip()
        if text:
            values.append(int(text))
    if not values:
        raise SystemExit(f"{path} is empty")
    return values


def output_delta(delta_a: Fraction, delta_b: Fraction) -> Fraction:
    return (delta_a * delta_b) / (delta_a + delta_b)


def self_check() -> None:
    """deinterleave_roundtrip vector: z=2/3, pattern B,A,A, B=1001+k, A=1+k."""
    delta_a = Fraction(1, 16)
    delta_b = Fraction(1, 8)
    for index in range(60):
        side, pos = hash_pick(delta_a, delta_b, index)
        if index % 3 == 0:
            if side != "B" or pos != index // 3:
                raise SystemExit(f"self-check: slot {index} expected B[{index // 3}]")
        else:
            expect_pos = (2 * index) // 3
            if side != "A" or pos != expect_pos:
                raise SystemExit(f"self-check: slot {index} expected A[{expect_pos}]")
        if output_delta(delta_a, delta_b) != Fraction(1, 24):
            raise SystemExit("self-check: interleave delta is not 1/24")
    # Held sample: slower stream repeats on the faster clock.
    held = add_pairs([10, 11, 12], Fraction(1, 10), [1, 2, 3], Fraction(1, 5))
    if held[:4] != [(10, 1), (11, 1), (12, 2)]:
        raise SystemExit(f"self-check: hold pattern {held[:4]}")
    print("self-check: OK")


def show_schedule(wheel: list[int], imu: list[int]) -> None:
    bus = interleave(wheel, WHEEL_DELTA, imu, IMU_DELTA)
    fused = add_pairs(wheel, WHEEL_DELTA, imu, IMU_DELTA)
    print("wheel delta 1/10 s, imu delta 1/20 s")
    print(f"interleave '#' delta {output_delta(WHEEL_DELTA, IMU_DELTA)} s  (imu, imu, wheel, ...)")
    print("slot  source  value")
    for index, value in enumerate(bus[:12]):
        side, _pos = hash_pick(WHEEL_DELTA, IMU_DELTA, index)
        source = "imu" if side == "B" else "wheel"
        print(f"{index:<5} {source:<6} {value}")
    print("resample '+' onto the faster clock 1/20 s; wheel is held")
    print("slot  wheel  imu")
    for index, (wheel_value, imu_value) in enumerate(fused[:8]):
        print(f"{index:<5} {wheel_value:<6} {imu_value}")


def read_u32(path: Path) -> list[int]:
    if not path.is_file():
        raise SystemExit(f"{path.name}: missing (xretractor did not write it)")
    data = path.read_bytes()
    if len(data) % 4 != 0:
        raise SystemExit(f"{path.name}: {len(data)} bytes is not a multiple of 4")
    count = len(data) // 4
    return list(struct.unpack("<" + "I" * count, data))


def read_pairs(path: Path) -> list[tuple[int, int]]:
    if not path.is_file():
        raise SystemExit(f"{path.name}: missing (xretractor did not write it)")
    data = path.read_bytes()
    if len(data) % 8 != 0:
        desc = path.with_suffix(".desc")
        extra = ""
        if desc.is_file():
            extra = "\n" + desc.read_text(encoding="utf-8", errors="replace")
        raise SystemExit(f"{path.name}: {len(data)} bytes is not 2 x uint32 records{extra}")
    words = struct.unpack("<" + "I" * (len(data) // 4), data)
    return [(words[i], words[i + 1]) for i in range(0, len(words), 2)]


def require_prefix(name: str, actual: list, expected: list, minimum: int) -> None:
    if len(actual) < minimum:
        raise SystemExit(f"{name}: only {len(actual)} records, need at least {minimum}")
    if actual != expected[: len(actual)]:
        raise SystemExit(
            f"{name}: mismatch\n  expected: {expected[: len(actual)]}\n  actual:   {actual}"
        )
    print(f"{name}: {len(actual)} records match")


def check_engine(wheel: list[int], imu: list[int]) -> None:
    bus = interleave(wheel, WHEEL_DELTA, imu, IMU_DELTA)
    fused = add_pairs(wheel, WHEEL_DELTA, imu, IMU_DELTA)
    require_prefix("bus", read_u32(HERE / "bus"), bus, 6)
    require_prefix("fused", read_pairs(HERE / "fused"), fused, 4)
    require_prefix("wheel_back", read_u32(HERE / "wheel_back"), wheel, 2)
    require_prefix("imu_back", read_u32(HERE / "imu_back"), imu, 4)
    print("engine: OK")


def main() -> None:
    self_check()
    wheel = load_column(HERE / "wheel.txt")
    imu = load_column(HERE / "imu.txt")
    if "--check-engine" in sys.argv[1:]:
        check_engine(wheel, imu)
        return
    show_schedule(wheel, imu)


if __name__ == "__main__":
    main()
