"""Capture every circuit state after the power-up transient for native MNA."""
import os
from pathlib import Path
import subprocess
import sys

from measure import CIRCUIT, POWER

out = Path(sys.argv[1]).resolve()
if any(char.isspace() for char in str(out)):
    raise ValueError("ngspice seed output path must not contain whitespace")
out.parent.mkdir(parents=True, exist_ok=True)
deck = CIRCUIT / "native-seed.tmp.cir"
body = (CIRCUIT / "163x.cir").read_text().rsplit(".end", 1)[0]
body = body.replace("AMP=0.1", "AMP=0")
deck.write_text(body + POWER + f"""
.control
set filetype=ascii
set num_threads=1
tran 10u 0.5 0.49998 10u
write {out.as_posix()} all
quit
.endc
.end
""")
try:
    subprocess.run([os.environ.get("NGSPICE", "ngspice"), "-b", deck.name], cwd=CIRCUIT, check=True)
    if not out.is_file():
        raise RuntimeError("ngspice did not produce the native state")
finally:
    deck.unlink()
