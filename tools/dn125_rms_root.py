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
# Isolate the manufacturer detector from the control network and compare
# its CT state and transfer against the full circuit, under identical input.
model=(vendor/'4301_Macro_01.lib').read_text(errors='replace')
m=re.search(r'(?ims)^\s*\.subckt\s+4301RMS\b.*?^\s*\.ends[^\n]*',model)
if not m:raise RuntimeError('RMS macro missing')
print(m[0],flush=True)
kind=os.environ['FIXTURE'];startup=os.environ['STARTUP'];p=float(os.environ.get('MORE','0'))
out=Path('measurements');out.mkdir(exist_ok=True)
levels=[-10,-30,-20,-10,0,10,-10,-30,-50]
def peak(d):return .775*2**.5*10**(d/20)
if kind=='isolated':
    deck="""DN125 RMS isolated
VPLUS VP 0 15
VMINUS VN 0 -15
C1 IN RMSAC 47u
R1 RMSAC RMSIN 28.8k
R5 IT VN 2meg
C4 CT 0 10u
XDET RMSIN IT CT RMSOUT VN VP 0 4301RMS
RLOAD RMSOUT 0 6.04k
.include vendor/4301_Macro_01.lib
"""
else:
    deck=re.sub(r'(?m)^\.param AMP=.*$',f'.param AMP=1 FREQ=1000 MORE={p} MAKEUP=.5 SYM=.5',base)
    deck=re.sub(r'(?m)^VIN IN .*\n','',deck)
points=['0 0','0.02 0','0.05 '+str(peak(levels[0]))]
for i,d in enumerate(levels[1:],1):
    t=.05+i*.8
    points.extend([f'{t} {peak(levels[i-1])}',f'{t+.01} {peak(d)}'])
end=.05+len(levels)*.8
points.append(f'{end} {peak(levels[-1])}')
deck+='\nVAMP A 0 PWL('+' '.join(points)+')\nBSIGNAL IN 0 V={v(A)*sin(6283.185307179586*time)}\n'
if startup=='rails':
    deck=deck.replace('VPLUS VP 0 15','VPLUS VP 0 PWL(0 0 0.01 15)').replace('VMINUS VN 0 -15','VMINUS VN 0 PWL(0 0 0.01 -15)')
elif startup.startswith('ct'):
    deck+=f'\n.ic v(CT)={startup[2:]}\n'
nodes='v(in) v(rmsout) v(ct) v(it) v(rmsin)'
if kind=='full':nodes+=' v(out) v(ec) v(oa1out)'
with tempfile.TemporaryDirectory() as td:
    d=Path(td);shutil.copytree(vendor,d/'vendor')
    for method in ('gear','trap'):
        (d/'test.cir').write_text(deck+f'\n.options method={method} maxord=2 reltol=0.001 abstol=1e-10 vntol=1e-5\n.control\nset wr_singlescale\ntran 10u {end} 0 10u\nwrdata trace.txt {nodes}\nquit\n.endc\n.end\n')
        if (d/'trace.txt').exists():(d/'trace.txt').unlink()
        r=subprocess.run(['ngspice','-b','test.cir'],cwd=d,capture_output=True,text=True,timeout=1200)
        log=r.stdout+r.stderr;(out/(method+'.log')).write_text(log)
        if not (d/'trace.txt').exists():print('failed',method,log[-900:],flush=True);continue
        a=np.loadtxt(d/'trace.txt')
        rows=[]
        for i,db in enumerate(levels):
            t=.05+i*.8+.65+np.arange(10000)/100000
            if a[-1,0]<t[-1]:break
            v=np.stack([np.interp(t,a[:,0],a[:,j]) for j in range(1,a.shape[1])],axis=1)
            row=dict(fixture=kind,startup=startup,method=method,slider=p,input_dbu=db,**{n:float(x) for n,x in zip(nodes.split()[1:],v[:,1:].mean(axis=0))})
            row['expected_rms_V']=.0061*(db+10)
            row['rms_error_V']=row['v(rmsout)']-row['expected_rms_V']
            if kind=='full':
                f=2*np.hypot(np.sin(2*np.pi*1000*t)@v[:,5],np.cos(2*np.pi*1000*t)@v[:,5])/len(t)
                row['output_dbu']=float(20*np.log10(max(f,1e-30)/peak(0)))
            print(json.dumps(row),flush=True);rows.append(row)
        (out/(method+'.json')).write_text(json.dumps(rows,indent=2))
        if len(rows)==len(levels) and max(abs(x['rms_error_V']) for x in rows)<.015:
            print('DETECTOR_TRANSFER_VALID',flush=True);break
    else:raise RuntimeError('No validated RMS transfer')
