import os,re,json,subprocess,tempfile,shutil
from pathlib import Path
from zipfile import ZipFile
from urllib.request import urlopen
import numpy as np
root=Path(__file__).resolve().parents[1]
vendor=root/'circuit/vendor';vendor.mkdir(exist_ok=True)
from io import BytesIO
with ZipFile(BytesIO(urlopen('https://thatcorp.com/wp-content/uploads/2020/11/THATMacroModels-Rev05.zip').read())) as z:
    for name in z.namelist():
        if Path(name).name in ('4301_Macro_01.lib','300 Series_Macro_01.lib'):
            (vendor/Path(name).name).write_bytes(z.read(name))
array=(vendor/'300 Series_Macro_01.lib').read_text(errors='replace')

# Select manufacturer complementary BJT models; fail rather than substitute placeholders.
models=re.findall(r'(?im)^\s*\.model\s+(\S+)\s+(NPN|PNP)\b',array)
selected={}
for typ in ('NPN','PNP'):
    candidates=[n for n,t in models if t.upper()==typ]
    if not candidates:raise RuntimeError('Vendor BJT model not found: '+typ)
    # Prefer THAT340 or 300A/320 family model names where present.
    selected[typ]=next((n for n in candidates if n.upper().endswith('_NS')),candidates[0])
print('Selected models',selected,flush=True)
(vendor/'array-selected.lib').write_text(array)
base=(root/'circuit/dn125.cir').read_text().replace('THATN',selected['NPN']).replace('THATP',selected['PNP']).rsplit('.end',1)[0]
hz=int(os.environ.get('HZ','1000'))
kind=os.environ['KIND']; db=float(os.environ.get('DBU','4')); knob=float(os.environ.get('MORE','0'))
out=Path('measurements');out.mkdir(exist_ok=True)
def peak(db):return .775*2**.5*10**(db/20)
def run(db,knob,burst=False,low=-85,protocol='new',ac=False):
    amp=peak(db)
    deck=re.sub(r'(?m)^\.param AMP=.*$',f'.param AMP={amp} FREQ={hz} MORE={knob} MAKEUP=.5 SYM=.5',base)
    start,stop=(.6,1.2) if protocol=='160' else (.8,1.2)
    end=2.25 if burst else 1.00001
    step=5e-6 if burst else min(5e-6,.005/hz)
    if ac:
        deck=deck.replace('VIN IN 0 SIN(0 {AMP} {FREQ})','VIN IN 0 DC 0 AC 1')
        cmd='ac dec 48 20 20k\nwrdata trace.txt vdb(out) vp(out)'
    else:
        if burst:
            deck=deck.replace('VIN IN 0 SIN(0 {AMP} {FREQ})',f'VAMP A 0 PWL(0 {peak(low)} {start-1e-6} {peak(low)} {start} {amp} {stop-1e-6} {amp} {stop} {peak(low)} {end} {peak(low)})\nBSIGNAL IN 0 V={{v(A)*sin(6.283185307179586*FREQ*time)*tanh(100*time)^2}}')
        else:
            deck=deck.replace('VIN IN 0 SIN(0 {AMP} {FREQ})','BSIGNAL IN 0 V={AMP*sin(6.283185307179586*FREQ*time)*tanh(100*time)^2}')
        cmd=f'tran {step} {end} {0 if burst else .89999} {step}\nwrdata trace.txt v(in) v(out) v(ec) v(rmsout) v(oa1out) v(sum) v(nem) v(pem)'
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);shutil.copytree(vendor,p/'vendor')
        for method in ('gear','trap'):
            (p/'test.cir').write_text(deck+f'\n.options method={method} maxord=2 reltol=0.001 abstol=1e-10 vntol=1e-5 cshunt=1f\n.control\nset wr_singlescale\n{cmd}\nquit\n.endc\n.end\n')
            try:
                proc=subprocess.run(['ngspice','-b','test.cir'],cwd=p,capture_output=True,text=True,timeout=1800)
                log=proc.stdout+proc.stderr
                (out/f'{kind}-{db}-{knob}-{method}.log').write_text(log)
                if proc.returncode or 'aborted' in log:raise RuntimeError(log[-650:])
                data=np.loadtxt(p/'trace.txt')
                if not ac and data[-1,0]<end-2*step:raise RuntimeError('incomplete transient')
                if not np.all(np.isfinite(data)):raise RuntimeError('nonfinite trace')
                return data
            except Exception as e:print('retry',method,str(e),flush=True)
        raise RuntimeError('Both integrators failed')
def emit(row):
    print(json.dumps(row,allow_nan=False),flush=True)
    (out/'summary.json').write_text(json.dumps(row,indent=2,allow_nan=False))
