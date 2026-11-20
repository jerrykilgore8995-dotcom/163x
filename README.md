# 163XL

163XL is a separate Windows x64 VST3 built from the 163X repository's **NEW** circuit. It has its own VST3 class ID and runs one THAT4301 nodal circuit per channel. The 163X Compression, Level Set and OverEasy control network are carried over.

## Install

Download the `163XL-0.1.0-Windows-x64-VST3` artifact from the [163XL GitHub Actions build](https://github.com/jerrykilgore8995-dotcom/163x/actions?query=branch%3A163xl). Copy the complete `163XL.vst3` folder into your VST3 directory. Its `Contents/Resources` directory contains the circuit runtime. The runtime targets an AVX2-capable CPU.

The solver processes stereo as dual mono. At 44.1 kHz, the reported latency is 1,536 samples (34.8 ms) at a 512-sample host block and 1,024 samples (23.2 ms) at 256. Digital Input and Output default to 0 dB. Settings provides the optional detector HPF, LP Bypass and Turbocharge. PSU Noise is off by default.

## Circuit and measurements

- The VCA and RMS sections use THAT's 4301 macromodel at ±15 V. The VCA uses 15 kΩ current input and feedback resistors, the EC+ control driver and the EC+-referenced symmetry trim. The current output is shared with the chip's OA3. 163XL uses that amplifier for current-to-voltage conversion and retains the 163X output isolation and load.
- The detector uses a 30 kΩ AC-coupled input, 2 MΩ from IT to the negative rail and the 163X adaptive LF353 timing network. The main CT capacitance is 12 µF. A filtered CT-current sense and precision rectifier using on-chip OA1 add discharge current during recovery. The assist follows the detector's discharge current as it falls. The original NJM4558 OverEasy network sets the soft knee and transition toward 1:1.
- Attack is the time to 63.2% of the measured 1 kHz gain-reduction change. Release is reported as a mid-slope in dB/s plus actual crossings at 90% and within 0.1 dB of the original gain. The 80, 160 and 240 ms references are the nominal linear equivalents at 125 dB/s. The measured envelope slows through the OverEasy knee.
- The output biquads correct the fixed-step solver's magnitude and phase against the OA3 SPICE circuit. This correction runs downstream of the compressor. Reports measure frequency response against 1 kHz and phase against the input, excluding host latency. Line-level distortion uses +4 dBu and includes individual K2–K20 components where the sample rate permits.
- The circuit and timing are model-verified. A physical 4301-retrofitted 163X and a DAW session on the target PC are separate benchmarks.

`circuit/163x.cir` is the connected SPICE reference. The build uses quiet ±15 V rails, omits the physical PSU and LED string, and preserves the meter-driver load. The optional PSU Noise is added by the plug-in. `tools/measure_xl.py` drives the compiled solver and writes the measurement JSON included in the build.
