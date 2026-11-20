"""Flatten the connected retrofit SPICE deck into native MNA devices."""
import ast
from collections import Counter, defaultdict
import math
from pathlib import Path
import re
import sys

source, bias_file, dest = map(Path, sys.argv[1:4])
quiet_rails = sys.argv[4:] == ["--quiet-rails"]
if sys.argv[4:] and not quiet_rails:
    raise ValueError("only --quiet-rails is supported as an option")
top, subs, models, devices = [], {}, {}, []
scales = dict(meg=1e6, t=1e12, g=1e9, k=1e3, m=1e-3, u=1e-6,
              n=1e-9, p=1e-12, f=1e-15)
literal = re.compile(r"(?<![\w.])((?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)((?!e[+-]?\d)[a-z]+)(?![\w.])")

def evaluate(value, scope):
    if "?" in value:
        condition, values = value.strip().strip("{}").strip().split("?")
        positive, negative = values.split(":")
        return evaluate(positive if evaluate(condition,scope) else negative,scope)
    value = literal.sub(lambda m: repr(float(m[1]) * next(
        (v for k, v in scales.items() if m[2].startswith(k)), 1)), value.strip().strip("{}").strip())
    tree = ast.parse(value, mode="eval")
    allowed = (ast.Expression, ast.Load, ast.Constant, ast.Name, ast.BinOp,
               ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.USub, ast.UAdd, ast.Call)
    if any(not isinstance(node, allowed) for node in ast.walk(tree)):
        raise ValueError(f"unsupported parameter expression {value!r}")
    return float(eval(compile(tree, "<circuit-parameter>", "eval"), {"__builtins__": {}},
                      dict(log10=math.log10, max=max, min=min, wiper=lambda x:min(.99999,max(.00001,x)), **scope)))

def read(path, title=False):
    lines = []
    for line in path.read_text(encoding="latin-1").splitlines()[int(title):]:
        line = line.lower().strip().strip("\x1a")
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            lines[-1] += " " + line[1:].strip()
        else:
            lines.append(line)
    current = top
    for line in lines:
        args = line.split()
        directive = args[0]
        if directive == ".include":
            read(next(p for p in path.parent.rglob("*") if p.relative_to(path.parent).as_posix().lower() == args[1]))
        elif directive == ".subckt":
            split = args.index("params:") if "params:" in args else len(args)
            current = []
            subs[args[1]] = (args[2:split], args[split+1:], current)
        elif directive == ".ends":
            current = top
        elif directive not in {".end", ".options", ".func"}:
            current.append(line)