def harmonic(db,p):
    a=run(db,p);t=.9+np.arange(100000)/1e6;y=np.interp(t,a[:,0],a[:,2])
    h=np.abs(2*np.fft.rfft(y)/len(y))[np.arange(1,21)*int(hz*.1)]
    rel=20*np.log10(np.maximum(h,1e-30)/h[0]);absolute=20*np.log10(np.maximum(h,1e-30)/peak(0))
    return dict(kind=kind,frequency_Hz=hz,input_dBu=db,slider=p,output_dBu=float(absolute[0]),gain_db=float(absolute[0]-db),THD_K2_K20_pct=float(100*np.linalg.norm(h[1:])/h[0]),THD_audio_20k_pct=float(100*np.linalg.norm(h[1:min(20,20000//hz)])/h[0]),harmonics_dBc=rel.tolist(),harmonics_dBu=absolute.tolist(),harmonics_dBFS=(absolute-22).tolist())
def timing(db,p,protocol):
    low=db-40 if protocol=='160' else -85
    a=run(db,p,True,low,protocol)
    start=.6 if protocol=='160' else .8;stop=1.2
    t=np.arange(.2,2.1,.001)
    grid=t[:,None]+(np.arange(100)+.5)/100000
    def fund(col):
        y=np.interp(grid,a[:,0],a[:,col]);w=2*np.pi*1000*(np.arange(100)+.5)/100
        return 2*np.hypot(y@np.sin(w),y@np.cos(w))/100
    gain=20*np.log10(np.maximum(fund(2),1e-30)/np.maximum(fund(1),1e-30))
    baseline=float(np.median(gain[(t>start-.2)&(t<start-.05)]))
    g=baseline-gain;gr=float(np.median(g[(t>1.05)&(t<1.15)]))
    def cross(begin,end,threshold,up):
        ix=np.flatnonzero((t>=begin)&(t<end))
        for i,j in zip(ix,ix[1:]):
            if (g[i]<threshold<=g[j] if up else g[i]>threshold>=g[j]):
                return float(1000*(t[i]+(t[j]-t[i])*(threshold-g[i])/(g[j]-g[i])-begin))
        return None
    row=dict(kind=kind,protocol=protocol,input_dBu=db,slider=p,initial_gain_db=baseline,actual_GR=gr,plateau_drift_db=float(np.ptp(g[(t>1.05)&(t<1.15)])))
    for frac in (.5,.632,.9,.95):
        row['attack_'+str(round(frac*100))+'_ms']=cross(start,stop,frac*gr,True) if gr>0 else None
        row['release_'+str(round(frac*100))+'_ms']=cross(stop,2.1,(1-frac)*gr,False) if gr>0 else None
    r=(t>stop)&(g>.2*gr)&(g<.8*gr)
    row['recovery_slope_dB_s']=float(-np.polyfit(t[r],g[r],1)[0]) if r.sum()>2 else None
    row['release_to_1dB_ms']=cross(stop,2.1,1,False) if gr>1 else 0
    row['release_to_0.1dB_ms']=cross(stop,2.1,.1,False) if gr>.1 else 0
    return row,t,g
if kind in ('harmonics','curve'):
    emit(harmonic(db,knob))
elif kind=='ac':
    a=run(-85,knob,ac=True);np.savetxt(out/'ac.csv',a,delimiter=',',header='frequency_Hz,gain_dB,phase_rad')
    emit(dict(kind=kind,slider=knob,rows=a.tolist()))
else:
    protocol=os.environ.get('PROTOCOL','new')
    target=os.environ.get('TARGET','endpoint')
    if target=='endpoint':row,t,g=timing(db,knob,protocol)
    else:
        wanted=float(target);samples=[]
        for p in np.linspace(0,1,9):
            try:samples.append(timing(db,float(p),protocol))
            except Exception as e:print('slider failed',p,str(e),flush=True)
        if not samples:raise RuntimeError('No converged timing trials')
        best=min(samples,key=lambda x:abs(x[0]['actual_GR']-wanted))
        for l,h in zip(samples,samples[1:]):
            if (l[0]['actual_GR']-wanted)*(h[0]['actual_GR']-wanted)>0:continue
            for _ in range(12):
                if abs(best[0]['actual_GR']-wanted)<.1:break
                q=timing(db,(l[0]['slider']+h[0]['slider'])/2,protocol)
                if abs(q[0]['actual_GR']-wanted)<abs(best[0]['actual_GR']-wanted):best=q
                if (l[0]['actual_GR']-wanted)*(q[0]['actual_GR']-wanted)<=0:h=q
                else:l=q
            break
        row,t,g=best;row.update(target=wanted,target_met=abs(row['actual_GR']-wanted)<.1)
    emit(row);np.savetxt(out/'envelope.csv',np.c_[t,g],delimiter=',',header='seconds,GR_dB')
