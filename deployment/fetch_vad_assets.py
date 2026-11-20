"""Fetch only pinned, integrity-checked browser assets; no npm install scripts."""
import base64
import hashlib
import io
from pathlib import Path
import sys
import tarfile
from urllib.request import urlopen

VERSION_DIR = "v0.0.31-ort1.22.0"
PACKAGES = [
    (
        "https://registry.npmjs.org/@ricky0123/vad-web/-/vad-web-0.0.31.tgz",
        "ePVq8TvB21sdHSxVMZOEIf9JVa7MAYpaIaNXeGgsPOiMCN8xbPCdF2LS5aYj7VRR3ZxzutedgV9ZplV65IA1Fg==",
        {"package/dist/bundle.min.js": "vad/bundle.min.js",
         "package/dist/vad.worklet.bundle.min.js": "vad/vad.worklet.bundle.min.js",
         "package/dist/silero_vad_v5.onnx": "vad/silero_vad_v5.onnx",
         "package/dist/bundle.min.js.LICENSE.txt": "vad/bundle.min.js.LICENSE.txt"},
    ),
    (
        "https://registry.npmjs.org/onnxruntime-web/-/onnxruntime-web-1.22.0.tgz",
        "Ud/+EBo6mhuaQWt/OjaOk0iNWjXqJoeeMFr6xQEERZdIZH2OWpGzuujz7lfuOBjUa6TEE/sc4nb7Da5dNL34fg==",
        {"package/dist/ort.wasm.min.js": "ort/ort.wasm.min.js",
         "package/dist/ort-wasm-simd-threaded.mjs": "ort/ort-wasm-simd-threaded.mjs",
         "package/dist/ort-wasm-simd-threaded.wasm": "ort/ort-wasm-simd-threaded.wasm"},
    ),
]


def install(destination):
    root = Path(destination) / VERSION_DIR
    for url, integrity, files in PACKAGES:
        with urlopen(url, timeout=120) as response:
            data = response.read(128 * 1024 * 1024)
        if hashlib.sha512(data).digest() != base64.b64decode(integrity):
            raise ValueError("VAD package integrity mismatch")
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            # Do not extract arbitrary package paths or execute package scripts.
            for source, relative in files.items():
                member = archive.getmember(source)
                if not member.isfile():
                    raise ValueError("Expected a regular asset file")
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
    print(f"Installed pinned VAD assets: {root}")


if __name__ == "__main__":
    install(sys.argv[1])
