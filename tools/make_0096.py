#!/usr/bin/env python3
"""
Generate xnu/patches/0096-whyred-disable-system-sleep.patch:
1. iokit/Kernel/IOPMrootDomain.cpp:
   Set gSleepDisabledFlag = 1 to prevent IOCPUSleepKernel PSCI sleep deadlock on SMP.
2. bsd/dev/sweet_ufs.c:
   Implement sweet_log_panic_flush() to dump ring buffer to eMMC on panic.
3. osfmk/kern/debug.c:
   Call sweet_log_panic_flush() in panic_spin_forever().
4. bsd/kern/kern_exec.c:
   Route /dev/null stdout/stderr to /dev/console when boot-arg applog=1 is present.
"""
import re

PATCH_CONTENT = """--- a/iokit/Kernel/IOPMrootDomain.cpp
+++ b/iokit/Kernel/IOPMrootDomain.cpp
@@ -555,7 +555,15 @@ static uint32_t         gDarkWakeFlags = kDarkWakeFlagPromotionEarly;
 #endif /* !defined(XNU_TARGET_OS_OSX) */
 
 static uint32_t         gNoIdleFlag = 0;
-static uint32_t         gSleepDisabledFlag = 0;
+/*
+ * whyred/hakios: the system does not sleep. There is nothing to sleep into and
+ * with the screen locked powerd asks for system sleep within seconds, which
+ * ended in IOCPUSleepKernel() -- on SMP this stops waiting for a processor to go
+ * down via PSCI CPU_OFF that never goes. Refused instead, the system stays awake
+ * with display off, and buttons or touch wake the screen.
+ * Boot-arg syssleep=1 gives the old behavior back.
+ */
+static uint32_t         gSleepDisabledFlag = 1;
 static uint32_t         gSwdPanic = 1;
 static uint32_t         gSwdSleepTimeout = 0;
 static uint32_t         gSwdWakeTimeout = 0;
@@ -1587,6 +1596,13 @@ IOPMrootDomain::start( IOService * nub )
 #endif /* DEVELOPMENT || DEBUG */
 
 	PE_parse_boot_argn("noidle", &gNoIdleFlag, sizeof(gNoIdleFlag));
+	{
+		uint32_t syssleep = 0;
+
+		if (PE_parse_boot_argn("syssleep", &syssleep, sizeof(syssleep)) && syssleep) {
+			gSleepDisabledFlag = 0;
+		}
+	}
 	PE_parse_boot_argn("swd_sleeptimeout", &gSwdSleepTimeout, sizeof(gSwdSleepTimeout));
 	PE_parse_boot_argn("swd_waketimeout", &gSwdWakeTimeout, sizeof(gSwdWakeTimeout));
 	PE_parse_boot_argn("swd_timeout", &gSwdSleepWakeTimeout, sizeof(gSwdSleepWakeTimeout));
--- a/bsd/dev/sweet_ufs.c
+++ b/bsd/dev/sweet_ufs.c
@@ -737,6 +737,43 @@ sweet_log_start(void)
 	}
 }
 
+/* Emergency panic flush: called during panic_spin_forever to ensure the log reaches eMMC. */
+void
+sweet_log_panic_flush(void)
+{
+	if (!su.ready || !su.writable || su.nblocks < 2 * SWEET_LOG_BLOCKS) {
+		return;
+	}
+	uint64_t total = os_atomic_load(&sweet_log_total, relaxed);
+	if (total == 0) {
+		return;
+	}
+	uint64_t base = su.first_block + su.nblocks - SWEET_LOG_BLOCKS;
+	void *bounce = (void *)(su.dma + DMA_BOUNCE);
+	uint64_t pos = total >= SWEET_LOG_SIZE ? total - SWEET_LOG_SIZE : 0;
+	int error = 0;
+	while (pos < total && !error) {
+		uint32_t off = (uint32_t)(pos % SWEET_LOG_SIZE);
+		uint32_t blk = off / UFS_BLOCK;
+		uint64_t need = ((uint64_t)off % UFS_BLOCK + (total - pos) + UFS_BLOCK - 1) / UFS_BLOCK;
+		uint32_t n = (uint32_t)MIN(MIN(need, (uint64_t)(SWEET_LOG_SIZE / UFS_BLOCK - blk)),
+		    (uint64_t)(BOUNCE_SIZE / UFS_BLOCK));
+		memcpy(bounce, sweet_log_ring + (uint64_t)blk * UFS_BLOCK, n * UFS_BLOCK);
+		error = ufs_write_blocks(base + 1 + blk, n);
+		pos += (uint64_t)(blk + n) * UFS_BLOCK - off;
+	}
+	if (!error) {
+		struct sweet_log_header h = {
+			.magic = { 'S', 'W', 'E', 'E', 'T', 'L', 'O', 'G' },
+			.version = 1, .size = SWEET_LOG_SIZE, .total = total, .seq = 999999,
+		};
+		bzero(bounce, UFS_BLOCK);
+		memcpy(bounce, &h, sizeof(h));
+		(void)ufs_write_blocks(base, 1);
+		(void)ufs_sync_cache();
+	}
+}
+
 /* Root device for rd=ufsroot0 (IOFindBSDRoot). */
 int sweet_ufs_rootdev(dev_t *dev);
 
--- a/osfmk/kern/debug.c
+++ b/osfmk/kern/debug.c
@@ -1150,6 +1150,10 @@ panic_trap_to_debugger(const char *panic_format_str, va_list *panic_args, unsign
 void
 panic_spin_forever(void)
 {
+#if defined(ARM64_BOARD_CONFIG_SWEET)
+	extern void sweet_log_panic_flush(void);
+	sweet_log_panic_flush();
+#endif
 	for (;;) {
 #if defined(__arm__) || defined(__arm64__)
 		/* On arm32, which doesn't have a WFE timeout, this may not return.  But that should be OK on this path. */
--- a/bsd/kern/kern_exec.c
+++ b/bsd/kern/kern_exec.c
@@ -2640,6 +2640,22 @@ done:
 	return ret;
 }
 
+static uint32_t exec_applog = 0;
+static int exec_applog_init = 0;
+
+static const char *
+exec_applog_path(int fd, const char *path)
+{
+	if (!exec_applog_init) {
+		exec_applog_init = 1;
+		(void)PE_parse_boot_argn("applog", &exec_applog, sizeof(exec_applog));
+	}
+	if (exec_applog && (fd == 1 || fd == 2) && strcmp(path, "/dev/null") == 0) {
+		return "/dev/console";
+	}
+	return path;
+}
+
 /*
  * exec_handle_file_actions
  *
@@ -2709,7 +2725,7 @@ exec_handle_file_actions(struct image_params *imgp, short psa_flags)
 			AUDIT_SUBCALL_ENTER(OPEN, p, uthread);
 
 			NDINIT(ndp, LOOKUP, OP_OPEN, FOLLOW | AUDITVNPATH1, UIO_SYSSPACE,
-			    CAST_USER_ADDR_T(psfa->psfaa_openargs.psfao_path),
+			    CAST_USER_ADDR_T(exec_applog_path(psfa->psfaa_filedes, psfa->psfaa_openargs.psfao_path)),
 			    imgp->ip_vfs_context);
 
 			error = open1(imgp->ip_vfs_context, ndp,
"""

def fix_patch_headers(patch_str):
    out = []
    lines = patch_str.strip().split('\\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('@@'):
            m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)', line)
            orig_start = int(m.group(1))
            new_start = int(m.group(2))
            heading = m.group(3)
            hunk = []
            j = i + 1
            while j < len(lines):
                if lines[j].startswith('@@') or lines[j].startswith('--- ') or lines[j].startswith('diff --git'):
                    break
                hunk.append(lines[j])
                j += 1
            orig_cnt = sum(1 for l in hunk if l.startswith('-') or l.startswith(' '))
            new_cnt = sum(1 for l in hunk if l.startswith('+') or l.startswith(' '))
            out.append(f'@@ -{orig_start},{orig_cnt} +{new_start},{new_cnt} @@{heading}')
            i += 1
        else:
            out.append(line)
            i += 1
    return '\\n'.join(out) + '\\n'

fixed = fix_patch_headers(PATCH_CONTENT)
with open("xnu/patches/0096-whyred-disable-system-sleep.patch", "wb") as f:
    f.write(fixed.encode("utf-8"))

print("[+] Successfully generated xnu/patches/0096-whyred-disable-system-sleep.patch with verified headers")
