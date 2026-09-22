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

    # Add our new activity right before </application>
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

    # Replace the ENTIRE method body (whatever it contains -- annotations
    # may or may not be present depending on apktool's decode settings)
    # with a single unconditional return. We don't need to preserve any of
    # the original logic; we're intentionally disabling this check.
    pattern = re.compile(
        r"(\.method public static verifyIntegrity\(Landroid/content/Context;\)V\n"
        r"\s*\.registers )(\d+)\n"
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
        "    .registers 1\n"
        "    # --- gcammod: neutered signature check ---\n"
        "    return-void\n"
        ".end method"
    )
    patched = text[: match.start()] + replacement + text[match.end() :]
    path.write_text(patched, encoding="utf-8")
    print(f"Patched signature check: {path}")


def patch_bottombar(decompiled: Path) -> None:
    path = find_smali_file(
        decompiled, "com/google/android/apps/camera/bottombar/BottomBar.smali"
    )
    text = path.read_text(encoding="utf-8")

    if "# --- gcammod: injected overlay button ---" in text:
        print("BottomBar already patched, skipping")
        return

    method_pattern = re.compile(
        r"\.method protected final onFinishInflate\(\)V\n"
        r"(\s*\.registers )(\d+)\n"
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

    old_register_count = int(match.group(2))
    new_register_count = old_register_count + 4  # room for 4 new scratch locals
    base = new_register_count - 3  # three fresh scratch registers we'll use

    injected = f"""
    # --- gcammod: injected overlay button ---
    invoke-virtual {{p0}}, Landroid/view/View;->getContext()Landroid/content/Context;

    move-result-object v{base}

    new-instance v{base + 1}, Landroid/widget/Button;

    invoke-direct {{v{base + 1}, v{base}}}, Landroid/widget/Button;-><init>(Landroid/content/Context;)V

    const-string v{base + 2}, "+Media"

    invoke-virtual {{v{base + 1}, v{base + 2}}}, Landroid/widget/Button;->setText(Ljava/lang/CharSequence;)V

    new-instance v{base + 2}, Lcom/example/gcammod/OverlayButtonClickListener;

    invoke-direct {{v{base + 2}, v{base}}}, Lcom/example/gcammod/OverlayButtonClickListener;-><init>(Landroid/content/Context;)V

    invoke-virtual {{v{base + 1}, v{base + 2}}}, Landroid/widget/Button;->setOnClickListener(Landroid/view/View$OnClickListener;)V

    invoke-virtual {{p0, v{base + 1}}}, Lcom/google/android/apps/camera/bottombar/BottomBar;->addView(Landroid/view/View;)V
    # --- end gcammod ---

"""

    replacement = (
        ".method protected final onFinishInflate()V\n"
        f"    .registers {new_register_count}\n"
        + match.group(3)
        + injected
        + match.group(4)
        + ".end method"
    )
    patched = text[: match.start()] + replacement + text[match.end() :]
    path.write_text(patched, encoding="utf-8")
    print(f"Patched BottomBar.onFinishInflate(): {path} (registers {old_register_count} -> {new_register_count})")


def copy_generated_smali(decompiled: Path, generated_smali_dir: Path) -> None:
    dest = decompiled / "smali" / "com" / "example" / "gcammod"
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for smali_file in generated_smali_dir.rglob("*.smali"):
        rel = smali_file.relative_to(generated_smali_dir)
        target = decompiled / "smali" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(smali_file.read_text(encoding="utf-8"), encoding="utf-8")
        count += 1
    print(f"Copied {count} generated smali file(s) into {dest.parent}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: apply_patches.py <decompiled_dir> [generated_smali_dir]")
        sys.exit(1)

    decompiled = Path(sys.argv[1])
    patch_manifest(decompiled)
    patch_signature_check(decompiled)
    patch_bottombar(decompiled)

    if len(sys.argv) >= 3:
        copy_generated_smali(decompiled, Path(sys.argv[2]))


if __name__ == "__main__":
    main()