def expand(lines, prefix="", mapping=None, parent=None):
    mapping = mapping or {}
    env = dict(parent or {})
    for line in lines:
        if line.startswith(".param "):
            for field in line.split()[1:]:
                k, v = field.split("=", 1)
                env[k] = evaluate(v, env)
        if line.startswith(".model "):
            m = re.fullmatch(r"\.model\s+(\S+)\s+(\w+)\s*\(\s*(.*?)\s*\)", line)
            if not m:
                raise ValueError(line)
            models[prefix+m[1]] = (m[2], {k:evaluate(v,env) for k,v in
                                       re.findall(r"(\w+)\s*=\s*([^ ,]+)", m[3])})
    def node(n):
        return "0" if n == "0" else mapping.get(n, prefix+n)
    for line in lines:
        orig, *args = line.split()
        kind, name = orig[0], prefix+orig
        if orig in {".model", ".param"}:
            continue
        if kind == "x":
            split = next((i for i,v in enumerate(args) if "=" in v), len(args))
            if split and args[split-1]=="params:":
                args.pop(split-1)
                split-=1
            pins, defaults, body = subs[args[split-1]]
            controls = dict(env)
            for argument in [*defaults,*args[split:]]:
                k,v = argument.split("=", 1)
                controls[k] = evaluate(v, env)
            expand(body,name+".",dict(zip(pins,map(node,args[:split-1]),strict=True)),controls)
            continue
        pins = list(map(node,args[:3 if kind in "qj" else 2]))
        if kind == "k":
            devices.append((kind,name,[],(prefix+args[0],prefix+args[1],evaluate(args[2],env))))
            continue
        if kind == "b":
            value = None
            if name not in {"bsignal","bmains"}:
                if orig=="bsink":
                    value = "comparator", [node(k) for k in ("out","vn","inm","inp")], []
                elif orig=="bdrive":
                    kind = "y"
                    value = ("negativeRegulator" if "xvr2" in prefix else "positiveRegulator"), [node("in"),node("ref")], []
                else:
                    raise ValueError(line)
        elif kind in "dqj":
            terminals=3 if kind in "qj" else 2
            model=args[terminals]
            value=prefix+model if prefix+model in models else model
            if len(args)>terminals+1:
                if len(args)!=terminals+2: raise ValueError(line)
                area=evaluate(args[terminals+1].removeprefix("area="),env)
                if area<=0:raise ValueError(line)
                if area!=1:
                    typ,md=models[value]
                    md=dict(md)
                    if kind=="j":
                        md["beta"]=md.get("beta",1e-4)*area
                        md["is"]=md.get("is",1e-14)*area
                    elif kind=="q":
                        for key,default in (("is",1e-16),("ise",0),("isc",0),("ikf",0),("ikr",0),("cje",0),("cjc",0)):
                            md[key]=md.get(key,default)*area
                        for key in ("rb","rc","re"):
                            if key in md:md[key]/=area
                    else:
                        for key,default in (("is",1e-14),("cjo",0)):md[key]=md.get(key,default)*area
                        if "rs" in md:md["rs"]/=area
                    value=name+"@area"
                    models[value]=(typ,md)
        elif kind in "rclvi":
            expr = args[3] if args[2] == "dc" else args[2]
            if kind=="r": expr=" ".join(args[2:])
            value = evaluate(expr.lstrip(), env)
        elif kind in "egfh":
            parts = args[2:]
            if parts[0].startswith("poly("):
                count = int(parts.pop(0)[5:-1])
                if kind=="e" and not parts[0].startswith("("):
                    ctrl=[tuple(map(node,parts[i:i+2])) for i in range(0,2*count,2)]
                    parts=parts[2*count:]
                else:
                    ctrl=([tuple(map(node,v.strip("()").split(","))) for v in parts[:count]]
                          if kind=="e" else [prefix+v for v in parts[:count]])
                    parts=parts[count:]
                coeff=[evaluate(arg,env) for arg in parts]
                if len(coeff)==count+1:
                    value=ctrl,coeff[0],coeff[1:]
                elif count==1 and kind=="f" and len(coeff)==4 and coeff[:3]==[0,0,0]:
                    kind="z"
                    value=ctrl[0],coeff[3]
                else:
                    raise ValueError(line)
            elif kind in "eg":
                value = [(node(parts[0]),node(parts[1]))], 0, [evaluate(parts[2],env)]
            else:
                value = [prefix+parts[0]], 0, [evaluate(parts[1],env)]
        else:
            raise ValueError(line)
        devices.append((kind,name,pins,value))

read(source/"163x.cir", True)
expand(top)
if quiet_rails:
    # Both reference fixtures are available in tools/measure.py. For the
    # real-time audio/control deck preserve all loading at TP4, with static
    # rails and an algebraic readout of the ladder thresholds.
    rail_parts = {"bmain","bmains","rprimary","cx","lpri","lsecondarya","lsecondaryb",
                  "kta","ktb","kab","rsecondarya","rsecondaryb"}
    board_power = {f"c{i}" for i in range(20,34)}
    board_power |= {f"dcr{i}" for i in range(21,26)}
    board_meter = {f"r{i}" for i in range(47,65)}
    board_meter |= {f"dcr{i}" for i in range(8,21)}
    board_meter |= {"q1","r66","rs1_2_4","rs1_4_6"}
    def retain(part):
        name=part[1]
        if name in rail_parts or name.startswith(("xunit.xvr","xunit.xic3","xunit.xic4","xunit.xic5")):
            return False
        return name.removeprefix("xunit.") not in board_power | board_meter
    devices=[part for part in devices if retain(part)]
    devices.extend((
        ("v","v_rail_positive",["xunit.vp15","0"],15.0),
        ("v","v_rail_negative",["xunit.vn15","0"],-15.0),
        ("r","meter_input_load",["xunit.tp4","xunit.vn15"],50e6/12),
    ))
