"""Measure the compiled 163XL circuit using coherent tone and burst fixtures."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

import numpy as np

RATE = 44100
ATTACK_START = .4
RELEASE_START = .8
RECOVERY_RATE = 125
FREQUENCIES = (20, 30, 40, 50, 60, 80, 100, 150, 200, 300, 500, 700, 1000,
               1500, 2000, 3000, 4000, 5000, 6000, 8000, 10000, 12000, 14000,
               15000, 16000, 18000, 19000, 20000)


def tone(exe, rate, frequency, dbu, slider):
    row = subprocess.check_output(
        [str(exe), "tone", str(rate), str(frequency), str(dbu), str(slider), "1"], text=True
    )
    fs, slide, hz, level, gain, phase, thd, failures, *harmonics = map(float, row.split(","))
    audio_harmonics = [value for k, value in enumerate(harmonics, 2) if k * hz <= 20000]
    audible_thd = 100 * np.linalg.norm(10 ** (np.array(audio_harmonics) / 20))
    return {
        "sample_rate_Hz": int(fs), "slider": slide, "frequency_Hz": hz,
        "input_dBu": level, "gain_dB": gain, "phase_deg": phase,
        "thd_below_nyquist_pct": thd if harmonics else None,
        "thd_through_20k_pct": float(audible_thd) if audio_harmonics else None,
        "harmonics_dBc": {f"K{k}": value for k, value in enumerate(harmonics, 2)},
        "solver_failures": int(failures),
    }


def crossing(t, y, threshold, rising):
    indices = np.flatnonzero(y >= threshold if rising else y <= threshold)
    if not len(indices):
        return None
    index = indices[0]
    if index == 0:
        return float(t[0])
    fraction = (threshold - y[index-1]) / (y[index] - y[index-1])
    return float(t[index-1] + fraction * (t[index] - t[index-1]))


def timing(exe, target, attack_target):
    def run(high):
        text = subprocess.check_output(
            [str(exe), "burst", str(RATE), "-55", str(high), "1", "0"], text=True
        )
        t, gr, ec, detector, failures = np.loadtxt(text.splitlines(), delimiter=",").T
        pre = float(np.median(gr[(t > .35) & (t < .39)]))
        post = float(np.median(gr[(t > .72) & (t < .78)]))
        return post - pre, t, gr - pre, ec, detector, int(max(failures))

    # Set the burst level to reach the requested change in audio attenuation.
    high = {10: -25., 20: -14., 30: -3.}[target]
    total_failures = 0
    for _ in range(6):
        result = run(high)
        total_failures += result[-1]
        delta, t, gr, ec, detector, _ = result
        if abs(delta - target) <= .15:
            break
        high += target - delta
    attack = (t >= ATTACK_START + .001) & (t < RELEASE_START)
    release = t >= RELEASE_START + .001
    # Track the linear part separately from the return through the soft knee.
    mid = release & (gr < .8 * delta) & (gr > .2 * delta)
    slope = float(-np.polyfit(t[mid], gr[mid], 1)[0]) if mid.sum() >= 3 else None
    tail = release & (gr < .2 * delta) & (gr > .05 * delta)
    tail_slope = float(-np.polyfit(t[tail], gr[tail], 1)[0]) if tail.sum() >= 3 else None
    attack_s = crossing(t[attack] - ATTACK_START, gr[attack], .632 * delta, True)
    recovery_s = crossing(t[release] - RELEASE_START, gr[release], .1 * delta, False)
    recovery_near_floor_s = crossing(t[release] - RELEASE_START, gr[release], .1, False)
    return {
        "target_GR_dB": target, "measured_GR_dB": delta, "low_dBu": -55, "high_dBu": high,
        "attack_63_ms": None if attack_s is None else 1000 * attack_s,
        "attack_target_ms": attack_target, "release_target_ms": 1000 * target / RECOVERY_RATE,
        "release_90_ms": None if recovery_s is None else 1000 * recovery_s,
        "release_to_0.1dB_ms": None if recovery_near_floor_s is None else 1000 * recovery_near_floor_s,
        "release_mid_slope_dB_s": slope, "release_tail_slope_dB_s": tail_slope,
        "release_full_ms_from_mid_slope": 1000 * delta / slope if slope and slope > 0 else None,
        "steady_EC_mV": float(1000 * np.median(ec[(t > .72) & (t < .78)])),
        "steady_RMS_output_mV": float(1000 * np.median(detector[(t > .72) & (t < .78)])),
        "solver_failures": total_failures,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("probe", type=Path)
    parser.add_argument("spice_ac", type=Path)
    parser.add_argument("report", type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    exe = args.probe.resolve()
    spice = json.loads(args.spice_ac.read_text())
    cases = [(RATE, f, -55, 0) for f in FREQUENCIES]
    cases += [(RATE, f, 4, slider) for f in (100, 1000, 5000, 10000) for slider in (0, .45, 1)]
    cases += [(192000, f, 4, 1) for f in (5000, 10000)]
    transfer_cases = [(RATE, 1000, level, 1) for level in (-65, -55, -45, -35, -25, -15, -5, 0, 4, 8, 12, 16, 18)]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        tones = list(pool.map(lambda case: tone(exe, *case), cases))
        transfer = list(pool.map(lambda case: tone(exe, *case), transfer_cases))
        timings = list(pool.map(lambda row: timing(exe, *row), [(10, 15), (20, 5), (30, 3)]))
    response, distortion = tones[:len(FREQUENCIES)], tones[len(FREQUENCIES):]
    native_ref = next(row["gain_dB"] for row in response if row["frequency_Hz"] == 1000)
    reference = {row["frequency_Hz"]: row for row in spice["response"]}
    for row in response:
        hz = row["frequency_Hz"]
        row["relative_dB"] = row["gain_dB"] - native_ref
        if hz in reference:
            row["spice_relative_dB"] = reference[hz]["relative_dB"]
            row["spice_phase_deg"] = reference[hz]["phase_deg"]
            row["phase_error_deg"] = (row["phase_deg"] - row["spice_phase_deg"] + 180) % 360 - 180
    for row in transfer:
        row["output_dBu"] = row["input_dBu"] + row["gain_dB"]
    report = {
        "frequency_response": response, "line_level_distortion": distortion, "timing": timings,
        "max_compression_transfer": transfer,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    for row in timings:
        print(json.dumps(row), flush=True)
    problems = []
    if any(row["solver_failures"] for row in tones + timings + transfer):
        problems.append("One or more native solves failed")
    if any(abs(row["relative_dB"]) > 1 for row in response):
        problems.append("Frequency response exceeded ±1 dB between 20 Hz and 20 kHz")
    if any(abs(row["phase_error_deg"]) > 4 for row in response if "phase_error_deg" in row):
        problems.append("Phase differed from the SPICE circuit by more than 4 degrees")
    if any(row["thd_through_20k_pct"] > .2 for row in distortion if row["frequency_Hz"] == 1000):
        problems.append("1 kHz THD exceeded 0.2% at +4 dBu")
    output_steps = np.diff([row["output_dBu"] for row in transfer])
    if min(output_steps) < -.02:
        problems.append("Output dropped as input increased at maximum Compression")
    if any(abs(row["measured_GR_dB"] - row["target_GR_dB"]) > .2 for row in timings):
        problems.append("A timing burst missed its requested gain reduction")
    if any(row["release_tail_slope_dB_s"] is None or row["release_mid_slope_dB_s"] is None
           or row["release_tail_slope_dB_s"] >= row["release_mid_slope_dB_s"] for row in timings):
        problems.append("A recovery failed to taper through the soft knee")
    if any(row["attack_63_ms"] is None or abs(row["attack_63_ms"] - row["attack_target_ms"]) > limit
           for row, limit in zip(timings, (2, 2, .8), strict=True)):
        problems.append("A burst missed the attack window")
    deep_slope = timings[-1]["release_mid_slope_dB_s"]
    if deep_slope is None or abs(deep_slope - RECOVERY_RATE) > 10:
        problems.append("30 dB mid-release missed the 125 dB/s window")
    if problems:
        raise SystemExit("; ".join(problems))


if __name__ == "__main__":
    main()
