"""Reproducible local resource inventory; does not read environment secrets."""
import argparse
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys

import psutil


def inventory():
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(Path.cwd().anchor or "/")
    data = dict(os=platform.platform(), python=sys.version, cpu=platform.processor(),
                physical_cores=psutil.cpu_count(logical=False), threads=psutil.cpu_count(),
                ram_bytes=memory.total, available_ram_bytes=memory.available,
                disk_free_bytes=disk.free,
                runtimes={name: shutil.which(name) for name in ("nvidia-smi", "ollama", "llama-cli")})
    if platform.system() == "Windows":
        command = "[pscustomobject]@{cpu=(Get-CimInstance Win32_Processor).Name; gpu=@(Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM)} | ConvertTo-Json -Depth 4"
        result = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                                capture_output=True, text=True, timeout=30, check=True)
        data["windows"] = json.loads(result.stdout)
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    path = parser.parse_args().output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory(), indent=2), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