used = {ctrl for k,_,_,d in devices if k in "fh" for ctrl in d[0]}
known = {"0": (0,0)}
known.update(src=(1,0),mains=(2,0))
nodes, branches = [], []
for kind,name,pins,data in devices:
    if kind=="b" and data is None:
        continue
    if kind == "v" and pins[1] == "0" and name not in used:
        known[pins[0]] = (0,data)
    elif kind in "vehly":
        branches.append(name)
extra = {}
for kind,name,pins,data in devices:
    ctrls = [n for pair in data[0] for n in pair] if kind in "eg" else []
    for node in [*pins,*ctrls]:
        if node not in known and node not in nodes:
            nodes.append(node)
    if kind in "dq":
        keys = ("rc","rb","re") if kind == "q" else ("rs",)
        labels = ("collector","base","emitter") if kind == "q" else ("pos",)
        for key,node,label in zip(keys,pins,labels):
            if models[data][1].get(key):
                extra[name+"#"+label] = node
                nodes.append(name+"#"+label)

variables = nodes+branches
index = {n:i for i,n in enumerate(variables)}
known_index = {n:-i-1 for i,n in enumerate(known)}
def ix(node):
    return index[node] if node in index else known_index[node]
def spice_name(name):
    if "." not in name:
        return name
    path,local = name.rsplit(".",1)
    return f"{local[0]}.{path}.{local}"

header, values = bias_file.read_text(encoding="latin-1").split("Values:",1)
vectors = re.findall(r"(?m)^\s*\d+\s+([vi]\([^\n]+?\))\s+\w+\s*$",header)
values = [float(s) for s in values.split()[1:]]
count = int(re.search(r"No. Variables: (\d+)",header)[1])
assert len(values) >= count and len(vectors) in {count,count-1}
op = dict(zip(vectors,values[-len(vectors):]))
def bias(name):
    if name in extra:
        instance,pin = name.split("#")
        ext = extra[name]
        return op.get(f"v({spice_name(instance)}#{pin})",
                      op.get(f"v({ext})",known.get(ext,(0,0))[1]))
    if name in nodes:
        return op[f"v({name})"]
    branch = spice_name(name)
    return op.get(f"i({branch})", op.get(f"i({branch}#branch)", op.get("i(a$poly$"+branch+")",0.)))

def fmt(x):
    return format(x,".17g")

cpp = ["// Generated from 163x.cir and its manufacturer includes.",
       "inline void loadDeck(Circuit& c) {", f"    c.nodes = {len(nodes)};",
       f"    c.size = {len(variables)};", f"    c.out = {ix('out')};",
       f"    c.control = {ix('xunit.vca_ec')};", f"    c.level = {ix('xunit.tp6')};",
       f"    c.meter = {ix('xunit.tp4')};",
       f"    c.detectorTap = {ix('xunit.tap')};",
       f"    c.detectorHpfSource = {ix('xunit.vdet_hpf')};",
       "    c.bias = {" + ", ".join(fmt(bias(k)) for k in variables) + "};"]
for kind,value in known.values():
    cpp.append(f"    c.constants.push_back({{{kind}, {fmt(value)}}});")
sets = {"d":("is n rs cjo vj m tt fc bv ibv",[1e-14,1,0,0,1,.5,0,.5,0,0]),
        "q":("is bf nf vaf ikf ise ne br nr var ikr isc nc rb rc re cje vje mje cjc vjc mjc tf tr fc",
             [1e-16,100,1,0,0,0,1.5,1,1,0,0,0,2,0,0,0,0,.75,.33,0,.75,.33,0,0,.5]),
        "j":("vto beta is lambda",[-2,1e-4,1e-14,0])}
