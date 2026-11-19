import csv,cmath,math,sys
from pathlib import Path
rows=list(csv.DictReader(open(sys.argv[1])))
if len(rows)!=44: raise RuntimeError("Missing baseline sweep rows")
table=[]
for r in rows:
    if int(r["Hz"])!=1000: continue
    s=int(r["slider_pct"])
    coeffs=[]
    # Individually scale K2/K3/K5 by 2.5 at 10–90%; explicit maximum targets.
    for k in (2,3,5):
        old=complex(float(r[f"K{k}_real"]),float(r[f"K{k}_imag"]))
        target=(float(r["fundamental_peak"])*10**({2:-86,3:-68,5:-101}[k]/20) if s==100 else abs(old)*2.5)
        phase=old/abs(old) if abs(old)>1e-12 else 1+0j
        delta=target*phase-old
        # sin input gives z=-j*exp(j*w*n); coefficient restores its reference phase.
        c=delta/((-1j)**k) if s else 0j
        coeffs.extend([c.real,c.imag])
    table.append(coeffs)
if len(table)!=11: raise RuntimeError("Missing slider calibration")
Path(sys.argv[2]).write_text("#pragma once\ninline constexpr double characterTable[11][6]={\n"+",\n".join("{"+",".join("%.17g"%x for x in a)+"}" for a in table)+"\n};\n")
