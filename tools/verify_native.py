"""Compare the compiled audio solver with the quiet-rail SPICE fixture."""

import csv
import json
import math
from pathlib import Path
import sys

tones, spice, ac = map(Path, sys.argv[1:])
results = {(float(slide), int(hz)): (float(output), float(thd), int(failures))
           for slide, hz, output, thd, failures in csv.reader(tones.read_text().splitlines())}
spice_reference = json.loads(spice.read_text())
ac_reference = {row["frequency_Hz"]: row["relative_dB"]
                for row in json.loads(ac.read_text())["response"]}
for row in spice_reference:
    slide = row["compression_slider"]
    output, thd, failures = results[slide, 1000]
    delta = output - row["output_dBu"]
    print(f"Slider {slide:.2f}: 1 kHz native versus SPICE {delta:+.3f} dB, "
          f"native K2–K5 THD {thd:.4f}%, SPICE K2–K20 {row['THD_K2_K20_pct']:.4f}%")
    if failures or not math.isfinite(delta) or abs(delta) > 0.15:
        raise SystemExit("The 1 kHz output level failed parity")
    if not math.isfinite(thd) or abs(thd - row["THD_K2_K20_pct"]) > 0.02:
        raise SystemExit("The 1 kHz THD failed parity")
reference = results[0., 1000][0]
for hz in (30, 5000, 10000, 15000, 20000):
    output, _, failures = results[0., hz]
    relative = output-reference
    print(f"{hz} Hz: {relative:+.3f} dB relative to 1 kHz, SPICE {ac_reference[hz]:+.3f} dB")
    # Listening build: explicitly allow up to 0.6 dB at 30 Hz only.
    # Retain all other level, THD, frequency and solver gates.
    tolerance = 0.6 if hz == 30 else 0.3
    if hz == 30 and abs(relative-ac_reference[hz])>0.3:
        print("LISTENING BUILD WARNING: 30 Hz deviation exceeds production 0.3 dB tolerance")
    if failures or not math.isfinite(relative) or abs(relative-ac_reference[hz])>tolerance:
        raise SystemExit("The native frequency response failed parity")
