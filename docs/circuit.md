# 163X circuit reference

## Sources

- [AKG/dbx schematic](https://www.eserviceinfo.com/downloadsm/170201/.%20Various_163X%20Schematic.html), one-page service drawing, SHA-256 `507a01a2f24258ffa9a6a3df6bbae1ba959e2137ad51c0f5e62541865d8102a2`.
- [Factory test procedure, Rev. 3](https://manualzz.com/doc/24162782/dbx-163x-compressor-user-manual), dated September 25, 1985 and reformatted September 13, 1997.
- [Owner's manual and service drawings](https://warehousesound.com/r/dbx163Xmanual.pdf), controls, transfer, stereo operation and specifications. The appendix contains 80-6186 Rev A0 dated 1995-02-17 and identifies parts left ambiguous on the one-page drawing.
- [NEC uPC1252HA2 datasheet](https://www.datasheetarchive.com/?q=upc1252ha2), pp. 171–175, nominal 5.9 mV/dB gain-control constant.
- [NEC uPC1253H2 datasheet](https://www.datasheetarchive.com/?q=upc1253h2), NEC catalog pp. 242–245.
- [THAT 2180 datasheet](https://thatcorp.com/that-2180-series-pre-trimmed-blackmer-voltage-controlled-amplifier-ics/) and [Rev. 05 manufacturer models](https://thatcorp.com/device-models/).
- [TI LF353-N](https://www.ti.com/product/LF353-N), SNOM253, and [TI NE5534](https://www.ti.com/product/NE5534), SLOJ049.
- [Bee Technologies NJM4558 modeling report](https://toucy.sakura.ne.jp/datas/Simulation/LTspice/JRC_Macro/Operational%20Amplifiers%20Macromodel/NJM4558/NJM4558.pdf) and [Nisshinbo NJM4558 datasheet](https://www.nisshinbo-microdevices.co.jp/en/products/operational-amplifier/spec/?product=njm4558).
- [Sanyo LA6339 datasheet](https://eletrodex.org/eletrodex/Loja_Tray/Datasheets/Semicondutores/CIs%20Amp-Ops/Comparadores/LA6339.pdf) and [NEC 2SA952 datasheet](https://wakamatsu.co.jp/waka/2SA952-A.pdf).

## Topology and model scope

- J1 selects the instrument input through the front jack's normal contact and enables the rear Hi-Z gain trim. J2 enters the same LF353N preamp through the normalled contact for rear line operation. Source and load belong to the test fixture.
- After R5, the signal divides into the VCA audio path and the detector path. The audio path uses the 2180B and the NE5534 with both external compensation capacitors. The VCA ground/reference and gain control are mapped for the THAT2180B. The retrofit adapter rescales the control voltage by 6.1/5.9 for the gain-control constants of the THAT and NEC parts and reflects current back to the original control node. Its symmetry pin is physically unused, so the original R9–R11 branch is retained as electrical loading/control offset and the original VCA symmetry calibration does not carry over.
- IC2 implements the NEC data sheet's current input, symmetry reference, log RMS integration and buffered output at their board pins. The logarithmic scale is 5.9 mV/dB typical. The nominal release calibration fits the otherwise unspecified internal buffer gain (1.19) to the 163X deep-release specification. The detector's log integrator parameters compensate that gain so the NEC static 5.9 mV/dB scale stays fixed. This is a calibrated macromodel parameter. R34, C15, C16, C17, CR6 and CR7 and LF353N section B make up the external timing network. The published NEC data provides a functional block diagram and measurements. IC2 is a datasheet-derived nonlinear macro with no claim of transistor-level identity.
- OA3/OA4, CR3/CR4/CR5/CR26 and their external passives generate the operating-level offset, soft knee and detector-dependent control voltage. R18 is Level Set, R38 is Compression. The three S1 poles switch TP2, J4 and the slave indicator together. The board supports connecting a second board at J4 tip/ring with distinct master and slave settings.
- The three LA6339 packages drive CR8–CR19 in a tapped series chain. The positive rail sets the comparator thresholds through R47–R59 and R64. Q1 supplies the meter/Slave LED current. The Power LED is powered separately from the negative reservoir. The 12 labeled comparator/component taps and their corresponding lamps remain in the circuit. The comparator, LED, zener and Q1 models represent the documented device functions. Specific semiconductor parameters absent from the sheets are estimates.
- The mains model includes the center-tapped transformer, the 4.7 nF primary capacitor, CR21–CR24, C26–C33, both regulator models and the nominal star grounds. Transformer inductance, turns ratio, winding resistance and coupling are estimates. Regulator macro models implement load, finite output impedance and dropout. This is a functional model of the 115 V option, with a soft mains ramp and bench precharge for convergence. It does not model insulation leakage, transformer magnetic saturation or cold startup.
- The 80-6186 drawing resolves the Hi-Z trim discrepancy. Its R1 is 4.7 kΩ in the equivalent position to R3 on the one-page drawing. Its R42 is 22 Ω outside the output feedback loop and matches the unlabeled series symbol after R16 on the one-page drawing. The reference applies those two documented values to the earlier topology. The one-page sheet has no labeled R17, and its S2 note does not identify a second switch in the drawing. J1 and J2 normals are represented in their connected plug states.
- The NJM4558 fit from the Bee Technologies report draws over 16 mA per section across ±15 V as published. The preparation tool adjusts its rail shunt to the Nisshinbo datasheet's 3.5 mA typical dual-package current so the supply reference is not loaded by that modeling discrepancy.

## Verification targets

| Item | Factory/owner reference |
| :--- | :--- |
| Rails | Raw ±24 V within ±3 V, less than 0.7 V ripple. Regulated ±15 V within ±0.5 V. |
| RMS calibration | TP6 at 0 mV ±10 mV for 1 kHz at −10 dBV. TP11 nominally 70 mVpp ±15 mV for 50 Hz at −10 dBV. |
| Compression | Increasing R38 shifts the soft knee left and adds makeup. Far above the knee, the local slope approaches limiting. |
| Frequency response | 20 Hz–20 kHz within ±1 dB. Factory checks include 20 Hz, 100 Hz, 1 kHz and 20 kHz, with both slider extremes. |
| Distortion | Factory applies 0 dBV at 1 kHz with Level Set at 0 and Compression at midpoint, with a limit of 0.08%. Limits at 40 Hz and 10 kHz are 0.25% and 0.10%. |
| Output noise | Under −82 dBV (unweighted, 20 Hz–20 kHz) at minimum Compression and central Level Set. |
| Release | Published nominal 125 dB/s, program dependent. |
| Native build | Verify against this reference after calibration, including response, harmonics, timing, meter/strap behavior and noise. Pace mono and stereo through a Windows VST3 host at 44.1 kHz with 512-sample buffers, including cymbal transients. |


## Initial measured results

These results are from the connected SPICE model with the 2180B. They describe this circuit candidate and are not physical unit measurements. The factory 1 kHz comparison uses the rear jack and a 10 kΩ load. Level Set at the 0 mark is 0.75 pot travel.

| Check | Result |
| :--- | :--- |
| Reference designator coverage | 65 shown numbered resistors, C1–C34, CR1–CR26, all visible amplifier sections, the two regulators and Q1. R17 and S2 are addressed above. |
| Hi-Z gain trim | About +20.83 dB from minimum to maximum, applying −20 dBV at the front jack. |
| Output impedance | About 22.0 Ω from the 600 Ω and 10 kΩ measurements. |
| Powered rails after bench precharge | Raw +23.54/−23.40 V with 0.545/0.672 Vpp ripple. Regulated +14.998/−14.997 V. |
| TP6 at −10 dBV, 1 kHz | About −0.44 mV after setting R25 and choosing the detector's 120 mV reference within the NEC datasheet spread. |
| TP11 at −10 dBV, 50 Hz | 84.6 mVpp after timing calibration. The factory tolerance is 55–85 mVpp. |
| 0 dBV, 1 kHz, midpoint Compression | 0.019% K2–K20 THD in the clean-rail fixture. Factory limit 0.08%. |
| 0 dBV, 40 Hz, midpoint Compression | 0.244% K2–K20 THD in the clean-rail fixture. Factory limit 0.25%. |
| 0 dBV, 10 kHz, midpoint Compression | 0.046% K2–K20 THD in the clean-rail fixture. Factory limit 0.10%. The short-step fixture uses 1 fF of numerical shunt per node to initialize the op-amp macros. |
| Level Set endpoints, maximum Compression | −24.19 and +8.10 dBV for the factory −10 dBV input. Both are within their respective factory tolerances. |
| Slope at maximum Compression | About 19.7:1 on the final +10 to +14 dBV segment of the 1 kHz clean-rail sweep at midpoint Level Set. The circuit trends toward limiting and these points still show finite slope. |
| Small-signal frequency response | −0.23 dB at 20 Hz and −0.27 dB at 20 kHz relative to 1 kHz. The driven 0 dBV comparison gave −0.28 dB at 20 kHz at both Compression extremes. |
| Modeled quiet-rail noise | −97.8 dBV output, 20 Hz–20 kHz, minimum Compression and midpoint Level Set. The vendor macros do not cover all physical device or transformer noise, so the result cannot establish hardware noise parity. |
| Attack at 10/20/30 dB input steps | 16/6/3 ms to 63% of measured gain change, Compression at 0.85. |
| Factory gain-reduction lamps | 4 lit at −30 dBV with Compression at maximum, 3 lit at +10 dBV with Compression at minimum, and all 12 lit at +10 dBV with Compression at maximum. The first two checks allow 3 ±1 lamps. |
| Mid-release at 10/20/30 dB input steps | 94/117/122 dB/s on the return to the lower tone. The 30 dB step followed by silence measured 125.1 dB/s in the same mid-release region. |
