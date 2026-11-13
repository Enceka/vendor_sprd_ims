#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Package stock SPRD private Java interfaces with its IMS app, without a boot jar."""

import argparse
import hashlib
import json
import re
import struct
import tempfile
import zipfile
from pathlib import Path


PRIVATE_JARS = (
    ("system/framework/unisoc_ims_common.jar", "IImsServiceEx$Stub;"),
    ("system/framework/radio_interactor_common.jar", "/RadioInteractor;"),
    ("system_ext/framework/unisoc-framework.jar", "/UniCarrierConfigManager;"),
)
STOCK_APK = "system_ext/priv-app/ims/ims.apk"
NATIVE_LIBS = (
    "libvideo_call_engine_jni.so", "libn3am_jni.so", "libavatar_lite.so",
    "libAVRTTManager.so", "libmme_jrtc.so", "libimsbrd.so",
)
REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "proprietary/system_ext/priv-app/SprdImsService/SprdImsService.apk"
SHARED_JARS = (
    "system/framework/radio_interactor_common.jar",
    "system_ext/framework/unisoc-framework.jar",
    "system_ext/framework/com.unisoc.sdk.common.jar",
)


def dex_classes(data):
    if len(data) < 112 or not re.fullmatch(rb"dex\n0[0-9]{2}\x00", data[:8]):
        raise ValueError("Expected an ordinary stock DEX file")
    size = struct.unpack_from("<I", data, 32)[0]
    if size != len(data):
        raise ValueError("DEX file length does not match its header")
    string_count, string_offset = struct.unpack_from("<II", data, 56)
    strings = []
    for index in range(string_count):
        offset = struct.unpack_from("<I", data, string_offset + index * 4)[0]
        # Skip the UTF-16 length ULEB128. Descriptors use ASCII, independent of
        # DEX's MUTF-8 encoding for other strings.
        for _ in range(5):
            byte = data[offset]
            offset += 1
            if not byte & 0x80:
                break
        else:
            raise ValueError("Invalid DEX string length")
        end = data.index(0, offset)
        strings.append(data[offset:end])
    type_count, type_offset = struct.unpack_from("<II", data, 64)
    types = [strings[struct.unpack_from("<I", data, type_offset + index * 4)[0]]
             for index in range(type_count)]
    class_count, class_offset = struct.unpack_from("<II", data, 96)
    return {types[struct.unpack_from("<I", data, class_offset + index * 32)[0]]
            .decode("ascii") for index in range(class_count)}


def dex_entries(archive):
    with zipfile.ZipFile(archive) as source:
        entries = [(entry, source.read(entry)) for entry in source.namelist()
                   if re.fullmatch(r"classes(?:[2-9]|[1-9][0-9]+)?\.dex", entry)]
    if not entries:
        raise ValueError(f"No classes.dex in {archive}; use a deodexed stock dump")
    return sorted(entries, key=lambda item: 1 if item[0] == "classes.dex"
                  else int(item[0][7:-4]))


