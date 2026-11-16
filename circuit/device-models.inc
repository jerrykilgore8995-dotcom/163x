* Datasheet-derived models. Values absent from source documents are described
* in docs/circuit.md and must be verified against the selected hardware revision.
.model D1N4148 D(IS=2.52n N=1.752 RS=0.568 CJO=4p M=0.4 TT=4n BV=100 IBV=100u)
.model D1N4002 D(IS=14n N=1.98 RS=0.034 CJO=25p M=0.333 TT=4.32u BV=100 IBV=5u)
.model RD9V1EB2 D(IS=1n N=1.6 RS=8 BV=9.1 IBV=5m CJO=90p)
.model LED3211A D(IS=2e-17 N=2 RS=12 BV=5 IBV=10u CJO=20p)
.model LED1254A D(IS=2e-17 N=2 RS=12 BV=5 IBV=10u CJO=20p)
.model LED1204A D(IS=2e-17 N=2 RS=12 BV=5 IBV=10u CJO=20p)
.model Q2SA952L PNP(IS=3e-14 BF=150 VAF=55 RB=50 RC=1 RE=0.5 CJE=18p CJC=7p TF=700p)

* NEC uPC1253H2 current rectifier, translinear square/average and buffer.
* VCT is the physical logarithmic integrator state. Preserve board R34, C15,
* C16, diode network and J4 ring; no hidden timing capacitor or envelope.
* NEC functional blocks are documented; transistor geometry is unpublished.
.subckt UPC1253H2 IN ISREF REF SYM VN CT OUT VP
VSENSE IN SENSE 0
RSENSE SENSE REF 15
RBIAS ISREF ISCLAMP 2k
VBIAS ISCLAMP VN 1.8
RSYM SYM REF 10k
IQUIET VP VN 0.9m
* Xrms current reaches 30.303uA at the 1Vrms/33k NEC reference.
* Reference current 10.113uA follows the test fixture's -12V and 1.2M.
* 120 mV fits the NEC sample spread and leaves R25 within the factory trim range.
* Current limiting bounds the macro outside the datasheet input range.
* Smoothing the rectifier around zero gives a finite noise-floor operating point.
.param KSQ=0.02562337 IREF=30.30303u ICREF=10.113333u VREF=0.120
BAVG 0 CT I={min(0.002, ICREF*((i(VSENSE)+v(SYM,REF)/10k)^2+1e-18)/(IREF*IREF)*exp(min(35,max(-35,(VREF-v(CT,REF))/KSQ))))}
EBUF BUF REF CT REF 1
ROUT BUF OUT 35
.ends UPC1253H2

* Open collector sink with finite saturation resistance and off conductance.
.subckt LA6339_OC INP INM VP VN OUT
IQ VP VN 200u
RINP INP VN 50meg
RINM INM VN 50meg
BSINK OUT VN I={v(OUT,VN)*(1e-9+0.025*(1+tanh(v(INM,INP)/0.003)))}
.ends LA6339_OC

.subckt REG15P IN OUT REF
IQUIET IN REF 3m
BDRIVE CORE REF V={min(15+0.0005*(v(IN,REF)-24),max(0,v(IN,REF)-2))}
VSENSE CORE PIN 0
ROUT PIN OUT 0.075
FLOAD IN REF VSENSE 1
.ends REG15P

.subckt REG15N IN OUT REF
IQUIET REF IN 3m
BDRIVE CORE REF V={max(-15+0.0005*(v(IN,REF)+24),min(0,v(IN,REF)+2))}
VSENSE CORE PIN 0
ROUT PIN OUT 0.075
FLOAD REF IN VSENSE -1
.ends REG15N
