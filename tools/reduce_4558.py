"""Measure NJM4558, fit a finite-gain/slew limited core, gate full-board parity.

Only the runner-local vendor file is swapped after the reference is measured.
The original circuit and manufacturer model remain the reference.
"""
import argparse
import json
import math
from pathlib import Path
import subprocess
import tempfile
import numpy as np
import measure as m

P=argparse.ArgumentParser()
P.add_argument("--install",action="store_true")
P.add_argument("--output",type=Path,required=True)
args=P.parse_args()
out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
vendor=m.CIRCUIT/"vendor"/"NJM4558.lib"
original=vendor.read_text()
(out/"NJM4558-reference.lib").write_text(original)
def run(label,body,cmd):
    with tempfile.TemporaryDirectory() as d:
        d=Path(d)
        (d/"amp.lib").write_text(original)
        (d/"test.cir").write_text("4558 measurement\n.include amp.lib\n"+body+"\n.control\nset wr_singlescale\nset num_threads=1\n"+cmd+"\nquit\n.endc\n.end\n")
        p=subprocess.run(["ngspice","-b","test.cir"],cwd=d,capture_output=True,text=True,timeout=100)
        (out/(label+".log")).write_text(p.stdout+p.stderr)
        if p.returncode or not (d/"trace.txt").exists() or "aborted" in p.stdout+p.stderr:raise RuntimeError(label+" failed")
        x=np.loadtxt(d/"trace.txt");np.savetxt(out/(label+".csv"),x,delimiter=",")
        if not np.all(np.isfinite(x)):raise RuntimeError(label+" nonfinite")
        return x
base="VP vp 0 15\nVN vn 0 -15\nXU y inm inp vn 0 dummy dummy vp NJM4558\nRLOAD y 0 100k\n"
# The unused second half is in unity feedback at ground.
def dc(label,load=0):
    return run(label,base+"VD inp 0 0\nVM inm 0 0\nIL y 0 "+str(load),
               "dc VD -0.005 0.005 0.000002\nwrdata trace.txt v(y) i(VD) i(VM)")
d=dc("open-loop-dc")
idx=np.where((d[:-1,1]<=0)&(d[1:,1]>0))[0]
if len(idx)!=1:raise RuntimeError("expected unique positive open-loop zero crossing")
i=int(idx[0]);vos=float(np.interp(0,d[i:i+2,1],d[i:i+2,0]))
mask=abs(d[:,1])<3
if mask.sum()<3:raise RuntimeError("insufficient linear DC points")
gain=float(np.polyfit(d[mask,0],d[mask,1],1)[0])
hi=float(np.median(d[-100:,1]));lo=float(np.median(d[:100,1]))
ibp=-float(np.interp(vos,d[:,0],d[:,2]));ibm=-float(np.interp(vos,d[:,0],d[:,3]))
# Repeat DC sweep with output loads to estimate open-loop output resistance near zero.
ld=dc("open-loop-loaded-positive",.0001);ln=dc("open-loop-loaded-negative",-.0001)
# Loaded and unloaded sweeps have the same input voltages.
ro=float(np.median((ln[mask,1]-ld[mask,1])/.0002))
ac=run("open-loop-ac",base+f"VD inp 0 DC {vos:.17g} AC 1\nVM inm 0 0",
       "ac dec 35 1 1e7\nwrdata trace.txt vm(y)")
acgain=ac[0,1]; target=acgain/math.sqrt(2)
ix=np.flatnonzero(ac[:,1]<=target)
if not len(ix) or ix[0]==0:raise RuntimeError("cannot identify dominant pole")
j=ix[0];pole=float(np.exp(np.interp(target,ac[j-1:j+1,1][::-1],np.log(ac[j-1:j+1,0][::-1]))))
slew=run("follower-step",base.replace("inm inp","y inp")+"VD inp 0 pulse(-5 5 100u 20n 20n 100u 200u)",
         "tran 20n 350u 0 20n\nwrdata trace.txt v(y)")
