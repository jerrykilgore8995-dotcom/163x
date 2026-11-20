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
print(array,flush=True)
# Select manufacturer complementary BJT models; fail rather than substitute placeholders.
models=re.findall(r'(?im)^\s*\.model\s+(\S+)\s+(NPN|PNP)\b',array)
selected={}
for typ in ('NPN','PNP'):
    candidates=[n for n,t in models if t.upper()==typ]
    if not candidates:raise RuntimeError('Vendor BJT model not found: '+typ)
    # Prefer THAT340 or 300A/320 family model names where present.
    selected[typ]=next((n for n in candidates if '340' in n),candidates[0])
print('Selected models',selected,flush=True)
(vendor/'array-selected.lib').write_text(array)
base=(root/'circuit/dn125.cir').read_text().replace('THATN',selected['NPN']).replace('THATP',selected['PNP']).rsplit('.end',1)[0]
hz=int(os.environ['HZ']); kind=os.environ['KIND']
out=Path('measurements');out.mkdir(exist_ok=True)
rows=[]
for db in ([-50,-40,-30,-20,-10,0,10] if kind=='curve' else [4,16]):
    for knob in ([0,.2,.4,.6,.8,1] if kind=='curve' else [0,.5,1]):
        amp=.775*2**.5*10**(db/20)
        deck=re.sub(r'(?m)^\.param AMP=.*$',f'.param AMP={amp} FREQ={hz} MORE={knob} MAKEUP=.5 SYM=.5',base)
        step=min(1e-5,.005/hz); start=.6; end=start+max(.05,10/hz)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);shutil.copytree(vendor,p/'vendor')
            (p/'test.cir').write_text(deck+f'\n.control\nset wr_singlescale\ntran {step} {end+step} {start-step} {step}\nwrdata trace.txt v(out) v(ec) v(rmsout)\nquit\n.endc\n.end\n')
            try:
                proc=subprocess.run(['ngspice','-b','test.cir'],cwd=p,capture_output=True,text=True,timeout=240)
                data=np.loadtxt(p/'trace.txt');assert data[-1,0]>=end
                t=data[:,0]; sel=(t>=start)&(t<=end);t=t[sel];y=data[sel,1:];w=np.sqrt(np.gradient(t))
                X=np.column_stack([np.ones(len(t))]+[v for k in range(1,21) for v in (np.cos(2*np.pi*hz*k*t),np.sin(2*np.pi*hz*k*t))])
                c=np.linalg.lstsq(X*w[:,None],y*w[:,None],rcond=None)[0];h=np.hypot(c[1::2,0],c[2::2,0]);band=min(20,int(20000/hz))
                row=dict(hz=hz,dbu=db,more=knob,output_dbu=20*np.log10(h[0]/(.775*2**.5)),ec_mean=c[0,1],harmonics_dBc=(20*np.log10(np.maximum(h,1e-30)/h[0])).tolist(),harmonics_dBFS=(20*np.log10(np.maximum(h,1e-30)/(.775*2**.5))-22).tolist(),audio_THD_pct=100*np.linalg.norm(h[1:band])/h[0])
            except Exception as e:row=dict(hz=hz,dbu=db,more=knob,error=str(e),log=proc.stdout[-1500:]+proc.stderr[-1500:] if 'proc' in locals() else '')
        print(json.dumps(row),flush=True);rows.append(row);(out/'dn125.json').write_text(json.dumps(rows,indent=2))
if any('error' in r for r in rows):raise SystemExit(1)
