#!/usr/bin/env python3
"""
Generate xnu/patches/0098-whyred-heartbeat-busywait-and-wakeup.patch:
1. bsd/dev/sweet_sample.c:
   - Make sweet_hb_thread use an active busy-wait loop (1000 x delay(1000)) so CPU 0 never idles.
   - Print SWEET HB %us (vt=%llu) with live vtimer tick counter.
   - Wake up sweet_log_thread every 1s so console output is flushed to eMMC without delay.
   - Wake up sweet_sample_thread every 5s so samples keep being collected even if timers stall.
2. bsd/dev/sweet_ufs.c:
   - Provide sweet_log_wakeup() to wake up sweet_log_chan.
3. osfmk/arm64/sleh.c:
   - Track architected virtual timer interrupts with atomic sweet_vtimer_ticks counter.
"""
import re
import subprocess
import os

PATCH_CONTENT = """--- a/bsd/dev/sweet_sample.c
+++ b/bsd/dev/sweet_sample.c
@@ -63,33 +63,44 @@ sweet_sample_proc(proc_t p, __unused void *arg)
 	return PROC_RETURNED;
 }
 
+static int sweet_sample_chan;
+
 static void
 sweet_sample_thread(__unused void *arg, __unused wait_result_t wr)
 {
-	static int chan;
 	if (!PE_parse_boot_argn("sweetsample", sweet_sample_names, sizeof(sweet_sample_names))) {
 		strlcpy(sweet_sample_names, "SpringBoard,backboardd,launchd,lsd,containermanagerd", sizeof(sweet_sample_names));
 	}
 	if (sweet_sample_names[0] == '-') {
 		return;
 	}
-	(void)tsleep(&chan, PZERO, "sweetsmp", 3 * hz);
+	(void)tsleep(&sweet_sample_chan, PZERO, "sweetsmp", 3 * hz);
 	for (int i = 0; i < 60; i++) {
 		printf("SMP --- sample %d\\n", i);
 		proc_iterate(PROC_ALLPROCLIST | PROC_NOWAITTRANS, sweet_sample_proc, NULL, NULL, NULL);
-		(void)tsleep(&chan, PZERO, "sweetsmp", 5 * hz);
+		(void)tsleep(&sweet_sample_chan, PZERO, "sweetsmp", 5 * hz);
 	}
 }
 
+extern void delay(int);
+extern void sweet_log_wakeup(void);
+_Atomic uint64_t sweet_vtimer_ticks = 0;
+
 static void
 sweet_hb_thread(__unused void *arg, __unused wait_result_t wr)
 {
-	static int hb_chan;
 	uint32_t s = 0;
 	while (1) {
-		(void)tsleep(&hb_chan, PZERO, "sweethb", 1 * hz);
+		for (int i = 0; i < 1000; i++) {
+			delay(1000);
+		}
 		s++;
-		printf("SWEET HB %us\\n", s);
+		printf("SWEET HB %us (vt=%llu)\\n", s, (unsigned long long)os_atomic_load(&sweet_vtimer_ticks, relaxed));
+		sweet_log_wakeup();
+		if ((s % 5) == 0) {
+			wakeup(&sweet_sample_chan);
+		}
 	}
 }
--- a/bsd/dev/sweet_ufs.c
+++ b/bsd/dev/sweet_ufs.c
@@ -904,6 +904,12 @@ sweet_log_panic_flush(void)
 		(void)ufs_sync_cache();
 	}
 }
 
+void
+sweet_log_wakeup(void)
+{
+	wakeup(&sweet_log_chan);
+}
+
 /* Root device for rd=ufsroot0 (IOFindBSDRoot). */
 int sweet_ufs_rootdev(dev_t *dev);
--- a/osfmk/arm64/sleh.c
+++ b/osfmk/arm64/sleh.c
@@ -1856,18 +1856,20 @@ sleh_irq(arm_saved_state_t *state)
 #endif
 
 
 #if defined(SWEET)
+	extern _Atomic uint64_t sweet_vtimer_ticks;
 	/*
 	 * sweet: TrustZone owns GIC Group 0, so the timer and IPIs that other
 	 * ARM64 targets take as FIQs arrive here as Group 1 IRQs.
 	 */
 	uint64_t iar = __builtin_arm_rsr64("ICC_IAR1_EL1");
 	uint32_t intid = (uint32_t)(iar & 0xFFFFFF);
 
 	if (intid >= 1020 && intid <= 1023) {
 		return; /* spurious */
 	}
 	if (intid == sweet_vtimer_intid) {
+		os_atomic_inc(&sweet_vtimer_ticks, relaxed);
 		sleh_interrupt_handler_prologue(state, DBG_INTR_TYPE_TIMER);
 		cdp->cpu_decrementer = -1; /* Large */
 		INTERRUPT_MASKED_DEBUG_START(rtclock_intr, DBG_INTR_TYPE_TIMER);
"""

def fix_patch_headers(patch_str):
    out = []
    lines = patch_str.strip().split('\n')
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
    return '\n'.join(out) + '\n'

def main():
    fixed = fix_patch_headers(PATCH_CONTENT)
    out_patch = r'D:\iOS_whyred\xnu\patches\0098-whyred-heartbeat-busywait-and-wakeup.patch'
    with open(out_patch, 'w', encoding='utf-8', newline='\n') as f:
        f.write(fixed)
    print(f'[+] Successfully generated {out_patch} ({len(fixed)} bytes)')

if __name__ == '__main__':
    main()
