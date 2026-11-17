import argparse
import hashlib
import json
import struct
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SOURCES = (
    "system_ext/bin/ims_bridged",
    "system_ext/lib64/libimsbrd.so",
)


def resolve_source(root, relative):
    partition, remainder = relative.split("/", 1)
    for candidate in (root / relative, root / partition / partition / remainder):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Missing stock file: {relative}")


def validate_elf(data, relative):
    if (len(data) < 64 or data[:7] != b"\x7fELF\x02\x01\x01"
            or struct.unpack_from("<HHI", data, 16) != (3, 183, 1)
            or struct.unpack_from("<H", data, 52)[0] != 64):
        raise ValueError(f"Expected little-endian AArch64 ELF64 ET_DYN: {relative}")


def main():
    parser = argparse.ArgumentParser(description="Import the stock AArch64 IMS bridge and record SHA-256 hashes")
    parser.add_argument("stock_dump", type=Path)
    parser.add_argument("--output", type=Path, default=REPO / "proprietary")
    args = parser.parse_args()

    payloads = []
    records = []
    for relative in SOURCES:
        data = resolve_source(args.stock_dump, relative).read_bytes()
        validate_elf(data, relative)
        payloads.append((relative, data))
        records.append({
            "path": relative,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
            "abi": "arm64-v8a",
        })

    for relative, data in payloads:
        destination = args.output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o755 if "/bin/" in relative else 0o644)

    manifest = args.output / "system_ext/ims-bridge.sources.json"
    manifest.write_text(json.dumps({"sources": records}, indent=2, sort_keys=True) + "\n")
    print(f"Imported {len(payloads)} AArch64 ELF files: {manifest}")


if __name__ == "__main__":
    main()
