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
    for k in (2,3,5):
        before=float(r[f"K{k}_dBc"]); after=float(q[f"K{k}_dBc"])
        target={2:-86,3:-68,5:-101}[k] if s==100 else before+20*math.log10(2.5)
        print("K",k,"measured",after,"target",target,flush=True)
        assert abs(after-target)<.35,(key,k,after,target)

 else: assert abs(ratio-1)<.015,(key,ratio)
