import argparse, json, math, tempfile, shutil, re, traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import measure as m

ROOT=m.CIRCUIT
NODES="v(out) v(xunit.tp1) v(xunit.tp6) v(xunit.j4r) v(xunit.tp11) v(xunit.vca_ec) v(xunit.tp3)"
LABELS="out tp1 detector cap timing control tp3".split()
def trial(job):
    hz,mode,slider,dbu=job
    a=argparse.Namespace(frequency=hz,level_set=.5,load=10000,hiz_trim=None,code_model=None,ngspice="ngspice",shared_worker=False)
    peak=.775*math.sqrt(2)*10**(dbu/20)
    def simulate(variant,offset=0,freeze=None):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);shutil.copytree(ROOT/"vendor",d/"vendor")
            for f in ("163x-board.inc","device-models.inc"):shutil.copyfile(ROOT/f,d/f)
            b=(d/"163x-board.inc").read_text()
            body=m.bench_deck(a,peak,slider,False)
            if "ti" in variant:
                body+="\n.include vendor/RC4558.301\n"
                b=b.replace("XOA3 OA3AO OA3AM 0 VN15 0 OA3BM TP4 VP15 NJM4558","X3A 0 OA3AM VP15 VN15 OA3AO RC4558\nX3B 0 OA3BM VP15 VN15 TP4 RC4558")
                b=b.replace("XOA4 OA4AO OA4AM 0 VN15 0 OA4BM OA4BO VP15 NJM4558","X4A 0 OA4AM VP15 VN15 OA4AO RC4558\nX4B 0 OA4BM VP15 VN15 OA4BO RC4558")
            if "that" in variant:
                # Use actual vendor subcircuit after verifying its documented pin order.
                model=next((d/"vendor").glob("2252*"))
                src=model.read_text(errors="replace")
                match=re.search(r"(?im)^\s*\.subckt\s+(\S+)\s+([^\r\n]+)",src)
                assert match, "No vendor subcircuit header"
                name,pins=match.groups()
                print("VENDOR_HEADER",name,pins,flush=True)
                # THAT library normally uses numbered physical pins; reject unknown ordering.
                pp=pins.split()
                if pp[:8]==list("12345678"):
                    nodes="RMS_IN RMS_BIAS RMS_REF RMS_SYM VN15 J4R THAT_RAW VP15"
                elif pp[:8]==["1","2","3","4","5","6","7","8"]:
                    nodes="RMS_IN RMS_BIAS RMS_REF RMS_SYM VN15 J4R THAT_RAW VP15"
                else:
                    raise ValueError("Unverified THAT2252 pin declaration: "+pins)
                body+=f"\n.include vendor/{model.name}\n"
                old="XIC2 RMS_IN RMS_BIAS RMS_REF RMS_SYM VN15 J4R TP6 VP15 UPC1253H2"
                # Preserve external timing network; adapt output scale and reference as a diagnostic.
                b=b.replace(old,f"XIC2 {nodes} {name}\nEDET TP6 RMS_REF THAT_RAW RMS_REF {5.9/6.1}")
            if "null" in variant:
                p=d/"device-models.inc";p.write_text(p.read_text().replace("i(VSENSE)+v(SYM,REF)/10k","i(VSENSE)"))
            if freeze is not None:
                b=b.replace("EVC_CTRL VCA_DRIVE 0 ECPLUS 0 {VCA_CONTROL_SCALE}",f"VFIX VCA_DRIVE 0 {freeze}")
            elif offset:
                b=b.replace("EVC_CTRL VCA_DRIVE 0 ECPLUS 0 {VCA_CONTROL_SCALE}",f"BCTRL VCA_DRIVE 0 V={{v(ECPLUS)*VCA_CONTROL_SCALE+({offset})}}")
            (d/"163x-board.inc").write_text(b)
            step=min(10e-6,.02/hz)
            if step<10e-6:body+="\n.options cshunt=1f\n"
            start=.42; end=start+max(.02,4/hz)
            old=m.CIRCUIT;m.CIRCUIT=d
            try: data,_=m.run_spice(a,body,f"save {NODES}\ntran {step} {end+step} {start-step} {step}\nwrdata trace.txt {NODES}")
            finally:m.CIRCUIT=old
        assert data[-1,0]>=end
        sel=(data[:,0]>=start)&(data[:,0]<=end);t=data[sel,0];y=data[sel,1:]
        w=np.sqrt(np.gradient(t));p=2*np.pi*hz*t
        X=np.column_stack([np.ones(len(t))]+[v for k in range(1,11) for v in (np.cos(k*p),np.sin(k*p))])
        c=np.linalg.lstsq(X*w[:,None],y*w[:,None],rcond=None)[0];H=c[1::2]-1j*c[2::2]
        nodes={}
        for i,n in enumerate(LABELS):
            h=H[:,i];amps=np.abs(h)
            nodes[n]={"mean":float(c[0,i]),"fund_peak":float(amps[0]),"harmonics_peak":amps.tolist(),"phase_deg":np.angle(h*np.exp(-1j*np.arange(1,11)*np.angle(H[0,0])),deg=True).tolist(),"harmonics_dBc":(20*np.log10(np.maximum(amps,1e-30)/max(amps[0],1e-30))).tolist(),"THD_pct":float(100*np.linalg.norm(amps[1:])/max(amps[0],1e-30))}
        return nodes
    try:
        stock=simulate("stock")
        if mode=="stock": result=stock
        elif mode=="frozen":result=simulate("stock",freeze=stock["control"]["mean"])
        else:
            raw=simulate(mode)
            delta=stock["control"]["mean"]-raw["control"]["mean"]
            result=simulate(mode,offset=delta)
        row={"mode":mode,"hz":hz,"slider":slider,"dbu":dbu,"stock_control":stock["control"]["mean"],"nodes":result}
        print(json.dumps(row),flush=True);return row
    except Exception as e:
        row={"mode":mode,"hz":hz,"slider":slider,"dbu":dbu,"error":str(e),"traceback":traceback.format_exc()};print(json.dumps(row),flush=True);return row
if __name__=="__main__":
    out=Path("measurements");out.mkdir(exist_ok=True)
    jobs=[(f,mode,s,4) for f in (100,1000,5000,10000) for s in (0,1) for mode in ("stock","frozen","null","ti","that","that_ti")]
    rows=[]
    with ProcessPoolExecutor(max_workers=8) as p:
        for r in p.map(trial,jobs):
            rows.append(r);(out/"rms-audit.json").write_text(json.dumps(rows,indent=2))
    if not any(r["mode"]=="that" and "nodes" in r for r in rows):raise RuntimeError("Vendor detector trials did not complete")
