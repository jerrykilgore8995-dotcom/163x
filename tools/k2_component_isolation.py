"""Diagnostic only: preserve stock files, compare complex harmonics at matched control."""
import argparse, json, math, tempfile, shutil, traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import measure as m

F=10000
PEAK=.775*math.sqrt(2)*10**(4/20)
NODES="v(out) v(xunit.tp1) v(xunit.tap) v(xunit.vca_ec) v(xunit.vca_io) v(xunit.oa2o) v(xunit.tp3) v(xunit.tp6) v(xunit.tp11) v(xunit.vp15) v(xunit.vn15) i(v.xunit.vdiag_in) i(v.xunit.vdiag_out)"
NAMES="out tp1 tap control summing oa2out tp3 tp6 tp11 vp15 vn15 vca_in_current vca_out_current".split()
def replace(b,old,new):
    assert b.count(old)==1, old
    return b.replace(old,new)
def run(job):
    mode,dc=job
    try:
        a=argparse.Namespace(frequency=F,level_set=.5,load=10000,hiz_trim=None,code_model=None,ngspice="ngspice",shared_worker=False)
        body=m.bench_deck(a,PEAK,1,False)
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); shutil.copytree(m.CIRCUIT/"vendor",d/"vendor")
            for p in ("device-models.inc","163x-board.inc"): shutil.copyfile(m.CIRCUIT/p,d/p)
            b=(d/"163x-board.inc").read_text()
            b=replace(b,"XIC1 VCA_IN VCA_EC 0 VCA_VEE 0 VP15 VCA_IO THAT2180B","VDIAG_IN VCA_IN VCA_PIN 0\nVDIAG_OUT VCA_PINOUT VCA_IO 0\nXIC1 VCA_PIN VCA_EC 0 VCA_VEE 0 VP15 VCA_PINOUT THAT2180B")
            if mode.startswith("frozen"):
                b=replace(b,"EVC_CTRL VCA_DRIVE 0 ECPLUS 0 {VCA_CONTROL_SCALE}",f"VVC_FIXED VCA_DRIVE 0 {dc:.12g}")
            if mode in ("ideal_lf","frozen_ideal_lf"):
                b=replace(b,"XOA1A OA1P OA1M VP15 VN15 TP1 LF353/NS","EIDEAL_LF TP1 0 OA1P OA1M 100000")
            if mode in ("ideal_ne","frozen_ideal_ne"):
                b=replace(b,"XOA2 OA2P VCA_IO VP15 VN15 OA2O OA2_COMP5 OA2_COMP8 NE5534","EIDEAL_NE OA2O 0 OA2P VCA_IO 100000\nRDIAG_COMP OA2_COMP5 0 1g\nRDIAG_COMP2 OA2_COMP8 0 1g")
            if mode=="frozen_ideal_vca":
                # Positive control increases gain. Preserve virtual-ground current input.
                b=replace(b,"XIC1 VCA_PIN VCA_EC 0 VCA_VEE 0 VP15 VCA_PINOUT THAT2180B","VIVCA VCA_PIN 0 0\nBVCA 0 VCA_PINOUT I={i(VIVCA)*exp(v(VCA_EC)*ln(10)/0.122)}")
            if mode=="symmetry_zero":
                body=replace(body,"LEVEL={OUTPUT}","LEVEL={OUTPUT} RMSSYM=0")
            if mode=="symmetry_mid":
                body=replace(body,"LEVEL={OUTPUT}","LEVEL={OUTPUT} RMSSYM=0.5")
            if mode=="symmetry_null":
                p=d/"device-models.inc"; p.write_text(replace(p.read_text(),"i(VSENSE)+v(SYM,REF)/10k","i(VSENSE)"))
            if mode=="ideal_njm":
                for old,new in [
                    ("XOA3 OA3AO OA3AM 0 VN15 0 OA3BM TP4 VP15 NJM4558","B3A OA3AO 0 V={min(13,max(-13,-100000*v(OA3AM)))}\nB3B TP4 0 V={min(13,max(-13,-100000*v(OA3BM)))}"),
                    ("XOA4 OA4AO OA4AM 0 VN15 0 OA4BM OA4BO VP15 NJM4558","B4A OA4AO 0 V={min(13,max(-13,-100000*v(OA4AM)))}\nB4B OA4BO 0 V={min(13,max(-13,-100000*v(OA4BM)))}")]:
                    b=replace(b,old,new)
            if mode=="comp_50p": b=replace(b,"C7 OA2_COMP8 OA2_COMP5 100p","C7 OA2_COMP8 OA2_COMP5 50p")
            if mode=="comp_200p": b=replace(b,"C7 OA2_COMP8 OA2_COMP5 100p","C7 OA2_COMP8 OA2_COMP5 200p")
            if mode=="ideal_rails":
                b=replace(b,"XVR1 VP24 VP15 0 REG15P","VREG1 VP15 0 15")
                b=replace(b,"XVR2 VN24 VN15 0 REG15N","VREG2 VN15 0 -15")
            (d/"163x-board.inc").write_text(b)
            step=.5e-6 if mode=="tight" else 2e-6
            if mode=="tight":
                body=replace(body,"reltol=1e-3 abstol=1e-10 vntol=1e-5","reltol=1e-6 abstol=1e-13 vntol=1e-8")
            body+="\n.options cshunt=1f\n"
            old=m.CIRCUIT;m.CIRCUIT=d
            try:
                data,_=m.run_spice(a,body,f"save {NODES}\ntran {step} .44001 .41999 {step}\nwrdata trace.txt {NODES}")
            finally: m.CIRCUIT=old
        assert data[-1,0]>=.44
        sel=(data[:,0]>=.42)&(data[:,0]<=.44)
        t=data[sel,0]; y=data[sel,1:]; w=np.sqrt(np.gradient(t))
        p=2*np.pi*F*t
        X=np.column_stack([np.ones(len(t))]+[v for k in range(1,11) for v in (np.cos(k*p),np.sin(k*p))])
        c=np.linalg.lstsq(X*w[:,None],y*w[:,None],rcond=None)[0]
        H=c[1::2]-1j*c[2::2]
        result={"mode":mode,"frequency":F,"input_dBu":4,"slider":1,"level":.5,"output_dBu":float(20*np.log10(abs(H[0,0])/(.775*np.sqrt(2)))),"nodes":{}}
        for i,n in enumerate(NAMES):
            h=H[:,i]; amp=np.abs(h)
            result["nodes"][n]={"mean":float(c[0,i]),"fund_peak":float(amp[0]),"K2_peak":float(amp[1]),"K2_dBc":float(20*np.log10(max(amp[1],1e-30)/max(amp[0],1e-30))),"K2_phase_deg":float(np.angle(h[1]*np.exp(-2j*np.angle(H[0,0])),deg=True)),"K3_dBc":float(20*np.log10(max(amp[2],1e-30)/max(amp[0],1e-30))),"THD_K2_K10_pct":float(100*np.linalg.norm(amp[1:])/max(amp[0],1e-30))}
        print(json.dumps(result),flush=True); return result
    except Exception as e:
        result={"mode":mode,"error":str(e),"traceback":traceback.format_exc()};print(json.dumps(result),flush=True);return result
if __name__=="__main__":
    out=Path("measurements");out.mkdir(exist_ok=True)
    baseline=run(("stock",None))
    (out/"k2-isolation.json").write_text(json.dumps([baseline],indent=2))
    if "error" in baseline: raise RuntimeError("Baseline failed")
    dc=baseline["nodes"]["control"]["mean"]
    modes=["frozen","ideal_lf","ideal_ne","frozen_ideal_lf","frozen_ideal_ne","frozen_ideal_vca","symmetry_zero","symmetry_mid","symmetry_null","ideal_njm","comp_50p","comp_200p","ideal_rails","tight"]
    rows=[baseline]
    with ProcessPoolExecutor(max_workers=4) as pool:
        for r in pool.map(run,[(mode,dc) for mode in modes]):
            rows.append(r);(out/"k2-isolation.json").write_text(json.dumps(rows,indent=2))
    for r in rows:
        if "error" not in r: print("SUMMARY",r["mode"],r["output_dBu"],r["nodes"]["out"],flush=True)
