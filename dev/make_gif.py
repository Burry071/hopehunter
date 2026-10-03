"""Stitches the CDP frames in _demo/frames into the demo GIF used by the DEV post.

Throwaway tooling, not part of the app:
    python dev/make_gif.py                     # -> shots/demo.gif
    python dev/make_gif.py <framesDir> <out.gif> <width>
"""
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent.parent
frames_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "_demo" / "frames"
out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "shots" / "demo.gif"
width = int(sys.argv[3]) if len(sys.argv) > 3 else 640

manifest = json.loads((frames_dir / "manifest.json").read_text())
frames = []
for entry in manifest["frames"]:
    im = Image.open(frames_dir / entry["file"]).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    frames.append((im.convert("P", palette=Image.ADAPTIVE, colors=256, dither=Image.Dither.NONE),
                   entry["delay"]))

out.parent.mkdir(parents=True, exist_ok=True)
frames[0][0].save(
    out, save_all=True, append_images=[f for f, _ in frames[1:]],
    duration=[d for _, d in frames], loop=0, optimize=True, disposal=1,
)
print(f"{out}  {len(frames)} frames  {sum(d for _, d in frames) / 1000:.1f}s  "
      f"{out.stat().st_size / 1e6:.1f} MB")
