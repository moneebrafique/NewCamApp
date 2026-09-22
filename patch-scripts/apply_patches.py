#!/usr/bin/env python3
"""
Applies all patches to a freshly apktool-decompiled GoogleCamera tree:
1. Rename the package + all provider authorities (so it installs as a
   separate app alongside the real GoogleCamera, and doesn't collide with
   its content-provider authorities).
2. Neuter Pairip's SignatureCheck.verifyIntegrity() (we sign with our own
   key, not Google's, so their signature check would otherwise fire).
3. Add our new OverlayActivity to the manifest.
4. Insert a small, hand-written smali snippet into BottomBar's
   onFinishInflate() that creates a new button and wires it to launch
   OverlayActivity.
5. Inject a crash/debug logger at the very top of the real entry
   Activity's onCreate(), so we can capture what's happening even if
   something fails before BottomBar (or anything else) ever runs.

Register strategy: rather than allocating new high-numbered registers
(which requires bumping .registers/.locals and risks exceeding the
4-bit v0-v15 limit of non-/range instructions), we always reuse the
lowest-numbered local registers (v0, v1, v2). This is safe because:
  - At the very START of a method, the dex verifier guarantees the
    original code never reads a local register before writing it first
    -- so any local register is safe to clobber before original code
    runs, since original code will overwrite it before ever reading it.
  - At the very END of a method (right before return-void), nothing
    reads any register afterward, so clobbering low registers there is
    equally safe.
This avoids touching the register-count declaration entirely.

Run from the repo root: python3 patch-scripts/apply_patches.py decompiled/
"""
import re
import sys
from pathlib import Path

OLD_PACKAGE = "com.google.android.GoogleCamera"
NEW_PACKAGE = "com.example.gcammod"
OLD_AUTHORITY_2 = "com.google.android.apps.camera.specialtypes.SpecialTypesProvider"
NEW_AUTHORITY_2 = "com.example.gcammod.specialtypes.SpecialTypesProvider"


def find_smali_file(decompiled: Path, relative_path: str) -> Path:
    """
    Large apps get split by apktool into smali/, smali_classes2/,
    smali_classes3/, etc. (one per dex file). A given class can end up in
    any of them, so search all of them rather than assuming smali/.
    """
    candidates = sorted(decompiled.glob("smali*/" + relative_path))
    if not candidates:
        print(f"ERROR: could not find {relative_path} in any smali* directory under {decompiled}")
        print("Available smali* directories:", [p.name for p in decompiled.glob("smali*") if p.is_dir()])
        sys.exit(1)
    if len(candidates) > 1:
        print(f"WARNING: {relative_path} found in multiple places: {candidates}; using the first")
    return candidates[0]


def patch_manifest(decompiled: Path) -> None:
    manifest = decompiled / "AndroidManifest.xml"
    text = manifest.read_text(encoding="utf-8")

    before = text
    text = text.replace(OLD_PACKAGE, NEW_PACKAGE)
    text = text.replace(OLD_AUTHORITY_2, NEW_AUTHORITY_2)
    if text == before:
        print("WARNING: manifest patch made no changes -- check OLD_PACKAGE constant")

    new_activity = (
        '        <activity android:name="com.example.gcammod.OverlayActivity" '
        'android:theme="@android:style/Theme.Translucent.NoTitleBar" '
        'android:exported="false"/>\n'
    )
    if "com.example.gcammod.OverlayActivity" not in text:
        text = text.replace("</application>", new_activity + "    </application>")

    manifest.write_text(text, encoding="utf-8")
    print(f"Patched manifest: {manifest}")


