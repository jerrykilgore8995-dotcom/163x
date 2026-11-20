"""Stock-component timing diagnosis. No resistor/capacitor fitting.
All attenuation times measured in dB, using actual input/output fundamental.
Compare threshold-origin steps, precompressed steps, and bare 4301 RMS.
"""
import argparse, json, math, os
from pathlib import Path
import numpy as np
import measure as m
MODE=os.environ.get("MODE","connected")
OUT=Path("measurements");OUT.mkdir(exist_ok=True)
if MODE=="old":
    m.CIRCUIT=Path("old/circuit").resolve()
a=argparse.Namespace(frequency=1000,level_set=.5,load=10000,hiz_trim=None,code_model=None,ngspice="ngspice",shared_worker=False)
base=m.CIRCUIT/"163x-board.inc"
if MODE!="old":
    assert "R34 RMS_IT VN15 2meg" in base.read_text()
    assert "C15 J4R TIME_SUM 10u" in base.read_text()
    assert "VCATRIM=0.52" in base.read_text()
def emit(row):
    print(json.dumps(row),flush=True)
    return row
def peak(db):return .775*np.sqrt(2)*10**(db/20)
def fundamental(data,centers):
    offsets=(np.arange(32)+.5)/32000-.0005
    grid=centers[:,None]+offsets
    si=np.sin(2*np.pi*1000*offsets);co=np.cos(2*np.pi*1000*offsets)
    vals=np.stack([np.interp(grid,data[:,0],data[:,i]) for i in range(1,data.shape[1])],axis=2)
    fund=2/len(offsets)*np.hypot(np.einsum("tcn,c->tn",vals,si),np.einsum("tcn,c->tn",vals,co))
    return fund,vals.mean(axis=1)
def static(db):
    body=m.bench_deck(a,peak(db),float(os.environ.get('SLIDER','1')),False)
    data,_=m.run_spice(a,body,"tran 10u .55 .5 10u\nwrdata trace.txt v(xunit.tp1) v(out) v(xunit.tp6) v(xunit.vca_ec)")
    f,dc=fundamental(data,np.arange(.51,.54,.001))
    gain=float(np.median(20*np.log10(np.maximum(f[:,1],1e-20)/np.maximum(f[:,0],1e-20))))
    return emit(dict(mode=MODE,kind="static",dbu=db,gain_db=gain,detector_V=float(dc[:,2].mean()),ec_V=float(dc[:,3].mean())))
def crossing(t,x,threshold,direction):
    ids=np.flatnonzero(x>=threshold if direction=="up" else x<=threshold)
    if not len(ids):return None
    i=ids[0]
    if not i:return float(t[0]*1000)
    q=(threshold-x[i-1])/(x[i]-x[i-1]) if x[i]!=x[i-1] else 1
    return float((t[i-1]+q*(t[i]-t[i-1]))*1000)
