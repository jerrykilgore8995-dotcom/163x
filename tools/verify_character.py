import csv,sys,math
a,b=[{(int(r["Hz"]),int(r["slider_pct"])):r for r in csv.DictReader(open(p))} for p in sys.argv[1:]]
assert len(a)==len(b)==44
for key,r in a.items():
 q=b[key];hz,s=key;ratio=float(q["THD_pct"])/float(r["THD_pct"])
 gr=abs(float(q["GR_peak_dB"])-float(r["GR_peak_dB"]))
 level=abs(float(q["output_dBu"])-float(r["output_dBu"]))
 print(hz,s,"THD ratio",ratio,"GR delta",gr,"output delta",level,flush=True)
 assert gr<.001 and level<.01
 if hz==1000 and s:
    assert 2.375<=ratio<=2.625
    powers=[10**(float(q[f"K{k}_dBc"])/10) for k in range(2,21)]
    odd=sum(powers[1::2])/sum(powers)
    assert .62<=odd<=.68,odd
 else: assert abs(ratio-1)<.015,(key,ratio)
