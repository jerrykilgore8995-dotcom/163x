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
        g=dc[:,1]/.0065
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
        a.level_set=.25
        static_rows=[]
        for db in range(-60,19,5):
            try:static_rows.append(static(db))
            except Exception as e:emit(dict(mode=MODE,dbu=db,error=str(e)))
        x=np.array([r["dbu"] for r in static_rows]);y=np.array([r["gain_db"] for r in static_rows])
        if len(x)<8:raise RuntimeError("insufficient static reference")
        lo=np.polyfit(x[:4],y[:4],1);hi=np.polyfit(x[-4:],y[-4:],1)
        threshold=float((lo[1]-hi[1])/(hi[0]-lo[0]))
        emit(dict(mode=MODE,kind="threshold",threshold_dbu=threshold,low_slope=float(lo[0]),high_slope=float(hi[0]),ratio=float(1/max(1e-6,1+hi[0]))))
        (OUT/"static.json").write_text(json.dumps(static_rows))
        if not np.isfinite(threshold) or threshold<-55 or threshold>18:
            raise RuntimeError("invalid fitted threshold; inspect static curve")
        for n in (10,20,30):
            for label,low in [("threshold",threshold),("below_threshold",threshold-5),("precompressed",threshold+8)]:
                if low+n>18:continue
                try:rows.append(burst(low,low+n,label))
                except Exception as e:rows.append(emit(dict(mode=MODE,fixture=label,step=n,error=str(e))))
    (OUT/"summary.json").write_text(json.dumps(rows,indent=2))
    if not any("attack_63_ms" in r for r in rows):raise RuntimeError("no valid burst data")
