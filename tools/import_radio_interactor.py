"""Package the stock RadioInteractor in its own phone-UID process with local client DEX."""

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from import_stock import dex_classes, dex_entries, resolve_dump_file, sha256


REPO = Path(__file__).resolve().parents[1]
WORKSPACE = REPO.parents[2]
STOCK_APK = "system_ext/priv-app/radio_interactor_service/radio_interactor_service.apk"
CLIENT_JAR = "system/framework/radio_interactor_common.jar"
TELEPHONY_JAR = "system/framework/telephony-common.jar"
OUTPUT = REPO / "proprietary/system_ext/priv-app/SprdRadioInteractorService/SprdRadioInteractorService.apk"
TARGET_CLASS = "com/android/unisoc/telephony/server/ExtRadioNetworkIndication.smali"
TARGET_METHOD = "public networkRegStateInd(I[I)V"
EXPECTED_METHOD_SHA256 = "e807fd7af0cd0a2503af0b8337e9e374c18fcaf0c4b8a4a5d97fcea5dc7ff1af"
ANDROID = "{http://schemas.android.com/apk/res/android}"
PROCESS = ":radio_interactor"
REPLACEMENT = """.method public networkRegStateInd(I[I)V
    .registers 5

    if-eqz p2, :invalid

    array-length v0, p2

    const/4 v1, 0x4

    if-ge v0, v1, :done

    :invalid
    const-string v0, "ExtRadioNetworkIndication"

    const-string v1, "networkRegStateInd return when data is null."

    invoke-static {v0, v1}, Lcom/android/unisoc/telephony/UtilLog;->logd(Ljava/lang/String;Ljava/lang/String;)V

    :done
    return-void
.end method"""


def run(command):
    subprocess.run([str(argument) for argument in command], check=True)


def canonical(text):
    return "\n".join(line.strip() for line in text.splitlines()
                     if line.strip() and not line.lstrip().startswith("#"))


def canonical_labels(text):
    labels = {}
    return re.sub(r":[a-zA-Z_][a-zA-Z_0-9]*",
                  lambda match: labels.setdefault(match.group(), f":label_{len(labels)}"),
                  canonical(text))


def get_method(text, signature):
    matches = list(re.finditer(r"^\.method " + re.escape(signature)
                              + r"\n.*?^\.end method", text, re.MULTILINE | re.DOTALL))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one method: {signature}")
    return matches[0]


def patch_callback(text, stock_platform):
    empty = get_method(stock_platform, "public startUpdateState(IIII)V").group()
    if canonical(empty) != ".method public startUpdateState(IIII)V\n.registers 5\nreturn-void\n.end method":
        raise ValueError("Stock startUpdateState is not the verified empty implementation")
    match = get_method(text, TARGET_METHOD)
    original = match.group()
    digest = hashlib.sha256(canonical(original).encode()).hexdigest()
    if digest != EXPECTED_METHOD_SHA256:
        raise ValueError(f"Unexpected networkRegStateInd instruction sequence: {digest}")
    for reference in (
        "Lcom/android/internal/telephony/PhoneFactory;->getPhone(I)Lcom/android/internal/telephony/Phone;",
        "Lcom/android/internal/telephony/Phone;->getServiceStateTracker()Lcom/android/internal/telephony/ServiceStateTracker;",
        "Lcom/android/internal/telephony/ServiceStateTracker;->startUpdateState(IIII)V",
    ):
        if text.count(reference) != 1 or original.count(reference) != 1:
            raise ValueError(f"Unexpected phone callback reference count: {reference}")
    return text[:match.start()] + REPLACEMENT + text[match.end():]


def patch_manifest(text):
    root = ET.fromstring(text)
    if (root.get("package") != "com.android.unisoc.telephony.server"
            or root.get(ANDROID + "sharedUserId") != "android.uid.phone"):
        raise ValueError("Unexpected RadioInteractor package or shared UID")
    application = root.find("application")
    if application is None:
        raise ValueError("Missing RadioInteractor application")
    expected = {"name": "RadioInteractorApp", "process": "com.android.phone",
                "persistent": "true", "directBootAware": "true"}
    if any(application.get(ANDROID + key) != value for key, value in expected.items()):
        raise ValueError("Unexpected RadioInteractor application configuration")
    if application.findall("uses-library"):
        raise ValueError("Expected stock application without shared libraries")
    for component in application:
        if (ANDROID + "process" in component.attrib
                or component.get(ANDROID + "isolatedProcess") == "true"):
            raise ValueError("Unexpected component process override")
    services = application.findall("service")
    if (len(services) != 1 or services[0].get(ANDROID + "name")
            != "com.android.unisoc.telephony.server.RadioInteractorService"):
        raise ValueError("Unexpected RadioInteractor service list")
    original = 'android:process="com.android.phone"'
    if text.count(original) != 1:
        raise ValueError("Expected exactly one phone process declaration")
    return text.replace(original, f'android:process="{PROCESS}"')


