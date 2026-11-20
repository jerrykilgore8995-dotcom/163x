"""Measure the connected 163X SPICE reference with explicit bench conditions."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
import shutil
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import numpy as np

CIRCUIT = Path(__file__).resolve().parents[1] / "circuit"
REFERENCE = 0.775
NODES = "v(out) v(xunit.tp3) v(xunit.tp4) v(xunit.tp6) v(xunit.vp15) v(xunit.vn15) v(xunit.vp24) v(xunit.vn24) v(xunit.tp1) v(xunit.tp11) v(xunit.vca_ec)"
ANALYSIS_RATE = 1_000_000
POWER = """* Bench precharge is removed by 150 ms; mains powers the measured interval.
VPRE_P POS_KICK 0 PWL(0 24 0.05 24 0.15 0)
VPRE_N NEG_KICK 0 PWL(0 -24 0.05 -24 0.15 0)
DPRE_P POS_KICK XUNIT.VP24 D1N4002
DPRE_N XUNIT.VN24 NEG_KICK D1N4002
"""
QUIET_RAILS = """* Quiet-rail test fixture at the bridge reservoirs.
VPRE_P XUNIT.VP24 0 24
VPRE_N XUNIT.VN24 0 -24
"""


def run_spice(args, body, commands):
    with TemporaryDirectory(prefix="163x-") as directory:
        work = Path(directory)
        shutil.copytree(CIRCUIT / "vendor", work / "vendor")
        for name in ("device-models.inc", "163x-board.inc"):
            shutil.copyfile(CIRCUIT / name, work / name)
        if args.code_model:
            shutil.copyfile(args.code_model, work / "spice2poly.cm")
        deck = work / "measurement.cir"
        deck.write_text(body + f"""
.control
set wr_singlescale
set num_threads=1
{commands}
quit
.endc
.end
""")
        run = subprocess.run([args.ngspice, "--batch" if args.shared_worker else "-b", deck.name],
                             cwd=work, capture_output=True, text=True, timeout=1800)
        log = run.stdout + run.stderr
        if run.returncode or "aborted" in log or not (work / "trace.txt").is_file():
            raise RuntimeError(log[-3000:])
        return np.loadtxt(work / "trace.txt"), log


def bench_deck(args, peak, slider, mains):
    body = (CIRCUIT / "163x.cir").read_text().rsplit(".end", 1)[0]
    if args.hiz_trim is not None:
        body = body.replace("RSOURCE SRC REAR 100\nRFRONT FRONT 0 1meg",
                            "RSOURCE SRC FRONT 100\nRREAR REAR 0 1meg")
        body = body.replace("LEVEL={OUTPUT}", f"LEVEL={{OUTPUT}} FRONT=1 HIZTRIM={args.hiz_trim}")
    body = body.replace("RLOAD OUT 0 10k", f"RLOAD OUT 0 {args.load}")
    body = body.replace(".param AMP=0.1 FREQ=1000 SLIDE=0.45 OUTPUT=0.5",
                        f".param AMP={peak:.12g} FREQ={args.frequency} SLIDE={slider} OUTPUT={args.level_set}")
    if mains:
        return body + POWER
    return re.sub(r"(?m)^BMAINS MAINS 0 .*", "VMAINS MAINS 0 0", body) + QUIET_RAILS


def small_signal(args):
    data, log = run_spice(args, bench_deck(args, 0, 0, False), """
ac dec 48 20 20k
wrdata trace.txt vdb(out)
noise v(out) VIN dec 48 20 20k
setplot noise2
print onoise_total inoise_total
""")
    reference = np.interp(np.log(1000), np.log(data[:, 0]), data[:, 1])
    output_noise = float(re.search(r"onoise_total\s*=\s*([0-9.eE+-]+)", log)[1])
    input_noise = float(re.search(r"inoise_total\s*=\s*([0-9.eE+-]+)", log)[1])
    return {
        "response": [{"frequency_Hz": float(f),
                      "relative_dB": float(np.interp(np.log(f), np.log(data[:, 0]), data[:, 1])-reference)}
                     for f in (20, 30, 40, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 15000, 20000)],
        "output_noise_dBV": 20 * np.log10(output_noise),
        "input_noise_dBu": 20 * np.log10(input_noise / REFERENCE),
    }


def simulate(args, slider, dbu, mains):
    peak = REFERENCE * np.sqrt(2) * 10 ** (dbu / 20)
    body = bench_deck(args, peak, slider, mains)
    max_step = min(5e-6, 0.005 / args.frequency)
    import os
    if os.environ.get("ROBUST")=="1": body += "\n.options method=gear maxord=2\n"
    if max_step < 10e-6:
        # Regularize the nanosecond DC-to-transient transition in the op amp
        # macros. One femtofarad per node is a fixture setting, not a board cap.
        body += ".options cshunt=1f\n"
    start = 0.9
    window = max(4, round(0.10 * args.frequency)) / args.frequency
    duration = start + window + 1 / ANALYSIS_RATE
    data, _ = run_spice(args, body, f"""