def burst(low,high,fixture):
    start=.8;stop=1.2;end=2.25
    expr=f"({peak(low)}+({peak(high)}-{peak(low)})*edge(time-{start})+({peak(low)}-{peak(high)})*edge(time-{stop}))*sin(6283.185307179586*time)*tanh(100*time)^2"
    edge=".func edge(t) {0.5-0.5*cos(3.141592653589793*min(1,max(0,t/500u)))}"
    if MODE=="standalone":
        body=f"""Bare 4301 datasheet timing fixture
.include vendor/4301_Macro_01.lib
VPLUS VP 0 15
VMINUS VN 0 -15
{edge}
BSIGNAL SRC 0 V={{{expr}}}
CIN SRC A 47u
RIN A IN 10k
RT IT VN 2meg
CT CT 0 10u
XDET IN IT CT OUT VN VP 0 4301RMS
.options reltol=1e-3 abstol=1e-10 vntol=1e-5 method=gear
"""
        nodes="v(src) v(out) v(ct) v(it)"
    else:
        body=m.bench_deck(a,peak(low),float(os.environ.get('SLIDER','1')),False)
        original="BSIGNAL SRC SRC_REF V={AMP*sin(6.283185307179586*FREQ*time)*tanh(100*time)^2}"
        assert original in body
        body=body.replace(original,edge+"\nBSIGNAL SRC SRC_REF V={"+expr+"}")
        nodes="v(xunit.tp1) v(out) v(xunit.tp6) v(j4_r) v(xunit.tp11) v(xunit.time_sum) v(xunit.oa1bo) v(xunit.vca_ec) v(xunit.tp3)"
    data,_=m.run_spice(a,body,"save "+nodes+"\ntran 10u "+str(end)+" .65 10u\nwrdata trace.txt "+nodes)
    assert data[-1,0]>end-.0001
    t=np.arange(.66,end-.001,.00025)
    f,dc=fundamental(data,t)
    if MODE=="standalone":
        g=-dc[:,1]/.0065
        diagnostics=dict(ct_V=dc[:,2].tolist(),it_V=dc[:,3].tolist())
    else:
        g=20*np.log10(np.maximum(f[:,0],1e-20)/np.maximum(f[:,1],1e-20))
        diagnostics=dict(detector_V=dc[:,2].tolist(),ct_V=dc[:,3].tolist(),tp11_V=dc[:,4].tolist(),time_sum_V=dc[:,5].tolist(),oa1bo_V=dc[:,6].tolist(),ec_V=dc[:,7].tolist(),tp3_V=dc[:,8].tolist(),diode_V=(dc[:,5]-dc[:,4]).tolist(),diode_peak_V=np.maximum(np.abs(np.interp(t,data[:,0],data[:,6])-np.interp(t,data[:,0],data[:,5])),0).tolist())
    pre=float(np.median(g[(t>.70)&(t<.78)]));post=float(np.median(g[(t>1.12)&(t<1.18)]));delta=post-pre
    at=(t>=start)&(t<stop);rt=t>=stop
    result=dict(mode=MODE,kind="burst",fixture=fixture,level_set=a.level_set,low_dbu=low,high_dbu=high,input_step_dB=high-low,baseline_db=pre,final_db=post,change_db=delta)
    for frac in (.5,.63,.9,.95):
        key=str(round(100*frac))
        result["attack_"+key+"_ms"]=crossing(t[at]-start,g[at],pre+frac*delta,"up") if delta>0 else None
        result["attack_input_"+key+"_ms"]=crossing(t[at]-start,g[at],pre+frac*(high-low),"up")
        result["release_"+key+"_ms"]=crossing(t[rt]-stop,g[rt],pre+(1-frac)*delta,"down") if delta>0 else None
    result["release_to_1dB_ms"]=crossing(t[rt]-stop,g[rt],pre+1,"down")
    mid=rt&(g>pre+.2*delta)&(g<pre+.8*delta)
    result["mid_release_dB_s"]=-float(np.polyfit(t[mid],g[mid],1)[0]) if mid.sum()>2 else None
    # Record the unclamped versus conducting adaptive node difference.
    if MODE!="standalone":
        result["diode_max_abs_V"]=float(np.max(np.abs(dc[:,5]-dc[:,4])))
        for node,i in [("detector",2),("ec",7),("tp3",8)]:
            result[node+"_step_V"]=float(np.median(dc[(t>1.12)&(t<1.18),i])-np.median(dc[(t>.70)&(t<.78),i]))
    # Same time windows for all physical nodes; signed V/s and absolute
    # ratios. No part changes. Report early/middle/late audio recovery.
    if MODE!="standalone" and delta>0:
        result["release_segments"]=[]
        for lo,hi in [(0,.2),(.2,.5),(.5,.8),(.8,.9),(.9,.95)]:
            mask=rt&(g<=post-lo*delta)&(g>=post-hi*delta)
            if mask.sum()<4:continue
            sl=lambda v:float(np.polyfit(t[mask],v[mask],1)[0])
            d=dict(recovered_fraction=[lo,hi],audio_dB_s=-sl(g))
            for name,i in [("CT",3),("TP6",2),("TP3",8),("EC",7),("TP11",4),("TIME_SUM",5),("OA1BO",6)]:
                d[name+"_V_s"]=sl(dc[:,i])
            d["CT_equiv_uA"]=10*d["CT_V_s"]
            d["TP6_to_EC"]=abs(d["EC_V_s"]/d["TP6_V_s"]) if abs(d["TP6_V_s"])>1e-9 else None
            d["EC_to_audio_mV_dB"]=1000*abs(d["EC_V_s"]/d["audio_dB_s"]) if abs(d["audio_dB_s"])>1e-9 else None
            d["diode_V_mean"]=float(np.mean(dc[mask,5]-dc[mask,4]))
            result["release_segments"].append(d)
    elif MODE=="standalone":
        result["raw_detector_step_V"]=float(np.median(dc[(t>1.12)&(t<1.18),1])-np.median(dc[(t>.70)&(t<.78),1]))
        result["early_CT_V_s"]=float(np.polyfit(t[(t>1.22)&(t<1.27)],dc[(t>1.22)&(t<1.27),2],1)[0])
    emit(result)
    target=OUT/f"{MODE}-{fixture}-{int(high-low)}.json"
    target.write_text(json.dumps(dict(summary=result,t=t.tolist(),gain_or_detector_db=g.tolist(),**diagnostics)))
    return result
if __name__=="__main__":
    a.level_set=0
    high=8.
    target=os.environ.get("TARGET","max")
    # Calibrate actual audio GR relative to the same slider's low-level gain.
    def point(p):
        os.environ["SLIDER"]=str(p)
        low1=static(-85)
        low2=static(-90)
        hi=static(high)
        baseline=low1["gain_db"]
        valid=abs(baseline-low2["gain_db"])<=.1
        gr=baseline-hi["gain_db"]
        emit(dict(kind="slider_calibration",slider=p,low_gain_db=baseline,low_gain_90_db=low2["gain_db"],baseline_valid=valid,gr_db=gr,high_gain_db=hi["gain_db"]))
        return gr,baseline,valid
    gmax,base,valid=point(1)
    p=1.
    if target!="max":
        wanted=float(target)
        gmin,_,_=point(0)
        if not min(gmin,gmax)<=wanted<=max(gmin,gmax):
            emit(dict(kind="unreachable",target=wanted,minimum_slider_gr=gmin,maximum_slider_gr=gmax))
            raise SystemExit(0)
        l,h=0.,1.
        for i in range(14):
            p=(l+h)/2
            g,base,valid=point(p)
            if abs(g-wanted)<=.05:break
            if (g<wanted)==(gmax>gmin):l=p
            else:h=p
    g,base,valid=point(p)
    if not valid:raise RuntimeError("Uncompressed static baseline not verified")
    row=burst(-85,high,"fixed8dbu_"+target)
    row.update(target=target,slider=p,static_gr=g,baseline_residual_gr_db=row["baseline_db"]+base,baseline_valid=abs(row["baseline_db"]+base)<=.1)
    emit(row)
    (OUT/"summary.json").write_text(json.dumps(row,indent=2))
    if not row["baseline_valid"]:raise RuntimeError("Burst did not start at verified uncompressed gain")