def manifest_tree(text):
    def visit(element):
        return (element.tag, sorted(element.attrib.items()),
                (element.text or "").strip(), tuple(visit(child) for child in element))
    return visit(ET.fromstring(text))


def disassemble(java, baksmali, source, output, classes=None):
    command = [java, "-jar", baksmali, "d", "--debug-info", "false",
               "--accessor-comments", "false", "-o", output]
    if classes:
        command += ["--classes", classes]
    run(command + [source])
    if not list(output.rglob("*.smali")):
        raise ValueError(f"Disassembler produced no classes: {source}")


def class_set(entries):
    result = set()
    for name, data in entries:
        classes = dex_classes(data)
        if result & classes:
            raise ValueError(f"Duplicate DEX classes: {name}")
        result.update(classes)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock_dump", type=Path)
    parser.add_argument("--java", type=Path, default=WORKSPACE / "prebuilts/jdk/jdk11/linux-x86/bin/java")
    parser.add_argument("--baksmali", type=Path, default=WORKSPACE / "prebuilts/extract-tools/common/smali/baksmali.jar")
    parser.add_argument("--smali", type=Path, default=WORKSPACE / "prebuilts/extract-tools/common/smali/smali.jar")
    parser.add_argument("--apktool", type=Path, default=WORKSPACE / "prebuilts/extract-tools/common/apktool/apktool.jar")
    parser.add_argument("--aapt2", type=Path,
                        help="apktool-compatible aapt2; defaults to the apktool JAR's bundled Linux binary")
    parser.add_argument("--platform-jar", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    sources = [(relative, resolve_dump_file(args.stock_dump, relative))
               for relative in (STOCK_APK, CLIENT_JAR, TELEPHONY_JAR)]
    stock_apk, client_jar, telephony_jar = [source for _, source in sources]
    app_entries = dex_entries(stock_apk)
    client_entries = dex_entries(client_jar)
    if len(app_entries) != 1 or len(client_entries) != 1:
        raise ValueError("Expected single-DEX stock service and client library")
    app_classes = class_set(app_entries)
    client_classes = class_set(client_entries)
    if app_classes & client_classes:
        raise ValueError("Stock service shadows its client library")
    combined = app_classes | client_classes
    required = {"Lcom/android/unisoc/telephony/UtilLog;",
                "Lcom/android/unisoc/telephony/aidl/IRadioInteractor$Stub;"}
    if not required <= client_classes:
        raise ValueError("Missing required RadioInteractor client classes")
    for platform in args.platform_jar:
        collision = combined & class_set(dex_entries(platform))
        if collision:
            raise ValueError(f"RadioInteractor shadows platform classes: {sorted(collision)[:8]}")

    with tempfile.TemporaryDirectory(prefix="import-radio-interactor-") as directory:
        work = Path(directory)
        aapt2 = args.aapt2
        if aapt2 is None:
            aapt2 = work / "aapt2"
            with zipfile.ZipFile(args.apktool) as archive:
                aapt2.write_bytes(archive.read("prebuilt/linux/aapt2_64"))
            aapt2.chmod(0o755)
        aapt2_record = {"name": args.aapt2.name if args.aapt2 else "apktool:prebuilt/linux/aapt2_64",
                        "sha256": sha256(aapt2)}
        decoded = work / "decoded"
        framework = work / "framework"
        run([args.java, "-jar", args.apktool, "d", "-s", "-p", framework,
             "-o", decoded, stock_apk])
        manifest_path = decoded / "AndroidManifest.xml"
        manifest_path.write_text(patch_manifest(manifest_path.read_text()))
        app_smali = work / "app-smali"
        platform_smali = work / "platform-smali"
        disassemble(args.java, args.baksmali, stock_apk, app_smali)
        disassemble(args.java, args.baksmali, telephony_jar, platform_smali,
                    "Lcom/android/internal/telephony/ServiceStateTracker;")
        target = app_smali / TARGET_CLASS
        original = target.read_text()
        stock_platform = (platform_smali / "com/android/internal/telephony/ServiceStateTracker.smali").read_text()
        target.write_text(patch_callback(original, stock_platform))
        for source in app_smali.rglob("*.smali"):
            text = source.read_text()
            if any(reference in text for reference in (
                    "Lcom/android/internal/telephony/PhoneFactory;",
                    "Lcom/android/internal/telephony/Phone;",
                    "Lcom/android/internal/telephony/ServiceStateTracker;")):
                raise ValueError(f"Remaining phone-process dependency: {source.relative_to(app_smali)}")
        run([args.java, "-jar", args.smali, "a", "--api", "33", "--jobs", "1", app_smali,
             "-o", decoded / "classes.dex"])
        verification = work / "verified-smali"
        disassemble(args.java, args.baksmali, decoded / "classes.dex", verification)
        before = {source.relative_to(app_smali) for source in app_smali.rglob("*.smali")}
        after = {source.relative_to(verification) for source in verification.rglob("*.smali")}
        if before != after:
            raise ValueError("Reassembly changed the class set")
        for relative in sorted(before):
            expected = (app_smali / relative).read_text()
            actual = (verification / relative).read_text()
            if str(relative) == TARGET_CLASS:
                if canonical_labels(get_method(actual, TARGET_METHOD).group()) != canonical_labels(REPLACEMENT):
                    raise ValueError("Reassembly changed the replacement callback")
                expected = expected.replace(get_method(expected, TARGET_METHOD).group(), "")
                actual = actual.replace(get_method(actual, TARGET_METHOD).group(), "")
            if canonical(expected) != canonical(actual):
                raise ValueError(f"Reassembly changed an unmodified class or method: {relative}")
        (decoded / "classes2.dex").write_bytes(client_entries[0][1])
        rebuilt = work / "rebuilt.apk"
        run([args.java, "-jar", args.apktool, "b", "--use-aapt2", "-a", aapt2,
             "-p", framework, "-o", rebuilt, decoded])
        verified_apk = work / "verified-apk"
        run([args.java, "-jar", args.apktool, "d", "-s", "-p", framework,
             "-o", verified_apk, rebuilt])
        if manifest_tree((verified_apk / "AndroidManifest.xml").read_text()) != manifest_tree(manifest_path.read_text()):
            raise ValueError("Rebuilt manifest changed attributes, permissions or components")
        result_entries = dex_entries(rebuilt)
        if class_set(result_entries) != combined or result_entries[1][1] != client_entries[0][1]:
            raise ValueError("Rebuilt APK changed the local client DEX or class set")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=args.output.parent, suffix=".apk", delete=False) as stream:
            temporary = Path(stream.name)
        try:
            with zipfile.ZipFile(rebuilt) as source, zipfile.ZipFile(
                    temporary, "w", compression=zipfile.ZIP_DEFLATED) as destination:
                for name in sorted(source.namelist()):
                    if name.upper().startswith("META-INF/") or name.endswith("/"):
                        continue
                    entry = zipfile.ZipInfo(name, (2009, 1, 1, 0, 0, 0))
                    # Soong's platform signing aligns stored entries in the installed APK.
                    entry.compress_type = (zipfile.ZIP_STORED if name == "resources.arsc"
                                           else zipfile.ZIP_DEFLATED)
                    destination.writestr(entry, source.read(name))
            temporary.chmod(0o644)
            temporary.replace(args.output)
        finally:
            temporary.unlink(missing_ok=True)

    manifest = {
        "sources": [{"path": relative, "sha256": sha256(source)} for relative, source in sources],
        "tools": {name: {"name": getattr(args, name).name, "sha256": sha256(getattr(args, name))}
                  for name in ("java", "baksmali", "smali", "apktool")},
        "aapt2": aapt2_record,
        "output_sha256": sha256(args.output),
        "process": PROCESS,
        "shared_uid": "android.uid.phone",
        "service_classes": len(app_classes),
        "local_client_classes": len(client_classes),
        "patched_method": TARGET_METHOD,
        "stock_method_sha256": EXPECTED_METHOD_SHA256,
        "stock_start_update_state": "return-void",
        "importer_sha256": sha256(Path(__file__)),
        "unchanged_classes_verified": len(app_classes) - 1,
        "platform_collision_checks": [{"name": path.name, "sha256": sha256(path)}
                                      for path in args.platform_jar],
    }
    args.output.with_suffix(".sources.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"Packaged {len(combined)} classes in an independent radio process: {args.output}")


if __name__ == "__main__":
    main()
