"""Public artifact download, not hosted inference. No HF token/account needed."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import urllib.request
import zipfile

GLINER_REV = "443d26d654e0324125a96bebd8e796c14ff2efe6"
ENCODER_REV = "a0484667b22365f84929a935b5e50a51f71f159d"
QWEN_REV = "23749fefcc72300e3a2ad315e1317431b06b590a"
ARTIFACTS = [
    (f"https://huggingface.co/urchade/gliner_multi-v2.1/resolve/{GLINER_REV}/model.safetensors",
     "urchade--gliner_multi-v2.1/model.safetensors", "2100142f31627531497850659dcb3821c99d5e71c08a8e01a98e4b11ef32a199"),
    (f"https://huggingface.co/urchade/gliner_multi-v2.1/resolve/{GLINER_REV}/gliner_config.json",
     "urchade--gliner_multi-v2.1/gliner_config.json", None),
    *[(f"https://huggingface.co/microsoft/mdeberta-v3-base/resolve/{ENCODER_REV}/{name}",
       f"microsoft--mdeberta-v3-base/{name}", None) for name in ("config.json", "tokenizer_config.json", "spm.model")],
    (f"https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/{QWEN_REV}/Qwen3-0.6B-Q8_0.gguf",
     "Qwen3-0.6B-Q8_0.gguf", "9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031"),
    ("https://github.com/ggml-org/llama.cpp/releases/download/b11784/llama-b11784-bin-win-cpu-x64.zip",
     "llama-b11784.zip", "c087ff4931ed497024b8f8703807be8944f66b81a599ddf134f8cfc349db459d"),
]


def sha256(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    cache = parser.parse_args().cache.resolve()
    repo = Path(__file__).resolve().parents[5]
    if cache.is_relative_to(repo):
        parser.error("Model artifacts must live outside this Git repository")
    for url, relative, digest in ARTIFACTS:
        path = cache / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".part")
            print("Downloading", relative, flush=True)
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as target:
                import shutil
                shutil.copyfileobj(response, target)
            if digest and sha256(temporary) != digest:
                raise ValueError(f"Artifact checksum mismatch: {relative}")
            temporary.replace(path)
        if digest and sha256(path) != digest:
            raise ValueError(f"Cached artifact checksum mismatch: {relative}")
        print(relative, path.stat().st_size, sha256(path), flush=True)
    with zipfile.ZipFile(cache / "llama-b11784.zip") as archive:
        destination = cache / "llama-b11784"
        for name in archive.namelist():
            if not (destination / name).resolve().is_relative_to(destination.resolve()):
                raise ValueError("Unsafe archive path")
        archive.extractall(destination)


if __name__ == "__main__":
    main()