def patch_signature_check(decompiled: Path) -> None:
    path = find_smali_file(decompiled, "com/pairip/SignatureCheck.smali")
    text = path.read_text(encoding="utf-8")

    if "# --- gcammod: neutered signature check ---" in text:
        print("SignatureCheck already patched, skipping")
        return

    # We discard the whole body regardless of convention, so we only need
    # to match either directive, not interpret its count.
    pattern = re.compile(
        r"\.method public static verifyIntegrity\(Landroid/content/Context;\)V\n"
        r"\s*\.(?:registers|locals) \d+\n"
        r"(?:.*\n)*?"
        r"\.end method",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        print("ERROR: could not find verifyIntegrity method to patch")
        idx = text.find("verifyIntegrity")
        if idx != -1:
            print("--- actual content around verifyIntegrity (for debugging) ---")
            print(text[max(0, idx - 100) : idx + 600])
        sys.exit(1)

    replacement = (
        ".method public static verifyIntegrity(Landroid/content/Context;)V\n"
        "    .locals 0\n"
        "    # --- gcammod: neutered signature check ---\n"
        "    return-void\n"
        ".end method"
    )
    patched = text[: match.start()] + replacement + text[match.end() :]
    path.write_text(patched, encoding="utf-8")
    print(f"Patched signature check: {path}")


def patch_bottombar(decompiled: Path) -> None:
    """
    Inserts a new button right before the method's final return-void.
    Uses only v0/v1/v2 -- safe because nothing reads any register after
    this point (the method just returns), so clobbering them is fine
    regardless of what they held before, and no register-count bump is
    needed at all.
    """
    path = find_smali_file(
        decompiled, "com/google/android/apps/camera/bottombar/BottomBar.smali"
    )
    text = path.read_text(encoding="utf-8")

    if "# --- gcammod: injected overlay button ---" in text:
        print("BottomBar already patched, skipping")
        return

    method_pattern = re.compile(
        r"(\.method protected final onFinishInflate\(\)V\n"
        r"\s*\.(?:registers|locals) \d+\n)"
        r"((?:.*\n)*?)"
        r"(\s*return-void\n)"
        r"\.end method",
        re.MULTILINE,
    )
    match = method_pattern.search(text)
    if not match:
        print("ERROR: could not find onFinishInflate() method to patch")
        idx = text.find("onFinishInflate")
        if idx != -1:
            print("--- actual content around onFinishInflate (for debugging) ---")
            print(text[max(0, idx - 100) : idx + 600])
        sys.exit(1)

    injected = """
    # --- gcammod: injected overlay button ---
    invoke-virtual {p0}, Landroid/view/View;->getContext()Landroid/content/Context;

    move-result-object v0

    new-instance v1, Landroid/widget/Button;

    invoke-direct {v1, v0}, Landroid/widget/Button;-><init>(Landroid/content/Context;)V

    const-string v2, "+Media"

    invoke-virtual {v1, v2}, Landroid/widget/Button;->setText(Ljava/lang/CharSequence;)V

    new-instance v2, Lcom/example/gcammod/OverlayButtonClickListener;

    invoke-direct {v2, v0}, Lcom/example/gcammod/OverlayButtonClickListener;-><init>(Landroid/content/Context;)V

    invoke-virtual {v1, v2}, Landroid/widget/Button;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    invoke-virtual {p0, v1}, Lcom/google/android/apps/camera/bottombar/BottomBar;->addView(Landroid/view/View;)V
    # --- end gcammod ---

"""

    replacement = match.group(1) + match.group(2) + injected + match.group(3) + ".end method"
    patched = text[: match.start()] + replacement + text[match.end() :]
    path.write_text(patched, encoding="utf-8")
    print(f"Patched BottomBar.onFinishInflate(): {path}")


def patch_camera_activity_logging(decompiled: Path) -> None:
    """
    Injects CrashLogger.install()/log() calls as the very FIRST instructions
    in CameraActivity.onCreate() -- the real entry point behind the
    CameraLauncher activity-alias -- so we capture what's happening even if
    something fails before BottomBar (or anything else) ever runs.

    Uses only v0 -- safe because the dex verifier guarantees the original
    code never reads a local register before writing it first, so any
    local register is safe to clobber before original code runs. No
    register-count bump needed.
    """
    path = find_smali_file(
        decompiled,
        "com/google/android/apps/camera/legacy/app/activity/main/CameraActivity.smali",
    )
    text = path.read_text(encoding="utf-8")

    if "# --- gcammod: crash logger installed ---" in text:
        print("CameraActivity already patched for logging, skipping")
        return

    method_pattern = re.compile(
        r"\.method protected onCreate\(Landroid/os/Bundle;\)V\n"
        r"\s*\.(?:registers|locals) \d+\n",
        re.MULTILINE,
    )
    match = method_pattern.search(text)
    if not match:
        print("ERROR: could not find CameraActivity.onCreate() to patch")
        idx = text.find("onCreate")
        if idx != -1:
            print("--- actual content around onCreate (for debugging) ---")
            print(text[max(0, idx - 100) : idx + 600])
        sys.exit(1)

    injected = """    # --- gcammod: crash logger installed ---
    invoke-static {p0}, Lcom/example/gcammod/CrashLogger;->install(Landroid/content/Context;)V

    const-string v0, "CameraActivity.onCreate reached"

    invoke-static {p0, v0}, Lcom/example/gcammod/CrashLogger;->log(Landroid/content/Context;Ljava/lang/String;)V
    # --- end gcammod ---

"""

    insertion_point = match.end()
    patched = text[:insertion_point] + injected + text[insertion_point:]
    path.write_text(patched, encoding="utf-8")
    print(f"Patched CameraActivity.onCreate() for logging: {path}")


def copy_generated_smali(decompiled: Path, generated_smali_dir: Path) -> None:
    # IMPORTANT: do NOT merge into smali/ (the primary classes.dex) --
    # GoogleCamera's primary dex is already right at the 64k method/field/
    # type reference limit (that's why it's already split into
    # smali_classes2/smali_classes3). Adding anything there pushes it over
    # the edge and corrupts rebuild. Put our small additions in a fresh
    # shard instead; modern Android loads multiple dex files natively.
    existing_shards = [p.name for p in decompiled.glob("smali_classes*") if p.is_dir()]
    next_n = 1 + max(
        [int(name.replace("smali_classes", "")) for name in existing_shards] + [1]
    )
    shard_name = f"smali_classes{next_n}"
    dest_root = decompiled / shard_name
    dest_root.mkdir(parents=True, exist_ok=True)

    count = 0
    for smali_file in generated_smali_dir.rglob("*.smali"):
        rel = smali_file.relative_to(generated_smali_dir)
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(smali_file.read_text(encoding="utf-8"), encoding="utf-8")
        count += 1
    print(f"Copied {count} generated smali file(s) into new shard {shard_name}/")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: apply_patches.py <decompiled_dir> [generated_smali_dir]")
        sys.exit(1)

    decompiled = Path(sys.argv[1])
    patch_manifest(decompiled)
    patch_signature_check(decompiled)
    patch_bottombar(decompiled)
    patch_camera_activity_logging(decompiled)

    if len(sys.argv) >= 3:
        copy_generated_smali(decompiled, Path(sys.argv[2]))


if __name__ == "__main__":
    main()