types = {"d":{"d"},"q":{"npn","pnp"},"j":{"njf","pjf"}}
groups = defaultdict(list)
inductors={name:data for kind,name,pins,data in devices if kind=="l"}
filtered=[device for device in devices if device[0]!="k" and not (device[0]=="b" and device[3] is None)]
for kind,name,pins,data in filtered:
    a,b = map(ix,pins[:2])
    def add(list_name,values):
        cpp.append("    c."+list_name+".push_back({"+values+"}); // "+name)
    if kind=="v" and name not in used and pins[1]=="0":
        continue
    if kind=="r":
        pot={"xunit.r38a":1,"xunit.r38b":2,"xunit.r18a":3,"xunit.r18b":4}.get(name,0)
        if not data: raise ValueError((name,pins,data))
        add("resistors",f"{a}, {b}, {fmt(1/data)}, {pot}")
    elif kind in "ci":
        add("capacitors" if kind=="c" else "currents",f"{a}, {b}, {fmt(data)}")
    elif kind=="v":
        add("sources",f"{a}, {b}, {ix(name)}, {fmt(data)}")
    elif kind=="l":
        k=ix(name)
        add("sources",f"{a}, {b}, {k}, 0")
        add("inductance",f"{k}, {k}, {fmt(data)}")
    elif kind in "byz":
        if kind=="z":
            ctrl,gain=data
            add("cubic",f"{a}, {b}, {ix(ctrl)}, {fmt(gain)}")
        else:
            model,controls,params=data
            if kind=="y":
                k=ix(name)
                add("sources",f"{a}, {b}, {k}, 0")
                a,b=k,ix("0")
            indices=", ".join(map(str,[ix(key) for key in controls]+[-1]*(4-len(controls))))
            values=", ".join(fmt(x) for x in params)
            add("behavioral",f"Behavior::{model}, {a}, {b}, {{{indices}}}, {{{values}}}")
    elif kind in "egfh":
        ctrls,offset,gains=data
        multiplier=1
        if kind in "eh":
            k=ix(name)
            add("sources",f"{a}, {b}, {k}, {fmt(offset)}")
            a,b,multiplier=k,ix("0"),-1
        elif offset:
            add("currents",f"{a}, {b}, {fmt(offset)}")
        for ctrl,gain in zip(ctrls,gains,strict=True):
            if gain:
                p,m=(ix(ctrl),ix("0")) if kind in "fh" else map(ix,ctrl)
                add("controlled",f"{a}, {b}, {p}, {m}, {fmt(gain*multiplier)}")
    else:
        model,md=models[data]
        keys,defaults=sets[kind]
        keys=keys.split()
        assert model in types[kind] and set(md)<=set(keys),(name,model,set(md)-set(keys))
        indices=list(map(ix,pins))
        series=(("rc","collector"),("rb","base"),("re","emitter")) if kind=="q" else (("rs","pos"),)
        for i,(key,label) in enumerate(series):
            if md.get(key):
                inner=ix(name+"#"+label)
                add("resistors",f"{indices[i]}, {inner}, {fmt(1/md[key])}, 0")
                indices[i]=inner
        sign = -1 if model in {"pnp","pjf"} else 1
        model_values=", ".join(fmt(md.get(k,d)) for k,d in zip(keys,defaults,strict=True)
                               if k not in {"rs","rc","rb","re"})
        groups[(kind,model_values,sign)].append((indices,name))
for kind,name,_,data in devices:
    if kind=="k":
        a,b,k=data
        mutual=fmt(k*math.sqrt(inductors[a]*inductors[b]))
        cpp.append(f"    c.inductance.push_back({{{ix(a)}, {ix(b)}, {mutual}}});")
        cpp.append(f"    c.inductance.push_back({{{ix(b)}, {ix(a)}, {mutual}}});")
offsets=defaultdict(int)
calls=defaultdict(list)
variants={"d":("diodes","DModel"),"q":("bjts","QModel"),"j":("jfets","JModel")}
for (kind,model,sign),members in groups.items():
    container,model_type=variants[kind]
    for terminals,name in members:
        cpp.append(f"    c.{container}.push_back({{{', '.join(map(str,terminals))}}}); // {name}")
    params=f"{model_type}{{{model}}}" if kind=="d" else f"{model_type}{{{model}}}, {sign}"
    calls[kind].append(f"    stamp.template operator()<{params}>({offsets[kind]}, {len(members)});")
    offsets[kind]+=len(members)
cpp.append("}")
for kind,(container,_) in variants.items():
    cpp+=["template<class Stamp>", f"inline void stamp_{container}(Stamp&& stamp) {{", *calls[kind], "}"]
dest.parent.mkdir(parents=True,exist_ok=True)
dest.write_text("\n".join(cpp)+"\n")
print("Components:",dict(Counter(row[0] for row in devices)),
      "unknowns:",len(variables),"fixed voltages:",len(known))
