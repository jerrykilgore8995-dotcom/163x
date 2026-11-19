import argparse,json,math
from pathlib import Path
import measure as m
import numpy as np
from concurrent.futures import ThreadPoolExecutor
def case(job):
    hz,slider,level,dbu,mode=job
    a=argparse.Namespace(frequency=hz,level_set=level,load=10000,hiz_trim=None,code_model=None,ngspice="ngspice",shared_worker=False)
    row=m.simulate(a,slider,dbu,False)
    if mode=="isolate":
        # Replace the control drive with its measured DC value, keeping the original load path.
        body=m.bench_deck(a,.775*math.sqrt(2)*10**(dbu/20),slider,False)
        # Override inside the copied subcircuit using a temporary directory local to this diagnostic.
        import tempfile,shutil
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)
            shutil.copytree(m.CIRCUIT/"vendor",d/"vendor")
            shutil.copyfile(m.CIRCUIT/"device-models.inc",d/"device-models.inc")
            shutil.copyfile(m.CIRCUIT/"163x.cir",d/"163x.cir")
            b=(m.CIRCUIT/"163x-board.inc").read_text()
            b=b.replace("EVC_CTRL VCA_DRIVE 0 ECPLUS 0 {VCA_CONTROL_SCALE}",f"VVC_FIXED VCA_DRIVE 0 {row['vca_control_mean_V']:.12g}")
            (d/"163x-board.inc").write_text(b)
            # run_spice copies from module path; use separate processes rather than threads for mutation
            old=m.CIRCUIT;m.CIRCUIT=d
            try:
                frozen=m.simulate(a,slider,dbu,False)
            finally:m.CIRCUIT=old
        row["fixed_control_THD_pct"]=frozen["THD_K2_K20_pct"]
        row["fixed_control_K2_dBc"]=frozen["K2_dBc"]
        row["fixed_control_K3_dBc"]=frozen["K3_dBc"]
    row["mode"]=mode
    print(json.dumps(row),flush=True)
    return row
if __name__=="__main__":
    from concurrent.futures import ProcessPoolExecutor
    cases=[(f,s,.5,4,"isolate") for f in (100,1000) for s in (0,1)]+[(f,.5,.75,20*math.log10(1/.775),"factory") for f in (40,1000,10000)]
    with ProcessPoolExecutor(max_workers=4) as p: rows=list(p.map(case,cases))
    Path("build").mkdir(exist_ok=True)
    Path("build/diagnostics.json").write_text(json.dumps(rows,indent=2))