t,y=slew[:,0],slew[:,1];dy=np.diff(y)/np.diff(t)
mid=(abs(y[:-1])<3)&(abs(y[1:])<3)
up=dy[mid&(dy>0)];dn=-dy[mid&(dy<0)]
if len(up)<5 or len(dn)<5:raise RuntimeError("slew measurement failed")
srp=float(np.percentile(up,90));srn=float(np.percentile(dn,90))
# Sanity guards are intentionally wide; no datasheet constants replace a failed fit.
if not (1e3<gain<1e7 and 0.1<pole<1e5 and 0<ro<1e5 and hi>5 and lo<-5 and 1e3<min(srp,srn)<1e8):raise RuntimeError("invalid measured parameters")
cap=1/(2*math.pi*pole*1e6)
params=dict(ga=gain,vos=vos,ip=srp*cap,im=srn*cap,hi=hi,lo=lo,gc=1e-2,cap=cap,ro=ro,ibp=ibp,ibm=ibm)
(out/"fit.json").write_text(json.dumps(dict(**params,pole_Hz=pole,slew_positive_V_s=srp,slew_negative_V_s=srn),indent=2))
print("Measured 4558 parameters",params,flush=True)
p=" ".join(f"{k}={v:.17g}" for k,v in params.items())
reduced=f"""* Reduced control amplifiers measured from NJM4558
.subckt CTRL4558 INP INM VP VN OUT params: {p}
IIP INP 0 {{ibp}}
IIM INM 0 {{ibm}}
BCTRLGM STATE 0 I={{-min(ip,max(-im,ga*(V(INP)-V(INM)-vos)/1meg))}}
RDOM STATE 0 1meg
CDOM STATE 0 {{cap}}
BCTRLCLAMP STATE 0 I={{gc*(max(0,V(STATE)-hi)+min(0,V(STATE)-lo))}}
EBUF BUF 0 STATE 0 1
ROUT BUF OUT {{ro}}
.ends CTRL4558
.subckt NJM4558 OUT1 INM1 INP1 VN INP2 INM2 OUT2 VP
XA INP1 INM1 VP VN OUT1 CTRL4558
XB INP2 INM2 VP VN OUT2 CTRL4558
.ends NJM4558
"""
(out/"NJM4558-reduced.lib").write_text(reduced)
# Measure full-board DC control trajectory and audio transfer at identical
# levels and slider/level-set settings. Compare the entire recovery waveform
# in addition to the steady points; keep the reference rails and diodes intact.
a=argparse.Namespace(frequency=1000,level_set=.5,load=10000,hiz_trim=None,code_model=None,ngspice="ngspice",shared_worker=False)
nodes="v(out) v(xunit.tp3) v(xunit.tp4) v(xunit.tp6) v(xunit.vca_ec) v(xunit.oa3ao) v(xunit.oa4ao) v(xunit.oa4bo)"
def peak(db):return .775*math.sqrt(2)*10**(db/20)
def traces():
    rows={}
    for slider,level,db,f in [(0,.5,-18,1000),(.45,.5,4,1000),(1,0,8,1000),(.75,1,4,100),(1,.5,4,5000),(.45,.5,4,10000),(.5,.5,-45,1000)]:
        a.frequency=f;a.level_set=level
        key=f"{slider}-{level}-{db}-{f}"
        data,_=m.run_spice(a,m.bench_deck(a,peak(db),slider,False),f"tran 5u .55 .45 5u\nwrdata trace.txt {nodes}")
        if data[-1,0]<.5499:raise RuntimeError("incomplete steady trace")
        rows[key]=data
    a.frequency=1000;a.level_set=0
    for slider in (.55,.8,1):
        body=m.bench_deck(a,peak(-65),slider,False)
        old="BSIGNAL SRC SRC_REF V={AMP*sin(6.283185307179586*FREQ*time)*tanh(100*time)^2}"
        new=f".func edge(t) {{0.5-0.5*cos(3.141592653589793*min(1,max(0,t/500u)))}}\nBSIGNAL SRC SRC_REF V={{(AMP+({peak(8)}-AMP)*edge(time-.5)-({peak(8)}-AMP)*edge(time-.8))*sin(6283.185307179586*time)*tanh(100*time)^2}}"
        assert old in body
        data,_=m.run_spice(a,body.replace(old,new),f"tran 10u 1.4 .4 10u\nwrdata trace.txt {nodes}")
        if data[-1,0]<1.3999:raise RuntimeError("incomplete burst")
        rows[f"burst-{slider}"]=data
    return rows
def spectrum(data,f):
    t=np.arange(.50,.55,1/400000)
    y=np.interp(t,data[:,0],data[:,1])
    z=abs(2*np.fft.rfft(y)/len(y));k=round(f*.05)
    return z[k],100*np.linalg.norm(z[np.arange(2,21)[np.arange(2,21)*k<len(z)]*k])/z[k]
ref=traces()
try:
    vendor.write_text(reduced)
    test=traces()
finally:
    vendor.write_text(original)
report={};ok=True
for key,x in ref.items():
    y=test[key]
    if key.startswith("burst"):
        t=np.arange(.41,1.399,.001)
        t=t[:,None]+np.arange(32)[None,:]/32000
        def envelope(a):
            v=np.interp(t,a[:,0],a[:,1])
            return 20*np.log10(np.maximum(2*abs(np.mean(v*np.exp(-2j*np.pi*1000*t),axis=1)),1e-15))
        gx,gy=envelope(x),envelope(y)
        # The soft-knee recovery is compared continuously, not forced linear.
        error=float(np.max(abs(gx-gy)))
        ec=float(np.max(abs(np.interp(t[:,0],x[:,0],x[:,5])-np.interp(t[:,0],y[:,0],y[:,5]))))
        row=dict(gain_trajectory_max_dB=error,ec_max_V=ec,passed=error<=.5 and ec<=.00325)
    else:
        f=int(key.rsplit("-",1)[1]);u,th=spectrum(x,f);v,th2=spectrum(y,f)
        delta=20*math.log10(v/u)
        ec=float(abs(np.mean(x[x[:,0]>.5,5])-np.mean(y[y[:,0]>.5,5])))
        row=dict(output_delta_dB=delta,thd_reference_pct=th,thd_reduced_pct=th2,ec_mean_error_V=ec,passed=abs(delta)<=.15 and abs(th-th2)<=.02 and ec<=.001)
    report[key]=row;ok &= row["passed"]
    np.savez_compressed(out/(key+".npz"),reference=x,reduced=y)
    print(key,row,flush=True)
(out/"board-parity.json").write_text(json.dumps(report,indent=2))
if not ok:raise SystemExit("Reduced 4558 failed full-board parity; original reference retained")
if args.install:
    vendor.write_text(reduced)
    print("Measured reduced 4558 installed in runner-local native seed/compile fixture",flush=True)
