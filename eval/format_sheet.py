"""Grid of one source design rendered into every catalogue format of a run.

    python -m eval.format_sheet --run v6b_formats --source official_core_01 --out /tmp/x.png
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from eval.render import _font, render  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cell", type=int, default=300)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--tasks", default=str(ROOT / "eval" / "testsets" / "formats"))
    a = ap.parse_args()
    run = ROOT / "eval" / "runs" / a.run / "outputs"
    files = sorted(run.glob(f"{a.source}__*.json"), key=lambda p: json.loads(p.read_text())["canvas"]["width"] /
                   json.loads(p.read_text())["canvas"]["height"])
    task0 = json.loads((Path(a.tasks) / "tasks" / files[0].name).read_text())
    cells = [(render(task0["source"], max_size=a.cell)[0], "SOURCE")]
    cells += [(render(json.loads(p.read_text()), max_size=a.cell)[0], p.stem.split("__")[1]) for p in files]
    rows = (len(cells) + a.cols - 1) // a.cols
    sheet = Image.new("RGB", (a.cols * (a.cell + 10) + 10, rows * (a.cell + 30) + 10), (236, 232, 226))
    d = ImageDraw.Draw(sheet)
    for k, (im, label) in enumerate(cells):
        r, c = divmod(k, a.cols)
        x, y = 10 + c * (a.cell + 10), 10 + r * (a.cell + 30)
        sheet.paste(im.convert("RGB"), (x + (a.cell - im.width) // 2, y + (a.cell - im.height) // 2))
        d.text((x, y + a.cell + 4), label, fill=(20, 20, 20), font=_font(13))
    sheet.save(a.out)
    print(a.out)


if __name__ == "__main__":
    main()