save {NODES}
tran {max_step:.9g} {duration:.10g} {start - 0.00005:.10g} {max_step:.9g}
wrdata trace.txt {NODES}
""")
    if data[-1, 0] < start + window:
        raise RuntimeError(f"SPICE stopped at {data[-1, 0]:.6f} s")
    time = start + np.arange(round(window * ANALYSIS_RATE)) / ANALYSIS_RATE
    output = np.interp(time, data[:, 0], data[:, 1])
    bands = abs(2 * np.fft.rfft(output) / len(output))
    indices = np.arange(1, 21) * round(args.frequency * window)
    harmonics = bands[indices[indices < len(bands)]]
    result = {
        "compression_slider": slider,
        "level_set_position": args.level_set,
        "frequency_Hz": args.frequency,
        "input_dBu": dbu,
        "front_hiz_trim": args.hiz_trim,
        "output_load_ohms": args.load,
        "output_dBu": 20 * np.log10(harmonics[0] / (REFERENCE * np.sqrt(2))),
        "THD_K2_K20_pct": 100 * np.linalg.norm(harmonics[1:]) / harmonics[0],
        "K2_dBc": 20 * np.log10(harmonics[1] / harmonics[0]),
        "K3_dBc": 20 * np.log10(harmonics[2] / harmonics[0]),
    }
    audio_h = harmonics[1:][np.arange(2,len(harmonics)+1)*args.frequency<=20000]
    result["THD_audio_20k_pct"]=float(100*np.linalg.norm(audio_h)/harmonics[0])
    result["THD_K2_K20_dB"]=float(20*np.log10(max(np.linalg.norm(harmonics[1:])/harmonics[0],1e-30)))
    result["harmonics_dBc"]={str(k):float(20*np.log10(max(v/harmonics[0],1e-30))) for k,v in enumerate(harmonics,1)}
    result["harmonics_dBu"]={str(k):float(20*np.log10(max(v/(REFERENCE*np.sqrt(2)),1e-30))) for k,v in enumerate(harmonics,1)}
    # Entire audio path, including control ripple; exclude DC and fundamental.
    mask=(np.fft.rfftfreq(len(output),1/ANALYSIS_RATE)<=20000)&(np.fft.rfftfreq(len(output),1/ANALYSIS_RATE)>0)
    mask[indices[0]]=False
    result["residual_20k_pct"]=float(100*np.linalg.norm(bands[mask])/harmonics[0])
    names = ("tp3", "tp4", "tp6", "positive_rail", "negative_rail",
             "raw_positive", "raw_negative", "tp1", "tp11", "vca_control")
    for index, name in enumerate(names, 2):
        node = np.interp(time, data[:, 0], data[:, index])
        result[name + "_mean_V"] = float(np.mean(node))
        result[name + "_peak_to_peak_V"] = float(np.ptp(node))
    return result


def timing(args, step, return_to_silence=False):
    # Both stimulus transitions occur at a 1 kHz zero crossing. A half-cycle
    # raised-cosine transition avoids a discontinuous slope at the breakpoint.
    attack_start, release_start = 0.25, 0.48
    low_peak = REFERENCE * np.sqrt(2) * 10 ** ((8-step)/20)
    high_peak = REFERENCE * np.sqrt(2) * 10 ** (8/20)
    body = bench_deck(args, low_peak, 0.85, False)
    release_peak = 0 if return_to_silence else low_peak
    body = body.replace(
        "BSIGNAL SRC SRC_REF V={AMP*sin(6.283185307179586*FREQ*time)*tanh(100*time)^2}",
        f""".func edge(t) {{0.5-0.5*cos(3.141592653589793*min(1,max(0,t/500u)))}}
