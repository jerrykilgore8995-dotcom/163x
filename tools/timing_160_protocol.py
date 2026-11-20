import os,json,math,argparse
from pathlib import Path
import numpy as np
import measure as m
a=argparse.Namespace(frequency=1000,level_set=0,load=10000,hiz_trim=None,code_model=None,ngspice="ngspice",shared_worker=False)
dbu=float(os.environ["HIGH_DBU"]); target=float(os.environ["TARGET"])
high=.775*math.sqrt(2)*10**(dbu/20);low=high*.01
rate=44100
out=Path("measurements");out.mkdir(exist_ok=True)
def run(p,reference=False):
    body=m.bench_deck(a,low,p,False)
    old="BSIGNAL SRC SRC_REF V={AMP*sin(6.283185307179586*FREQ*time)*tanh(100*time)^2}"
    assert old in body
    body=body.replace(old,f"VAMP AMPSTEP 0 PWL(0 {low} .599999999 {low} .6 {high} 1.199999999 {high} 1.2 {low} 2.2 {low})\nBSIGNAL SRC SRC_REF V={{v(AMPSTEP)*sin(6283.185307179586*time)}}")
    if reference:
        assert "XUNIT" in body.upper()
        # Reference deck uses the same audio path, with EC held at zero.
        import tempfile,shutil
        saved=m.CIRCUIT
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/"circuit";shutil.copytree(saved,dest)
            b=dest/"163x-board.inc";s=b.read_text()
            assert "R8 TP2 ECPLUS 80.6" in s
            b.write_text(s.replace("R8 TP2 ECPLUS 80.6","VREF_EC ECPLUS 0 0"))
            m.CIRCUIT=dest
            try:data,_=m.run_spice(a,body,"tran 5u 2.2 0 5u\nwrdata trace.txt v(out)")
            finally:m.CIRCUIT=saved
    else:data,_=m.run_spice(a,body,"tran 5u 2.2 0 5u\nwrdata trace.txt v(out)")
    assert data[-1,0]>2.199
    t=[];g=[]
    for k in range(1,2100):
        n=round(k*rate/1000);end=round((k+1)*rate/1000)
        tt=np.arange(n,end)/rate;v=np.interp(tt,data[:,0],data[:,1])
        tc=(n+end)/2/rate;amp=high if .6<=tc<1.2 else low
        mag=2*np.hypot(v@np.sin(2*np.pi*1000*tt),v@np.cos(2*np.pi*1000*tt))/len(v)
        t.append(tc);g.append(20*np.log10(max(mag/amp,1e-15)))
    return np.array(t),np.array(g)
t,base=run(0,True)
def point(p):
    _,v=run(p);g=base-v;zero=np.median(g[(t>.4)&(t<.55)]);g-=zero
    gr=float(np.median(g[(t>1.05)&(t<1.15)]))
    print(json.dumps(dict(kind="cal",slider=p,gr=gr,initial_GR=float(zero))),flush=True)
    return (p,gr,g,float(zero))
samples=[]
for p in np.linspace(0,1,5):
    try:samples.append(point(float(p)))
    except Exception as e:print("point failed",p,str(e),flush=True)
if not samples:raise RuntimeError("No valid slider points")
best=min(samples,key=lambda x:abs(x[1]-target))
for l,h in zip(samples,samples[1:]):
    if (l[1]-target)*(h[1]-target)>0:continue
    for _ in range(12):
        if abs(best[1]-target)<.3:break
        q=point((l[0]+h[0])/2)
        if abs(q[1]-target)<abs(best[1]-target):best=q
        if (l[1]-target)*(q[1]-target)<=0:h=q
        else:l=q
    break
p,gr,g,initial=best
def cross(begin,end,value,up):
    ix=np.flatnonzero((t>=begin)&(t<end))
    for i,j in zip(ix,ix[1:]):
        if (g[i]<value<=g[j] if up else g[i]>value>=g[j]):
            return float(1000*(t[i]+(t[j]-t[i])*(value-g[i])/(g[j]-g[i])-begin))
    return None
r=(t>1.2)&(g>.2*gr)&(g<.8*gr)
row=dict(input_dbu=dbu,target=target,actual_GR=gr,initial_GR=initial,slider=p,target_met=abs(gr-target)<.3,attack_ms=cross(.6,1.2,.632*gr,True),release63_ms=cross(1.2,2.1,.368*gr,False),release90_ms=cross(1.2,2.1,.1*gr,False),recovery_slope_dB_s=float(-np.polyfit(t[r],g[r],1)[0]) if r.sum()>1 else None)
print(json.dumps(row),flush=True)
(out/"summary.json").write_text(json.dumps(row,indent=2))
np.savetxt(out/"envelope.csv",np.c_[t,g],delimiter=",",header="seconds,GR_dB")
