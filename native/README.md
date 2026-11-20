# 163XL native solver

See the [163XL README](../README.md) for installation, timing and behavior.

The Windows runtime links the generated sparse solver to the VST3 through a small C ABI. The full SPICE deck is the source of the circuit and its initial state. The audio profile preserves the 4301 VCA and RMS cell equations, audio amplifier models, control components and loading. It uses closed-loop equivalents for control amplifiers to reduce the number of unknowns in the real-time solve.

The Windows workflow tests the built VST3 against the native runtime in mono and stereo at 44.1 kHz with 256- and 512-sample host blocks. It uploads the offline-verified evaluation bundle first, then verifies paced playback.
