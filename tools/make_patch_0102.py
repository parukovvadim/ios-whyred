#!/usr/bin/env python3
import os
import shutil
import tempfile
import subprocess
import zipfile
import tarfile
import stat

def remove_readonly(func, path, excinfo):
    os.chmod(path, stat.S_IWRITE)
    func(path)

def main():
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run(['git', 'init'], cwd=tmp, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['git', 'config', 'core.autocrlf', 'false'], cwd=tmp, check=True)
        subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=tmp, check=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=tmp, check=True)

        # 1. Extract kern_exec.c from buildtree_0098
        with zipfile.ZipFile('buildtree_0098/xnu-buildtree.zip') as z:
            with z.open('buildtree.tgz') as gz:
                with tarfile.open(fileobj=gz, mode='r:gz') as tar:
                    f = tar.extractfile('xnu/bsd/kern/kern_exec.c')
                    os.makedirs(os.path.join(tmp, 'bsd', 'kern'), exist_ok=True)
                    target_file = os.path.join(tmp, 'bsd', 'kern', 'kern_exec.c')
                    with open(target_file, 'wb') as out_f:
                        out_f.write(f.read())

        subprocess.run(['git', 'add', '-A'], cwd=tmp, check=True)
        subprocess.run(['git', 'commit', '-m', 'buildtree 0098 kern_exec.c baseline'], cwd=tmp, check=True, stdout=subprocess.DEVNULL)

        # 2. Apply Build 0134 change to kern_exec.c
        with open(target_file, 'r', encoding='utf-8') as f:
            c = f.read()

        target = '''#if defined(ARM64_BOARD_CONFIG_SWEET)
			/* SWEET runs every iOS binary this way: one short line per exec. */
			printf("exec %s\\n", p->p_name);
#else'''

        replacement = '''#if defined(ARM64_BOARD_CONFIG_SWEET)
			/* SWEET daemon blocking support via sweet_block=name1,name2 boot-arg */
			static char sweet_block_list[256];
			static int sweet_block_list_inited = 0;
			if (!sweet_block_list_inited) {
				sweet_block_list_inited = 1;
				if (!PE_parse_boot_argn("sweet_block", sweet_block_list, sizeof(sweet_block_list))) {
					sweet_block_list[0] = '\\0';
				}
			}
			if (sweet_block_list[0] && p->p_name[0]) {
				const char *sb = sweet_block_list;
				size_t nlen = strlen(p->p_name);
				while (*sb) {
					const char *comma = strchr(sb, ',');
					size_t len = comma ? (size_t)(comma - sb) : strlen(sb);
					if (len == nlen && strncmp(sb, p->p_name, len) == 0) {
						printf("SWEET EXEC: BLOCKED %s per sweet_block boot-arg\\n", p->p_name);
						signature_failure_reason = os_reason_create(OS_REASON_EXEC, EXEC_EXIT_REASON_WRONG_PLATFORM);
						error = EPERM;
						goto done;
					}
					if (!comma) break;
					sb = comma + 1;
				}
			}
			/* SWEET runs every iOS binary this way: one short line per exec. */
			printf("exec %s\\n", p->p_name);
#else'''

        assert target in c, "target block not found in kern_exec.c!"
        c = c.replace(target, replacement)
        with open(target_file, 'w', encoding='utf-8', newline='\n') as f:
            f.write(c)

        # 3. Generate real git diff
        diff_res = subprocess.run(['git', 'diff', 'bsd/kern/kern_exec.c'], cwd=tmp, capture_output=True, text=True, check=True)
        diff_output = diff_res.stdout
        
        dst_patch = os.path.abspath('xnu/patches/0102-whyred-daemon-block-bootarg.patch')
        with open(dst_patch, 'w', encoding='utf-8', newline='\n') as f:
            f.write(diff_output)
        print(f"[+] Wrote REAL git diff to {dst_patch} ({len(diff_output)} bytes)")

        # 4. Verify apply
        subprocess.run(['git', 'checkout', '-f'], cwd=tmp, check=True)
        p = subprocess.run(['git', 'apply', '--check', dst_patch], cwd=tmp, capture_output=True, text=True)
        assert p.returncode == 0, f"git apply failed: {p.stderr}"
        print("[+] Verified: git apply --check SUCCEEDED with zero errors!")

    finally:
        shutil.rmtree(tmp, onerror=remove_readonly)

if __name__ == '__main__':
    main()
