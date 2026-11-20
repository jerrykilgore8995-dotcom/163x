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
    body=m.bench_deck(a,peak(db),1,False)
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
        body=m.bench_deck(a,peak(low),1,False)
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
    rows=[]
    if MODE=="standalone":
        for n in (10,20,30):
            try: rows.append(burst(-30,-30+n,"bare"))
            except Exception as e:rows.append(emit(dict(mode=MODE,step=n,error=str(e))))
    else:
        # Infer the intersection of low-level and high-level asymptotes.
        # Use LEVEL SET=0.25 to leave headroom for a 30 dB step.
        a.level_set=float(os.environ.get("LEVEL_SET",".25"))
        static_rows=[]
        for db in range(-95,19,5):
            try:static_rows.append(static(db))
            except Exception as e:emit(dict(mode=MODE,dbu=db,error=str(e)))
        x=np.array([r["dbu"] for r in static_rows]);y=np.array([r["gain_db"] for r in static_rows])
        if len(x)<8:raise RuntimeError("insufficient static reference")
        lo=np.polyfit(x[:4],y[:4],1);hi=np.polyfit(x[-4:],y[-4:],1)
        threshold=float((lo[1]-hi[1])/(hi[0]-lo[0]))
        emit(dict(mode=MODE,kind="threshold",threshold_dbu=threshold,low_slope=float(lo[0]),high_slope=float(hi[0]),ratio=float(1/max(1e-6,1+hi[0]))))
        (OUT/"static.json").write_text(json.dumps(static_rows))
        if not np.isfinite(threshold) or threshold<-85 or threshold>18:
            raise RuntimeError("invalid fitted threshold; inspect static curve")
        # Factory-style stimulus: a settled uncompressed baseline, then an
        # input level 10/20/30 dB above the estimated hard-knee intersection.
        # Soft knee may already compress at that intersection, so do not
        # use it as the low-level stimulus. Verify actual low-level gain.
        unity=float(np.median(y[:4]))
        candidates=[r for r in static_rows if r["dbu"]<threshold and abs(r["gain_db"]-unity)<=.1]
        if not candidates:raise RuntimeError("No verified uncompressed baseline")
        low=max(r["dbu"] for r in candidates)
        emit(dict(mode=MODE,kind="baseline",low_dbu=low,uncompressed_gain_db=unity,threshold_dbu=threshold))
        for n in (10,20,30):
            high=threshold+n
            if high>18:
                emit(dict(mode=MODE,kind="unavailable",above_threshold_db=n,high_dbu=high,reason="exceeds +18 dBu test ceiling"))
                continue
            try:
                row=burst(low,high,"zero_to_compression_"+str(n))
                row["above_threshold_db"]=n
                row["baseline_residual_gr_db"]=row["baseline_db"]+unity
                row["baseline_valid"]=abs(row["baseline_residual_gr_db"])<=.1
                row["final_gr_relative_unity_db"]=row["final_db"]+unity
                emit(row)
                rows.append(row)
            except Exception as e:rows.append(emit(dict(mode=MODE,above_threshold_db=n,error=str(e))))
    (OUT/"summary.json").write_text(json.dumps(rows,indent=2))
    if not any("attack_63_ms" in r and (MODE=="standalone" or r.get("baseline_valid")) for r in rows):raise RuntimeError("no valid burst data")
