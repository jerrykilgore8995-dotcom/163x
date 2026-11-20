* Datasheet-derived models. Values absent from source documents are described
* in docs/circuit.md and must be verified against the selected hardware revision.
.model D1N4148 D(IS=2.52n N=1.752 RS=0.568 CJO=4p M=0.4 TT=4n BV=100 IBV=100u)
.model D1N4002 D(IS=14n N=1.98 RS=0.034 CJO=25p M=0.333 TT=4.32u BV=100 IBV=5u)
.model RD9V1EB2 D(IS=1n N=1.6 RS=8 BV=9.1 IBV=5m CJO=90p)
.model LED3211A D(IS=2e-17 N=2 RS=12 BV=5 IBV=10u CJO=20p)
.model LED1254A D(IS=2e-17 N=2 RS=12 BV=5 IBV=10u CJO=20p)
.model LED1204A D(IS=2e-17 N=2 RS=12 BV=5 IBV=10u CJO=20p)
.model Q2SA952L PNP(IS=3e-14 BF=150 VAF=55 RB=50 RC=1 RE=0.5 CJE=18p CJC=7p TF=700p)

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
