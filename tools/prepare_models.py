"""Fetch the device macromodels in the reference deck's vendor directory."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "circuit" / "vendor"
MODELS = {
    "LF353.MOD": "https://www.ti.com/lit/zip/snom253",
    "NE5534.301": "https://www.ti.com/lit/zip/sloj049",
    "4301_Macro_01.lib": "https://thatcorp.com/wp-content/uploads/2020/11/THATMacroModels-Rev05.zip",
}
NJM_REPORT = (
    "https://toucy.sakura.ne.jp/datas/Simulation/LTspice/JRC_Macro/"
    "Operational%20Amplifiers%20Macromodel/NJM4558/NJM4558.pdf"
)


def fetch(url):
    with urlopen(url, timeout=30) as response:
        return response.read()


def njm_model(report):
    with TemporaryDirectory() as directory:
        pdf = Path(directory) / "NJM4558.pdf"
        pdf.write_bytes(report)
        source = subprocess.check_output(["pdftotext", "-layout", str(pdf), "-"], text=True)
    match = re.search(
        r"(?ims)^\s*\.Subckt NJM4558 OUT1.*?^\s*\.ends\s*?$", source
    )
    if not match:
        raise ValueError("NJM4558 report does not contain the expected dual device model")
    model = match[0].strip()
    # The report's rail shunt draws about 16.6 mA per half at +/-15 V.
    # Set the two halves' combined quiescent draw to the NJM4558D's 3.5 mA
    # typical (including its input pair tail currents).
    model, count = re.subn(r"(?im)^(\s*rp\s+3\s+4\s+)1\.8032E3\s*$",
                           r"\g<1>17.4424k", model)
    if count != 1:
        raise ValueError("NJM4558 model's supply resistor did not match")
    return (model + "\n").encode()


def main():
    VENDOR.mkdir(exist_ok=True)
    files = {}
    for filename, url in MODELS.items():
        with ZipFile(BytesIO(fetch(url))) as archive:
            files[filename] = archive.read(filename)
    files["NJM4558.lib"] = njm_model(fetch(NJM_REPORT))
    for filename, data in files.items():
        (VENDOR / filename).write_bytes(data)
        print(f"{sha256(data).hexdigest()}  {filename}")


if __name__ == "__main__":
    main()
