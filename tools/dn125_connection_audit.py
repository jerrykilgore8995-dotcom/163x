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
# Verify actual package pin mapping and run DC-control and ascending/descending
# transient fixtures independently. No component substitutions.
model=(vendor/'4301_Macro_01.lib').read_text(errors='replace')
print('VENDOR HEADER AND INTERNAL CONNECTIONS',flush=True)
for line in model.splitlines():
    if re.match(r'(?i)^\s*(\.subckt|x_x|\.ends)',line):print(line,flush=True)
out=Path('measurements');out.mkdir(exist_ok=True)
# Physical pin assignment from DN125 Fig 11; actual vendor order is parsed.
match=re.search(r'(?im)^\s*\.subckt\s+THAT4301\s+([^\r\n]+)((?:\r?\n\s*\+[^\r\n]*)*)',model)
if not match:raise RuntimeError('Full macro not found')
pins=(match[1]+match[2].replace('+',' ')).split()
physical={1:'RMSIN',2:'IT',4:'RMSOUT',5:'CT',6:'SUM',7:'EC',8:'0',9:'0',10:'VN',11:'VP',12:'OUT',13:'VCAOUT',14:'SYMN',15:'0',16:'EC',17:'VCAIN',18:'OA1OUT',19:'OA1M',20:'0'}
print('VENDOR ORDER',pins,flush=True)
if all(re.fullmatch(r'(?i)p?\d+',p) for p in pins):
    nodes=[physical[int(p.lower().removeprefix('p'))] for p in pins]
    instance='XU1 '+' '.join(nodes)+' THAT4301'
    print('VERIFIED INSTANCE',instance,flush=True)
    base=re.sub(r'(?im)^XU1 .*$',instance,base)
else:
    print('Named pins: review header before altering mapping',flush=True)
p=float(os.environ['MORE']);direction=os.environ['DIRECTION']
deck=re.sub(r'(?m)^\.param AMP=.*$',f'.param AMP=1 FREQ=1000 MORE={p} MAKEUP=.5 SYM=.5',base)
def peak(db):return .775*2**.5*10**(db/20)
levels=[-60,-50,-40,-30,-20,-10,0,10] if direction=='up' else [10,0,-10,-20,-30,-40,-50,-60]
points=['0 0','0.02 0','0.05 '+str(peak(levels[0]))]
for i,db in enumerate(levels):
    t=.05+i*.5
    if i:points.extend([f'{t} {peak(levels[i-1])}',f'{t+.005} {peak(db)}'])
points.append(f'{.05+len(levels)*.5} {peak(levels[-1])}')
deck=deck.replace('VIN IN 0 SIN(0 {AMP} {FREQ})','VAMP A 0 PWL('+' '.join(points)+')\nBSIGNAL IN 0 V={v(A)*sin(6283.185307179586*time)}')
# Seed from known reference levels and show all control-node voltages.
deck+='\n.options method=gear maxord=2 reltol=0.001 abstol=1e-10 vntol=1e-5 cshunt=1f\n'
nodes='v(in) v(out) v(ec) v(rmsout) v(oa1out) v(sum) v(nem) v(pem) v(nb) v(pb) v(oa1m) v(morew)'
with tempfile.TemporaryDirectory() as td:
    d=Path(td);shutil.copytree(vendor,d/'vendor')
    (d/'test.cir').write_text(deck+f'\n.control\nset wr_singlescale\ntran 10u 4.05 0 10u\nwrdata trace.txt {nodes}\nquit\n.endc\n.end\n')
    result=subprocess.run(['ngspice','-b','test.cir'],cwd=d,capture_output=True,text=True,timeout=1800)
    log=result.stdout+result.stderr;(out/'spice.log').write_text(log)
    if not (d/'trace.txt').exists():raise RuntimeError(log[-1500:])
    a=np.loadtxt(d/'trace.txt')
    rows=[]
    for i,db in enumerate(levels):
        t=.05+i*.5+.4+np.arange(5000)/100000
        if t[-1]>a[-1,0]:break
        v=np.stack([np.interp(t,a[:,0],a[:,j]) for j in range(1,a.shape[1])],axis=1)
        f=2*np.hypot(np.sin(2*np.pi*1000*t)@v,np.cos(2*np.pi*1000*t)@v)/len(t)
        row=dict(more=p,direction=direction,input_dbu=db,output_dbu=float(20*np.log10(max(f[1],1e-30)/peak(0))),**{n:float(x) for n,x in zip(nodes.split()[2:],v[:,2:].mean(axis=0))})
        print(json.dumps(row),flush=True);rows.append(row)
    (out/'summary.json').write_text(json.dumps(rows,indent=2))
    if len(rows)!=len(levels) or 'aborted' in log:raise RuntimeError('Incomplete sweep')
