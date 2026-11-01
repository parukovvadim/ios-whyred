#!/usr/bin/env python3
import difflib
import subprocess
import os

with open("tools/IOKitBSDInit.cpp", "r", encoding="utf-8") as f:
    orig_iokit = f.read()

# Apply 0028 hunk to IOKitBSDInit.cpp
needle_0028 = """\t\t}\n\t}\n\n//\n//\tNow check if we are trying to root on a memory device\n"""
patch_0028 = """\t\t}\n\t}\n\n#if defined(ARM64_BOARD_CONFIG_SWEET)\n//\n//\tSWEET: root on a GPT partition of the internal UFS (bsd/dev/sweet_ufs.c)\n//\n\tif (strcmp(rdBootVar, "ufsroot0") == 0) {\n\t\textern int sweet_ufs_rootdev(dev_t *dev);\n\t\tOSSafeReleaseNULL(matching);\n\t\tint ufs_error = sweet_ufs_rootdev(root);\n\t\tif (ufs_error) {\n\t\t\tpanic("IOFindBSDRoot: SWEET UFS root %s unavailable: %d", rdBootVar, ufs_error);\n\t\t}\n\t\tstrlcpy(rootName, rdBootVar, rootNameSize);\n\t\tIOLog("BSD root: %s, major %d, minor %d\\n", rootName, major(*root), minor(*root));\n\t\t*oflags = 0;\n\t\tgoto iofrootx;\n\t}\n#endif\n\n//\n//\tNow check if we are trying to root on a memory device\n"""

base_iokit = orig_iokit.replace(needle_0028, patch_0028)
assert base_iokit != orig_iokit, "0028 needle not found"

new_iokit = base_iokit.replace(
"""\t\tstrlcpy(rootName, rdBootVar, rootNameSize);\n\t\tIOLog("BSD root: %s, major %d, minor %d\\n", rootName, major(*root), minor(*root));\n\t\t*oflags = 0;\n\t\tgoto iofrootx;""",
"""\t\tstrlcpy(rootName, rdBootVar, rootNameSize);\n\t\tprintf("SWEET BSD: IOFindBSDRoot ufsroot0 major %d minor %d\\n", major(*root), minor(*root));\n\t\t*oflags = 0;\n\t\tIOService::setRootMedia(NULL);\n\t\treturn kIOReturnSuccess;"""
)
assert new_iokit != base_iokit, "new_iokit replacement not applied"

diff_iokit = "".join(difflib.unified_diff(
    base_iokit.splitlines(True), new_iokit.splitlines(True),
    fromfile="a/iokit/bsddev/IOKitBSDInit.cpp", tofile="b/iokit/bsddev/IOKitBSDInit.cpp"
))

# Now bsd_init.c
with open("tools/bsd_init.c", "r", encoding="utf-8") as f:
    orig_bsd = f.read()

# Apply 0089 hunk to bsd_init.c
needle_0089 = """\twhile (TRUE) {\n\t\tint err;\n\n\t\tbsd_init_kprintf("calling setconf\\n");\n\t\tsetconf();\n#if CONFIG_NETBOOT\n\t\tnetboot = (mountroot == netboot_mountroot);\n#endif\n\n\t\tbsd_init_kprintf("vfs_mountroot\\n");"""
patch_0089 = """\twhile (TRUE) {\n\t\tint err;\n\n\t\tprintf("SWEET BSD: bsd_init calling setconf\\n");\n\t\tbsd_init_kprintf("calling setconf\\n");\n\t\tsetconf();\n#if CONFIG_NETBOOT\n\t\tnetboot = (mountroot == netboot_mountroot);\n#endif\n\n\t\tprintf("SWEET BSD: bsd_init calling vfs_mountroot\\n");\n\t\tbsd_init_kprintf("vfs_mountroot\\n");"""

base_bsd = orig_bsd.replace(needle_0089, patch_0089)
assert base_bsd != orig_bsd, "0089 needle not found in bsd_init.c"

new_bsd = base_bsd.replace(
"""static void\nsetconf(void)\n{\n\tu_int32_t       flags;\n\tkern_return_t   err;\n\n\terr = IOFindBSDRoot(rootdevice, sizeof(rootdevice), &rootdev, &flags);""",
"""static void\nsetconf(void)\n{\n\tu_int32_t       flags;\n\tkern_return_t   err;\n\n\tprintf("SWEET BSD: setconf calling IOFindBSDRoot\\n");\n\terr = IOFindBSDRoot(rootdevice, sizeof(rootdevice), &rootdev, &flags);\n\tprintf("SWEET BSD: setconf IOFindBSDRoot returned %d\\n", err);"""
)
assert new_bsd != base_bsd, "new_bsd replacement not applied"

diff_bsd = "".join(difflib.unified_diff(
    base_bsd.splitlines(True), new_bsd.splitlines(True),
    fromfile="a/bsd/kern/bsd_init.c", tofile="b/bsd/kern/bsd_init.c"
))

full_patch = diff_iokit + diff_bsd

out_path = "xnu/patches/0090-whyred-fix-iofindbsdroot-direct-return.patch"
with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    f.write(full_patch)

print(f"Generated {out_path} ({len(full_patch)} bytes)")
print(full_patch)

# Test git apply --check on dummy files
os.makedirs("tools/test_git/iokit/bsddev", exist_ok=True)
os.makedirs("tools/test_git/bsd/kern", exist_ok=True)
with open("tools/test_git/iokit/bsddev/IOKitBSDInit.cpp", "w", encoding="utf-8", newline="\n") as f:
    f.write(base_iokit)
with open("tools/test_git/bsd/kern/bsd_init.c", "w", encoding="utf-8", newline="\n") as f:
    f.write(base_bsd)

res = subprocess.run(["git", "-C", "tools/test_git", "apply", "--check", os.path.abspath(out_path)], capture_output=True, text=True)
print("git apply --check result code:", res.returncode)
if res.returncode != 0:
    print("STDOUT:", res.stdout)
    print("STDERR:", res.stderr)
else:
    print("[SUCCESS] Patch 0090 applies cleanly without fuzz or errors!")
