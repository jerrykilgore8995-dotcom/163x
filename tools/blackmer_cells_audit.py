import argparse, json, math, tempfile, shutil, re, traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import measure as m

ROOT=m.CIRCUIT
NODES="v(out) v(xunit.tp1) v(xunit.tp6) v(j4_r) v(xunit.tp11) v(xunit.vca_ec) v(xunit.tp3)"
LABELS="out tp1 detector cap timing control tp3".split()
def trial(job):
    hz,mode,dbu,kind,target=job
    slider=1.0
    a=argparse.Namespace(frequency=hz,level_set=.75,load=10000,hiz_trim=None,code_model=None,ngspice="ngspice",shared_worker=False)
    peak=.775*math.sqrt(2)*10**(dbu/20)
    def simulate(variant,offset=0,freeze=None,position=1.0,det_offset=0,low_dbu=None):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td);shutil.copytree(ROOT/"vendor",d/"vendor")
            for f in ("163x-board.inc","device-models.inc"):shutil.copyfile(ROOT/f,d/f)
            b=(d/"163x-board.inc").read_text()
            body=m.bench_deck(a,peak,position,False)
            (d/"163x-board.inc").write_text(b)
            if low_dbu is not None:
                lp=.775*np.sqrt(2)*10**(low_dbu/20)
                original="BSIGNAL SRC SRC_REF V={AMP*sin(6.283185307179586*FREQ*time)*tanh(100*time)^2}"
                assert original in body
                body=body.replace(original,f""".func edge(t) {{0.5-0.5*cos(3.141592653589793*min(1,max(0,t/500u)))}}
BSIGNAL SRC SRC_REF V={{({lp}+({peak}-{lp})*edge(time-.6)+({lp}-{peak})*edge(time-.9))*sin(6283.185307179586*time)*tanh(100*time)^2}}""")
                old=m.CIRCUIT;m.CIRCUIT=d
                try: data,_=m.run_spice(a,body,f"save {NODES}\\ntran 10u 1.55 .52 10u\\nwrdata trace.txt {NODES}".replace("\\n","\n"))
                finally:m.CIRCUIT=old
                assert data[-1,0]>=1.5499
                t=np.arange(.53,1.549,.001)
                grid=t[:,None]+(np.arange(32)+.5)/32000
                ec=np.interp(grid,data[:,0],data[:,6]).mean(axis=1)
                g=-ec/.0061
                pre=float(g[t<.58].mean());post=float(g[(t>.86)&(t<.89)].mean())
                return t,g,pre,post
            step=min(5e-6,.01/hz)
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
        print(json.dumps(row),flush=True);return row
    meta=dict(mode=mode,hz=hz,dbu=dbu,kind=kind,target=target)
    try:
        if kind=="line":
            a.level_set=.5
            for pos in (0,1):
                result=simulate(mode,position=pos)
                amps=np.array(result["out"]["harmonics_peak"]);band=min(20,int(20000/hz))
                emit(dict(**meta,slider=pos,actual_gr=-result["control"]["mean"]/.0061,audio_THD_pct=float(100*np.linalg.norm(amps[1:band])/amps[0]),harmonics_dBFS=(20*np.log10(np.maximum(amps,1e-30)/(.775*np.sqrt(2)))-22).tolist(),nodes=result))
            return dict(**meta,complete=True)
        if kind=="factory":
            # 0 dBV = 1 Vrms; physical level-set scale -30 to +10, 0 marking at .75.
            result=simulate(mode,position=.5)
            amps=np.array(result["out"]["harmonics_peak"]);band=min(20,int(20000/hz))
            thd=float(100*np.linalg.norm(amps[1:])/amps[0])
            audio=float(100*np.linalg.norm(amps[1:band])/amps[0])
            return emit(dict(**meta,level_set=a.level_set,slider=.5,thd_K2_K20_pct=thd,audio_THD_pct=audio,limit_pct={40:.25,1000:.08,10000:.10}[hz],harmonics_dBc=result["out"]["harmonics_dBc"],nodes=result))
        a.level_set=0.0
        # Match actual change in gain, not input step. High level fixed +16 dBu.
        l,h=-70.,dbu-.1
        best=None
        for iteration in range(12):
            low=(l+h)/2
            t,g,pre,post=simulate(mode,position=1,low_dbu=low)
            delta=post-pre
            if best is None or abs(delta-target)<abs(best[0]-target):best=(delta,low,t,g,pre,post)
            if abs(delta-target)<.2:break
            if delta>target:l=low
            else:h=low
        delta,low,t,g,pre,post=best
        at=np.flatnonzero((t>=.6)&(t<.9)&(g>=pre+.63*delta))
        rt=np.flatnonzero((t>=.9)&(g<=pre+.1*delta))
        mid=(t>.902)&(g>pre+.2*delta)&(g<pre+.8*delta)
        def slope(mask):return -float(np.polyfit(t[mask],g[mask],1)[0]) if mask.sum()>2 else None
        return emit(dict(**meta,low_dbu=low,level_set=0,slider=1,baseline_gr=pre,peak_gr=post,actual_gr_change=delta,target_met=abs(delta-target)<.2,attack63_ms=float((t[at[0]]-.6)*1000) if len(at) else None,release90_ms=float((t[rt[0]]-.9)*1000) if len(rt) else None,mid_release_dB_s=slope(mid),trace_t=t.tolist(),trace_gr=g.tolist()))
    except Exception as e:return emit(dict(**meta,error=str(e)))
if __name__=="__main__":
    import os
    out=Path("measurements");out.mkdir(exist_ok=True)
    mode=os.environ["AUDIT_MODE"];kind=os.environ["AUDIT_KIND"];case=int(os.environ["AUDIT_CASE"])
    job=(case,mode,4,kind,0) if kind=="line" else ((case,mode,20*math.log10(1/.775),kind,0) if kind=="factory" else (1000,mode,16,kind,case))
    row=trial(job)
    (out/"result.json").write_text(json.dumps(row,indent=2))
    if "error" in row:raise RuntimeError("Measurement failed")
