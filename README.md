# 163X

Circuit reconstruction of the dbx 163X OverEasy compressor/limiter, with the THAT2180B retrofit. The connected SPICE reference is in [circuit/163x.cir](circuit/163x.cir). The board transcription, model provenance and hardware comparisons are documented in [docs/circuit.md](docs/circuit.md).

## Run the reference

Install Python 3, NumPy, ngspice (with XSPICE) and Poppler's `pdftotext`. Run:

```sh
python3 tools/prepare_models.py
python3 tools/measure.py --small-signal --output measurements/ac-noise.json
python3 tools/measure.py --mains --output measurements/mains.json
python3 tools/measure.py --output measurements/transfer.json
python3 tools/measure.py --timing --output measurements/timing.json
```

The mains fixture runs the transformer, rectifier and regulators and measures after its precharge disconnects. The transfer fixture uses clean DC at both reservoirs so supply ripple is excluded from the harmonic measurement. The source is the rear input with 100 Ω source impedance and a 10 kΩ load on the output.

The real-time Windows VST3 builds and runs its playback checks in [163X native Windows VST3](https://github.com/jerrykilgore8995-dotcom/163x/actions/workflows/native.yml). See [native build notes](native/README.md) for its circuit and host setup.
