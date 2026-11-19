import csv,cmath,math,sys
from pathlib import Path
rows=list(csv.DictReader(open(sys.argv[1])))
if len(rows)!=44: raise RuntimeError("Missing baseline sweep rows")
table=[]
for r in rows:
    if int(r["Hz"])!=1000: continue
    s=int(r["slider_pct"])
    coeffs=[]
    total=float(r["fundamental_peak"])*float(r["THD_pct"])/100*2.5
    # Final harmonic POWER split, with K3 dominant and K5 next among odd orders.
    for k,fraction in [(2,.35),(3,.65*.85),(5,.65*.15)]:
        old=complex(float(r[f"K{k}_real"]),float(r[f"K{k}_imag"]))
        target=math.sqrt(max(0.,total*total-float(r["other_harmonic_power"])) * fraction)
        phase=old/abs(old) if abs(old)>1e-12 else 1+0j
        delta=target*phase-old
        # sin input gives z=-j*exp(j*w*n); coefficient restores its reference phase.
        c=delta/((-1j)**k) if s else 0j
        coeffs.extend([c.real,c.imag])
    table.append(coeffs)
if len(table)!=11: raise RuntimeError("Missing slider calibration")
Path(sys.argv[2]).write_text("#pragma once\ninline constexpr double characterTable[11][6]={\n"+",\n".join("{"+",".join("%.17g"%x for x in a)+"}" for a in table)+"\n};\n")
