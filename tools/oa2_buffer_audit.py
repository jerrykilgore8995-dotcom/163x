import argparse, json, math, tempfile, shutil, re, traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import measure as m

ROOT=m.CIRCUIT
NODES="v(out) v(xunit.tp1) v(xunit.tp6) v(j4_r) v(xunit.tp11) v(xunit.vca_ec) v(xunit.tp3)"
LABELS="out tp1 detector cap timing control tp3".split()
def trial(job):
    hz,mode,dbu=job
    slider=1.0
    a=argparse.Namespace(frequency=hz,level_set=.5,load=10000,hiz_trim=None,code_model=None,ngspice="ngspice",shared_worker=False)
    peak=.775*math.sqrt(2)*10**(dbu/20)
    def simulate(variant,offset=0,freeze=None,position=1.0,det_offset=0):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);shutil.copytree(ROOT/"vendor",d/"vendor")
            for f in ("163x-board.inc","device-models.inc"):shutil.copyfile(ROOT/f,d/f)
            b=(d/"163x-board.inc").read_text()
            body=m.bench_deck(a,peak,position,False)
            if "ti" in variant:
                body+="\n.include vendor/RC4558.301\n"
                b=b.replace("XOA3 OA3AO OA3AM 0 VN15 0 OA3BM TP4 VP15 NJM4558","X3A 0 OA3AM VP15 VN15 OA3AO RC4558\nX3B 0 OA3BM VP15 VN15 TP4 RC4558")
                b=b.replace("XOA4 OA4AO OA4AM 0 VN15 0 OA4BM OA4BO VP15 NJM4558","X4A 0 OA4AM VP15 VN15 OA4AO RC4558\nX4B 0 OA4BM VP15 VN15 OA4BO RC4558")
            if "new" in variant:
                b=re.sub(r'(?m)^R(?:9|10|11A|11B) .*\n','',b)
                b=b.replace('VCA_CONTROL_SCALE={6.1/5.9}','VCA_CONTROL_SCALE=1')
                b=re.sub(r'(?m)^(C\d+ V[PN]15 0 )10n$',r'\g<1>100n',b)
            if "that" in variant or "new" in variant:
                # 4301RMS pin order verified in 160 repo: IN IT CT LEVEL VN VP REF.
                # Separate timing-current input; retain external CT network, avoid double-counting R34.
                body+="\n.include vendor/4301_Macro_01.lib\n"
                old="XIC2 RMS_IN RMS_BIAS RMS_REF RMS_SYM VN15 J4R TP6 VP15 UPC1253H2"
                assert old in b
                b=b.replace(old,"RT_VENDOR IT_VENDOR VN15 2meg\nXIC2 RMS_IN IT_VENDOR J4R DET_RAW VN15 VP15 RMS_REF 4301RMS\nEDET TP6 RMS_REF DET_RAW RMS_REF {5.9/6.5}")
                b=b.replace("R34 J4R VN15 2meg","* R34 replaced by vendor IT timing resistor")
            if "buffer" in variant or "loaded" in variant:
                original="EDET TP6 RMS_REF DET_RAW RMS_REF {5.9/6.5}"
                assert original in b
                # Preserve the same DC and AC gain. The passive divider is high impedance.
                # OA2 pin order: noninverting, inverting, V+, V-, output.
                stage="RSCALE DET_RAW DET_SCALED 60k\nRREF DET_SCALED RMS_REF 590k"
                if "loaded" in variant:
                    # Diagnostic passive adapter, deliberately exposing detector loading.
                    stage=stage.replace("DET_SCALED","TP6")
                else:
                    stage+="\nXBUFFER DET_SCALED TP6 VP15 VN15 TP6 4301OA2"
                b=b.replace(original,stage)
            if "nofb" in variant:
                b=b.replace("R32 TP6 RMS_IN 22meg","* R32 diagnostic open")
            if det_offset:
                b=b.replace("EDET TP6 RMS_REF DET_RAW RMS_REF {5.9/6.5}",f"BDET TP6 RMS_REF V={{v(DET_RAW,RMS_REF)*5.9/6.5+({det_offset})}}")
            if "null" in variant:
                p=d/"device-models.inc";p.write_text(p.read_text().replace("i(VSENSE)+v(SYM,REF)/10k","i(VSENSE)"))
            if freeze is not None:
                b=b.replace("EVC_CTRL VCA_DRIVE 0 ECPLUS 0 {VCA_CONTROL_SCALE}",f"VFIX VCA_DRIVE 0 {freeze}")
            elif offset:
                b=b.replace("EVC_CTRL VCA_DRIVE 0 ECPLUS 0 {VCA_CONTROL_SCALE}",f"BCTRL VCA_DRIVE 0 V={{v(ECPLUS)*VCA_CONTROL_SCALE+({offset})}}")
            (d/"163x-board.inc").write_text(b)
            step=min(5e-6,.005/hz)
            if step<10e-6:body+="\n.options cshunt=1f\n"
            start=.42; end=start+max(.04,8/hz)
            old=m.CIRCUIT;m.CIRCUIT=d
            try: data,_=m.run_spice(a,body,f"save {NODES}\ntran {step} {end+step} {start-step} {step}\nwrdata trace.txt {NODES}")
            finally:m.CIRCUIT=old
        assert data[-1,0]>=end
        sel=(data[:,0]>=start)&(data[:,0]<=end);t=data[sel,0];y=data[sel,1:]
        w=np.sqrt(np.gradient(t));p=2*np.pi*hz*t
        X=np.column_stack([np.ones(len(t))]+[v for k in range(1,21) for v in (np.cos(k*p),np.sin(k*p))])
        c=np.linalg.lstsq(X*w[:,None],y*w[:,None],rcond=None)[0];H=c[1::2]-1j*c[2::2]
        nodes={}
        for i,n in enumerate(LABELS):
            h=H[:,i];amps=np.abs(h)
            nodes[n]={"mean":float(c[0,i]),"fund_peak":float(amps[0]),"harmonics_peak":amps.tolist(),"phase_deg":np.angle(h*np.exp(-1j*np.arange(1,21)*np.angle(H[0,0])),deg=True).tolist(),"harmonics_dBc":(20*np.log10(np.maximum(amps,1e-30)/max(amps[0],1e-30))).tolist(),"THD_pct":float(100*np.linalg.norm(amps[1:])/max(amps[0],1e-30))}
        return nodes
    def emit(row):
        print(json.dumps(row),flush=True)
        return row
    def gr(n):return -n["control"]["mean"]/.0061
    def record(result,target,pos,extra=None):
        amps=np.array(result["out"]["harmonics_peak"])
        fs=(20*np.log10(np.maximum(amps,1e-30)/(.775*np.sqrt(2)))-22).tolist()
        band=min(20,int(20000/hz))
        return emit(dict(mode=mode,hz=hz,dbu=dbu,target=target,slider=pos,actual_gr=gr(result),fundamental_dBFS=fs[0],audio_harmonics_dBFS={f"K{k}":fs[k-1] for k in range(2,band+1)},ultrasonic_dBFS={f"K{k}":fs[k-1] for k in range(band+1,21)},audio_THD_pct=float(100*np.linalg.norm(amps[1:band])/amps[0]),nodes=result,**(extra or {})))
    rows=[]
    try:
        lo=simulate(mode,position=0);hi=simulate(mode,position=1)
        rows.append(record(lo,"min",0));rows.append(record(hi,"max",1))
        for target in ():
            if not min(gr(lo),gr(hi))<=target<=max(gr(lo),gr(hi)):
                rows.append(emit(dict(mode=mode,hz=hz,dbu=dbu,target=target,unattainable=True,gr_min=gr(lo),gr_max=gr(hi))))
                continue
            l,h=0.,1.
            try:
                for _ in range(10):
                    pos=(l+h)/2
                    result=simulate(mode,position=pos)
                    if abs(gr(result)-target)<.05:break
                    if (gr(result)<target)==(gr(lo)<gr(hi)):l=pos
                    else:h=pos
                rows.append(record(result,target,pos,dict(target_error_dB=gr(result)-target)))
            except Exception as e:rows.append(emit(dict(mode=mode,hz=hz,dbu=dbu,target=target,error=str(e))))
        if False:
            try:
                stock=simulate("stock",position=1)
                delta=stock["detector"]["mean"]-hi["detector"]["mean"]
                aligned=simulate(mode,position=1,det_offset=delta)
                rows.append(record(aligned,"detector_dc_aligned",1,dict(detector_offset_V=delta)))
                frozen=simulate(mode,position=1,freeze=hi["control"]["mean"])
                rows.append(record(frozen,"frozen",1))
            except Exception as e:rows.append(emit(dict(mode=mode,hz=hz,dbu=dbu,target="diagnostic",error=str(e))))
    except Exception as e:rows.append(emit(dict(mode=mode,hz=hz,dbu=dbu,error=str(e))))
    return rows
if __name__=="__main__":
    import os
    out=Path("measurements");out.mkdir(exist_ok=True)
    hz=int(os.environ.get("AUDIT_HZ","1000"))
    mode=os.environ.get("AUDIT_MODE","new_ti")
    jobs=[(hz,mode,level) for level in (4,12)]
    rows=[]
    with ProcessPoolExecutor(max_workers=3) as p:
        for batch in p.map(trial,jobs):
            rows.extend(batch);(out/"gr-audit.json").write_text(json.dumps(rows,indent=2))
    if any("error" in r for r in rows):raise RuntimeError("Incomplete diagnostic sweep")