def resolve_dump_file(root, relative):
    partition, remainder = relative.split("/", 1)
    candidates = [root / relative, root / partition / partition / remainder]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Missing stock file: {relative}")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_dump", type=Path,
                        help="dump containing system/ and system_ext/ partitions")
    parser.add_argument("--platform-jar", type=Path, action="append", default=[],
                        help="LOS dex jar to check for class collisions (repeatable)")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--engineer-apk", type=Path,
                        help="check the unmodified EngineerMode app for shared-library collisions")
    args = parser.parse_args()

    sources = [(STOCK_APK, resolve_dump_file(args.stock_dump, STOCK_APK))]
    sources += [(relative, resolve_dump_file(args.stock_dump, relative))
                for relative, _ in PRIVATE_JARS]
    native_sources = []
    for partition_dir, abi in (("lib", "armeabi-v7a"), ("lib64", "arm64-v8a")):
        for library in NATIVE_LIBS:
            relative = f"system_ext/{partition_dir}/{library}"
            native_sources.append((relative, resolve_dump_file(args.stock_dump, relative), abi))
    platform_classes = set()
    for jar in args.platform_jar:
        for _, data in dex_entries(jar):
            platform_classes.update(dex_classes(data))

    client_classes = set()
    if args.engineer_apk:
        for _, data in dex_entries(args.engineer_apk):
            client_classes.update(dex_classes(data))
    shared_classes = set()
    shared_records = []
    shared_sources = []
    for relative in SHARED_JARS:
        source = resolve_dump_file(args.stock_dump, relative)
        classes = set()
        for _, data in dex_entries(source):
            new_classes = dex_classes(data)
            if classes & new_classes:
                raise ValueError(f"Duplicate classes inside shared library: {relative}")
            classes.update(new_classes)
        collision = classes & (platform_classes | client_classes | shared_classes)
        if collision:
            raise ValueError(f"Shared SDK shadows client/platform classes: {sorted(collision)[:8]}")
        shared_classes.update(classes)
        shared_sources.append(source)
        shared_records.append({"path": relative, "sha256": sha256(source),
                               "classes": len(classes)})

    seen = set()
    records = []
    appended = []
    app_entries = dex_entries(sources[0][1])
    for relative, source in sources:
        source_classes = set()
        for name, data in dex_entries(source):
            classes = dex_classes(data)
            duplicates = classes & (seen | source_classes)
            if duplicates:
                raise ValueError(f"Duplicate classes in {relative}: {sorted(duplicates)[:8]}")
            if relative != STOCK_APK:
                collisions = classes & platform_classes
                if collisions:
                    raise ValueError(f"Private library shadows LOS classes: {sorted(collisions)[:8]}")
                appended.append(data)
            source_classes.update(classes)
        seen.update(source_classes)
        if relative != STOCK_APK:
            required = dict(PRIVATE_JARS)[relative]
            if not any(name.endswith(required) for name in source_classes):
                raise ValueError(f"Unexpected stock library: {relative} lacks {required}")
        records.append({"path": relative, "sha256": sha256(source),
                        "classes": len(source_classes)})

    native_entries = {}
    for relative, source, abi in native_sources:
        data = source.read_bytes()
        expected_class = 2 if abi == "arm64-v8a" else 1
        expected_machine = 183 if abi == "arm64-v8a" else 40
        if (data[:4] != b"\x7fELF" or data[4] != expected_class
                or data[5] != 1 or struct.unpack_from("<H", data, 18)[0] != expected_machine):
            raise ValueError(f"Unexpected native architecture: {relative}")
        native_entries[f"lib/{abi}/{source.name}"] = data
        records.append({"path": relative, "sha256": sha256(source), "abi": abi})

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=args.output.parent, suffix=".apk", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with zipfile.ZipFile(sources[0][1]) as source, zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_DEFLATED) as destination:
            for entry in source.infolist():
                # The build signs the imported app with its platform key.
                if entry.filename.upper().startswith("META-INF/"):
                    continue
                if entry.filename in native_entries:
                    if source.read(entry) != native_entries[entry.filename]:
                        raise ValueError(f"Existing APK native library differs: {entry.filename}")
                    continue
                destination.writestr(entry, source.read(entry))
            next_index = max(1 if name == "classes.dex" else int(name[7:-4])
                             for name, _ in app_entries) + 1
            for data in appended:
                entry = zipfile.ZipInfo(f"classes{next_index}.dex", (2009, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                destination.writestr(entry, data)
                next_index += 1
            for name, data in sorted(native_entries.items()):
                entry = zipfile.ZipInfo(name, (2009, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                destination.writestr(entry, data)
        temporary.chmod(0o644)
        temporary.replace(args.output)
    finally:
        temporary.unlink(missing_ok=True)
    manifest = {"sources": records, "output_sha256": sha256(args.output),
                "added_dex_files": len(appended),
                "native_library_entries": sorted(native_entries),
                "platform_collision_checks": [jar.name for jar in args.platform_jar]}
    args.output.with_suffix(".sources.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    shared_output = REPO / "proprietary/system_ext/framework"
    shared_output.mkdir(parents=True, exist_ok=True)
    for source in shared_sources:
        with tempfile.NamedTemporaryFile(dir=shared_output, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(source.read_bytes())
        temporary.chmod(0o644)
        temporary.replace(shared_output / source.name)
    shared_manifest = {"sources": shared_records,
                       "platform_collision_checks": [jar.name for jar in args.platform_jar],
                       "engineer_apk_sha256": sha256(args.engineer_apk)
                       if args.engineer_apk else None}
    (shared_output / "sprd-radio-sdk.sources.json").write_text(
        json.dumps(shared_manifest, indent=2, sort_keys=True) + "\n")
    print(f"Packaged {len(seen)} classes, {len(appended)} private DEX files and "
          f"{len(native_entries)} native libraries: {args.output}")


if __name__ == "__main__":
    main()