BSIGNAL SRC SRC_REF V={{(AMP+({high_peak:.12g}-AMP)*edge(time-{attack_start})+({release_peak:.12g}-{high_peak:.12g})*edge(time-{release_start}))*sin(6283.185307179586*time)*tanh(100*time)^2}}"""
    )
    data, _ = run_spice(args, body, f"""
save {NODES}
tran 10u 0.82 0.21 10u
wrdata trace.txt {NODES}
""")
    if data[-1, 0] < 0.81999:
        raise RuntimeError("SPICE did not reach the end of the release")
    # Use the actual VCA pin voltage and the NEC detector's own log output.
    # The DC makeup offset cancels when measuring a change.
    time = np.arange(0.22, 0.819, 0.001)
    periods = time[:, None]+(np.arange(16)+0.5)/16000
    vca_control = np.interp(periods, data[:, 0], data[:, 11]).mean(axis=1)
    detector_db = np.interp(periods, data[:, 0], data[:, 4]).mean(axis=1)/0.0059
    gr = -vca_control/0.0061
    low = float(np.mean(gr[time < 0.245]))
    high = float(np.mean(gr[(time > 0.45) & (time < 0.475)]))
    delta = high - low
    attack = np.flatnonzero((time >= attack_start) & (gr >= low + 0.63*delta))
    mid = (time > release_start+0.012) & (gr > low+0.25*delta) & (gr < low+0.85*delta)
    early = (time >= release_start+0.020) & (time < release_start+0.060)

    def falling_rate(values, region):
        return -float(np.polyfit(time[region], values[region], 1)[0]) if np.count_nonzero(region) > 2 else None

    return {"input_step_dB": step, "return_to_silence": return_to_silence,
            "gain_reduction_change_dB": delta,
            "attack_63_percent_ms": float((time[attack[0]] - attack_start)*1000) if len(attack) else None,
            "early_detector_release_dB_per_s": falling_rate(detector_db, early),
            "early_vca_release_dB_per_s": falling_rate(gr, early),
            "mid_release_dB_per_s": falling_rate(gr, mid)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ngspice", default="ngspice")
    parser.add_argument("--shared-worker", action="store_true")
    parser.add_argument("--code-model", type=Path)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--timing", action="store_true", help="Measure 10, 20 and 30 dB input steps")
    parser.add_argument("--small-signal", action="store_true", help="Run AC and integrated noise")
    parser.add_argument("--mains", action="store_true", help="Measure with the connected transformer and rectifier")
    parser.add_argument("--frequency", type=int, default=1000, metavar="20..20000")
    parser.add_argument("--hiz-trim", type=float, help="Use the front input with this trim position (0 to 1)")
    parser.add_argument("--load", type=float, default=10_000, help="Output load in ohms")
    parser.add_argument("--level-set", type=float, default=0.5)
    parser.add_argument("--case", type=float, nargs=2, action="append", metavar=("SLIDER", "DBU"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.hiz_trim is not None and not 0 <= args.hiz_trim <= 1:
        parser.error("--hiz-trim must be within 0 to 1")
    if args.load <= 0:
        parser.error("--load must be positive")
    if not 20 <= args.frequency <= 20000:
        parser.error("--frequency must be between 20 and 20000 Hz")
    if not 0 <= args.level_set <= 1:
        parser.error("--level-set must be within 0 to 1")
    cases = args.case or ([(0.45, -15)] if args.mains else [
        (slider, level) for slider in (0.05, 0.45, 0.85) for level in (-45, -30, -15, 0, 6, 12)
    ])
    if args.small_signal or args.timing:
        if args.timing:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                fixtures = [(10, False), (20, False), (30, False), (30, True)]
                result = list(pool.map(lambda case: timing(args, *case), fixtures))
        else:
            result = small_signal(args)
        print(json.dumps(result, indent=2))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        return
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = pool.map(lambda case: simulate(args, *case, args.mains), cases)
        result = []
        for row in rows:
            result.append(row)
            print(json.dumps(row), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
