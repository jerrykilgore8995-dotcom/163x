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
            # Squeezer-equivalent detector input current resistor, separate from output load.
            if "inputload" in variant:
                assert "R28 RMS_AC RMS_IN 62k" in b
                b=b.replace("R28 RMS_AC RMS_IN 62k","R28 RMS_AC RMS_IN 28.8k")
            # Preserve existing 163X control-stage DC gain and resistor values.
            # R42=10k, so 100n yields 159Hz, not 264Hz; matched pole uses 60.4n.
            if "cap100" in variant or "capmatched" in variant:
                assert "R42 OA4BM OA4BO 10k" in b
                cv="100n" if "cap100" in variant else "60.4n"
                b=b.replace("R42 OA4BM OA4BO 10k",f"R42 OA4BM OA4BO 10k\nC_DIAG OA4BM OA4BO {cv}")
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
    job=(case,mode,20*math.log10(1/.775),kind,0) if kind=="factory" else (1000,mode,16,kind,case)
    row=trial(job)
    (out/"result.json").write_text(json.dumps(row,indent=2))
    if "error" in row:raise RuntimeError("Measurement failed")
