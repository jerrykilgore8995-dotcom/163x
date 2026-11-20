"""Gate user 2150, select validated trimmable 2181 fallback; never substitute an RMS model silently."""
import json,re,subprocess,tempfile
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO
from urllib.request import urlopen
import numpy as np
root=Path(__file__).resolve().parents[1]
out=root/'measurements';out.mkdir(exist_ok=True)
url='https://thatcorp.com/wp-content/uploads/2020/11/THATMacroModels-Rev05.zip'
with ZipFile(BytesIO(urlopen(url,timeout=60).read())) as z:
    names=z.namelist()
    print('Vendor archive:',names,flush=True)
    vca=next(n for n in names if Path(n).name=='2181_Macro_01.lib')
    vendor=z.read(vca).decode(errors='replace')
    rms=[n for n in names if '2252' in n.lower()]
    for n in rms:
        (out/Path(n).name).write_bytes(z.read(n))
print('2181 headers:',re.findall(r'(?im)^\s*\.subckt.*',vendor),flush=True)
user=(root/'circuit/models/dbx2150_user.inc').read_text()
rows=[]
for variant,model,instance in [('2150',user,'XU IN 0 EC SYM BIAS VN OUT VP DBX2150_CORE'),('2181',vendor,'XU IN EC 0 SYM BIAS 0 VP OUT THAT2181B')]:
    for gr in (0,10,30):
        for trim in (.0,.25,.5,.75,1.):
            # Vendor model pin order is the same one used in the 160 adapter.
            # For supplied core, EC+ is pin 3 per its own header.
            ec=(-.0061 if variant=='2150' else -.0061)*gr
            deck=f"""VCA validation
{model}
VPLUS VP 0 15
VMINUS VN 0 -15
VIN SRC 0 SIN(0 1.737 1000)
RIN SRC IN 18k
VEC EC 0 {ec}
RBIAS BIAS VN 5.1k
RUP VP W {max(.001,1-trim)*47000}
RDN W VN {max(.001,trim)*47000}
RFEED W SYM 100k
RREF SYM 0 47
{instance}
* Ideal I/V fixture, not part of production model.
EIV OA 0 OUT 0 -1000000
RF OA OUT 20k
.control
set wr_singlescale
tran 2u .06 .04 2u
wrdata trace.txt v(oa) v(in) v(sym)
quit
.endc
.end
"""
            row=dict(variant=variant,target_gr=gr,trim=trim)
            try:
                with tempfile.TemporaryDirectory() as td:
                    p=Path(td);(p/'test.cir').write_text(deck)
                    r=subprocess.run(['ngspice','-b','test.cir'],cwd=p,capture_output=True,text=True,timeout=30)
                    if 'aborted' in r.stderr or not (p/'trace.txt').exists():raise RuntimeError(r.stderr[-800:])
                    d=np.loadtxt(p/'trace.txt');assert d[-1,0]>=.05999
                t=np.arange(.04,.05999,2e-6); y=np.interp(t,d[:,0],d[:,1])
                X=np.column_stack([np.ones(len(t))]+[v for k in range(1,21) for v in (np.cos(2*np.pi*1000*k*t),np.sin(2*np.pi*1000*k*t))])
                c=np.linalg.lstsq(X,y,rcond=None)[0];h=np.hypot(c[1::2],c[2::2])
                row.update(dc=float(c[0]),fund_peak=float(h[0]),input_node_peak=float(np.max(np.abs(d[:,2]))),sym_mean=float(np.mean(d[:,3])),gain_dB=float(20*np.log10(max(h[0],1e-30)/(1.737*20/18))),k2_dBc=float(20*np.log10(max(h[1],1e-30)/max(h[0],1e-30))),thd_pct=float(100*np.linalg.norm(h[1:])/max(h[0],1e-30)))
            except Exception as e:row['error']=str(e)
            rows.append(row);print(json.dumps(row),flush=True)
            (out/'vca_gate.json').write_text(json.dumps(rows,indent=2))
def gate(variant):
    good=[r for r in rows if r['variant']==variant and 'error' not in r and abs(r['gain_dB']+r['target_gr'])<1 and r['input_node_peak']<.01 and abs(r['dc'])<.1]
    return all(any(r['target_gr']==g for r in good) for g in (0,10,30))
summary=dict(user2150_pass=gate('2150'),vendor2181_pass=gate('2181'),rms2252_files=rms)
print(json.dumps(summary),flush=True);(out/'summary.json').write_text(json.dumps(summary,indent=2))
