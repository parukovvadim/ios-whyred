#!/usr/bin/env python3
import os
import shutil
import tempfile
import subprocess

def main():
    orig_dir = os.path.abspath('buildtree_0098/orig')
    assert os.path.exists(orig_dir), "buildtree_0098/orig does not exist!"
    
    tmp = tempfile.mkdtemp()
    try:
        shutil.copytree(orig_dir, os.path.join(tmp, 'tree'))
        tree = os.path.join(tmp, 'tree')
        
        subprocess.run(['git', 'init'], cwd=tree, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['git', 'config', 'core.autocrlf', 'false'], cwd=tree, check=True)
        subprocess.run(['git', 'config', 'user.email', 'test@test.com'], cwd=tree, check=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=tree, check=True)
        subprocess.run(['git', 'add', '-A'], cwd=tree, check=True)
        subprocess.run(['git', 'commit', '-m', 'orig 0098 baseline'], cwd=tree, check=True, stdout=subprocess.DEVNULL)

        # 1. Modify sweet_sample.c
        sample_path = os.path.join(tree, 'bsd', 'dev', 'sweet_sample.c')
        with open(sample_path, 'r', encoding='utf-8') as f:
            c = f.read()

        old_sample_block = '''extern void sweet_sample_task(const char *name, int pid, task_t task);  /* osfmk/kern/exception.c */

static int
sweet_sample_proc(proc_t p, __unused void *arg)
{
\tchar name[32];
\tproc_name(proc_pid(p), name, sizeof(name));
\tif (sweet_sample_wanted(name)) {
\t\ttask_t task = proc_task(p);
\t\tif (task != TASK_NULL) {
\t\t\tsweet_sample_task(name, proc_pid(p), task);
\t\t}
\t}
\treturn PROC_RETURNED;
}

static int sweet_sample_chan;

static void
sweet_sample_thread(__unused void *arg, __unused wait_result_t wr)
{
\tif (!PE_parse_boot_argn("sweetsample", sweet_sample_names, sizeof(sweet_sample_names))) {
\t\tstrlcpy(sweet_sample_names, "SpringBoard,backboardd,launchd,lsd,containermanagerd", sizeof(sweet_sample_names));
\t}
\tif (sweet_sample_names[0] == '-') {
\t\treturn;
\t}
\t(void)tsleep(&sweet_sample_chan, PZERO, "sweetsmp", 3 * hz);
\tfor (int i = 0; i < 60; i++) {
\t\tprintf("SMP --- sample %d\\n", i);
\t\tproc_iterate(PROC_ALLPROCLIST | PROC_NOWAITTRANS, sweet_sample_proc, NULL, NULL, NULL);
\t\t(void)tsleep(&sweet_sample_chan, PZERO, "sweetsmp", 5 * hz);
\t}
}

extern void delay(int);
extern void sweet_log_wakeup(void);
_Atomic uint64_t sweet_vtimer_ticks = 0;

static void
sweet_hb_thread(__unused void *arg, __unused wait_result_t wr)
{
\tuint32_t s = 0;
\twhile (1) {
\t\tfor (int i = 0; i < 1000; i++) {
\t\t\tdelay(1000);
\t\t}
\t\ts++;
\t\tprintf("SWEET HB %us (vt=%llu)\\n", s, (unsigned long long)os_atomic_load(&sweet_vtimer_ticks, relaxed));
\t\tsweet_log_wakeup();
\t\tif ((s % 5) == 0) {
\t\t\twakeup(&sweet_sample_chan);
\t\t}
\t}
}'''

        new_sample_block = '''volatile uint32_t *sweet_fb_ptr = NULL;
_Atomic uint32_t sweet_core_irq_counts[4] = {0, 0, 0, 0};

void
sweet_core_irq_tick(unsigned int cpuid)
{
\tif (cpuid >= 4) return;
\tuint32_t t = os_atomic_inc_orig(&sweet_core_irq_counts[cpuid], relaxed) + 1;

\t/* Draw every 32 ticks (~100ms at ~300Hz timer rate) */
\tif ((t & 31) == 0) {
\t\tvolatile uint32_t *fb = sweet_fb_ptr;
\t\tif (fb) {
\t\t\t/* Blinking color: Bright Green (0x00FF00) vs Dark Green (0x002200) */
\t\t\tuint32_t color = (t & 32) ? 0x00FF00u : 0x002200u;
\t\t\tint x_start = 60 + (int)cpuid * 260;
\t\t\tfor (int y = 20; y < 55; y++) {
\t\t\t\tfor (int x = x_start; x < x_start + 160; x++) {
\t\t\t\t\tfb[y * 1080 + x] = color;
\t\t\t\t}
\t\t\t}
\t\t\t__asm__ volatile("dsb sy; isb" ::: "memory");
\t\t}
\t}
}

static volatile uint32_t *sweet_wdt_ptr = NULL;
static void
sweet_pet_hw_watchdog(void)
{
\tif (!sweet_wdt_ptr) {
\t\textern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
\t\tsweet_wdt_ptr = (volatile uint32_t *)ml_io_map(0x17817000u, 0x1000u);
\t}
\tif (sweet_wdt_ptr) {
\t\t/* Pure read-only dump of APSS WDT MMIO registers (0x00 .. 0x5C) */
\t\tuint32_t w00 = sweet_wdt_ptr[0x00 / 4];
\t\tuint32_t w04 = sweet_wdt_ptr[0x04 / 4];
\t\tuint32_t w08 = sweet_wdt_ptr[0x08 / 4];
\t\tuint32_t w0c = sweet_wdt_ptr[0x0C / 4];
\t\tuint32_t w10 = sweet_wdt_ptr[0x10 / 4];
\t\tuint32_t w14 = sweet_wdt_ptr[0x14 / 4];

\t\tuint32_t w38 = sweet_wdt_ptr[0x38 / 4];
\t\tuint32_t w40 = sweet_wdt_ptr[0x40 / 4];
\t\tuint32_t w44 = sweet_wdt_ptr[0x44 / 4];
\t\tuint32_t w4c = sweet_wdt_ptr[0x4C / 4];
\t\tuint32_t w5c = sweet_wdt_ptr[0x5C / 4];

\t\tprintf("SWEET WDT[00..14]: %x %x %x %x %x %x [38..5C]: %x %x %x %x %x\\n",
\t\t\tw00, w04, w08, w0c, w10, w14,
\t\t\tw38, w40, w44, w4c, w5c);
\t}
}

static int
sweet_sample_proc(proc_t p, __unused void *arg)
{
\tchar name[32];
\tproc_name(proc_pid(p), name, sizeof(name));
\tif (sweet_sample_wanted(name)) {
\t\tprintf("SMP %s[%d] alive\\n", name, proc_pid(p));
\t}
\treturn PROC_RETURNED;
}

extern void delay(int);
extern void sweet_log_wakeup(void);
extern void sweet_log_append(const char *c, int size);
extern boolean_t sweet_ufs_lock_is_free(void);
_Atomic uint64_t sweet_vtimer_ticks = 0;
static volatile uint32_t sweet_hb_seconds = 0;
static int sweet_sample_chan;

static void
sweet_core_thread(void *arg, __unused wait_result_t wr)
{
\tunsigned int target_cpu = (unsigned int)(uintptr_t)arg;
\tstruct processor;
\ttypedef struct processor *processor_t;
\textern processor_t cpu_to_processor(int cpu);
\textern processor_t thread_bind(processor_t processor);

\tif (target_cpu < 4) {
\t\tprocessor_t p = cpu_to_processor((int)target_cpu);
\t\tif (p) {
\t\t\tthread_bind(p);
\t\t}
\t}

\tstatic int core_sleep_chan[4];
\tuint32_t cnt = 0;
\twhile (1) {
\t\t/* Yield CPU to userland and sleep for 250ms (hz / 4) */
\t\t(void)tsleep(&core_sleep_chan[target_cpu], PZERO, "swcore", hz / 4);
\t\tcnt++;
\t\tvolatile uint32_t *fb = sweet_fb_ptr;
\t\tif (fb) {
\t\t\t/* Blinking color: Bright Yellow (0xFFFF00) vs Dark Yellow (0x333300) */
\t\t\tuint32_t color = (cnt & 1) ? 0xFFFF00u : 0x333300u;
\t\t\tint x_start = 60 + (int)target_cpu * 260;
\t\t\tfor (int y = 65; y < 100; y++) {
\t\t\t\tfor (int x = x_start; x < x_start + 160; x++) {
\t\t\t\t\tfb[y * 1080 + x] = color;
\t\t\t\t}
\t\t\t}
\t\t\t__asm__ volatile("dsb sy; isb" ::: "memory");
\t\t}
\t}
}

static void
sweet_sample_thread(__unused void *arg, __unused wait_result_t wr)
{
\tif (!PE_parse_boot_argn("sweetsample", sweet_sample_names, sizeof(sweet_sample_names))) {
\t\tstrlcpy(sweet_sample_names, "lsd,containermanager,containermanagerd,SpringBoard,backboardd", sizeof(sweet_sample_names));
\t}
\tif (sweet_sample_names[0] == '-') {
\t\treturn;
\t}
\t(void)tsleep(&sweet_sample_chan, PZERO, "sweetsmp", 3 * hz);
\tfor (int i = 0; i < 60; i++) {
\t\tprintf("SMP --- sample %d (hb=%us)\\n", i, sweet_hb_seconds);
\t\tproc_iterate(PROC_ALLPROCLIST | PROC_NOWAITTRANS, sweet_sample_proc, NULL, NULL, NULL);
\t\t(void)tsleep(&sweet_sample_chan, PZERO, "sweetsmp", 1 * hz);
\t}
}

static void
sweet_hb_thread(__unused void *arg, __unused wait_result_t wr)
{
\tuint32_t s = 0;
\tuint64_t last_pct = __builtin_arm_rsr64("CNTPCT_EL0");
\tuint64_t last_vt = 0;
\twhile (1) {
\t\tfor (int i = 0; i < 1000; i++) {
\t\t\tdelay(1000);
\t\t}
\t\ts++;
\t\tsweet_hb_seconds = s;
\t\tsweet_pet_hw_watchdog();
\t\tuint64_t cur_pct = __builtin_arm_rsr64("CNTPCT_EL0");
\t\tuint64_t cur_vt = os_atomic_load(&sweet_vtimer_ticks, relaxed);
\t\tunsigned int cpu = 0;
\t\t__asm__ volatile("mrs %0, mpidr_el1" : "=r"(cpu));
\t\tcpu &= 0xFF;
\t\tboolean_t free = sweet_ufs_lock_is_free();
\t\tuint32_t i0 = os_atomic_load(&sweet_core_irq_counts[0], relaxed);
\t\tuint32_t i1 = os_atomic_load(&sweet_core_irq_counts[1], relaxed);
\t\tuint32_t i2 = os_atomic_load(&sweet_core_irq_counts[2], relaxed);
\t\tuint32_t i3 = os_atomic_load(&sweet_core_irq_counts[3], relaxed);
\t\tprintf("SWEET HB %us (cpu=%u, irq=[%u,%u,%u,%u], pct=%llu +%llu, vt=%llu +%llu, ufs=%s)\\n",
\t\t\ts, cpu, i0, i1, i2, i3,
\t\t\t(unsigned long long)cur_pct, (unsigned long long)(cur_pct - last_pct),
\t\t\t(unsigned long long)cur_vt, (unsigned long long)(cur_vt - last_vt),
\t\t\tfree ? "free" : "LOCKED");
\t\tlast_pct = cur_pct;
\t\tlast_vt = cur_vt;
\t\tsweet_log_wakeup();
\t\tif (s >= 20) {
\t\t\twakeup(&sweet_sample_chan);
\t\t}
\t}
}'''
        assert old_sample_block in c, "old_sample_block not found in sweet_sample.c!"
        c = c.replace(old_sample_block, new_sample_block)

        old_start = '''void
sweet_sample_start(void)
{
\tthread_t thread;
\tif (kernel_thread_start(sweet_hb_thread, NULL, &thread) == KERN_SUCCESS) {
\t\tthread_deallocate(thread);
\t}
\tif (kernel_thread_start(sweet_sample_thread, NULL, &thread) == KERN_SUCCESS) {
\t\tthread_deallocate(thread);
\t}
}'''

        new_start = '''void
sweet_sample_start(void)
{
\tif (!sweet_fb_ptr) {
\t\textern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
\t\tsweet_fb_ptr = (volatile uint32_t *)ml_io_map(0x9d400000u, 0x100000u);
\t}

\tthread_t thread;
\tif (kernel_thread_start(sweet_hb_thread, NULL, &thread) == KERN_SUCCESS) {
\t\tthread_deallocate(thread);
\t}
\tfor (uintptr_t c = 0; c < 4; c++) {
\t\tif (kernel_thread_start(sweet_core_thread, (void *)c, &thread) == KERN_SUCCESS) {
\t\t\tthread_deallocate(thread);
\t\t}
\t}
\tif (kernel_thread_start(sweet_sample_thread, NULL, &thread) == KERN_SUCCESS) {
\t\tthread_deallocate(thread);
\t}
}'''
        assert old_start in c, "old_start not found in sweet_sample.c!"
        c = c.replace(old_start, new_start)

        with open(sample_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(c)
        print("[+] sweet_sample.c modified")

        # 2. Modify sleh.c
        sleh_path = os.path.join(tree, 'osfmk', 'arm64', 'sleh.c')
        with open(sleh_path, 'r', encoding='utf-8') as f:
            sc = f.read()

        old_sleh_block = '''\tif (intid == sweet_vtimer_intid) {
\t\tos_atomic_inc(&sweet_vtimer_ticks, relaxed);
\t\tsleh_interrupt_handler_prologue(state, DBG_INTR_TYPE_TIMER);'''

        new_sleh_block = '''\tif (intid == sweet_vtimer_intid) {
\t\tos_atomic_inc(&sweet_vtimer_ticks, relaxed);
\t\textern void sweet_core_irq_tick(unsigned int cpuid);
\t\tsweet_core_irq_tick((unsigned int)cdp->cpu_number);
\t\tsleh_interrupt_handler_prologue(state, DBG_INTR_TYPE_TIMER);'''
        assert old_sleh_block in sc, "old_sleh_block not found in sleh.c!"
        sc = sc.replace(old_sleh_block, new_sleh_block)

        with open(sleh_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(sc)
        print("[+] sleh.c modified")

        # 3. Modify sweet_ufs.c
        ufs_path = os.path.join(tree, 'bsd', 'dev', 'sweet_ufs.c')
        with open(ufs_path, 'r', encoding='utf-8') as f:
            c = f.read()

        old_wakeup = '''void
sweet_log_wakeup(void)
{
\twakeup(&sweet_log_chan);
}'''

        new_wakeup = '''void
sweet_log_wakeup(void)
{
\twakeup(&sweet_log_chan);
}

boolean_t
sweet_ufs_lock_is_free(void)
{
\tif (lck_mtx_try_lock(&sweet_ufs_lock)) {
\t\tlck_mtx_unlock(&sweet_ufs_lock);
\t\treturn TRUE;
\t}
\treturn FALSE;
}'''
        assert old_wakeup in c, "old_wakeup not found in sweet_ufs.c!"
        c = c.replace(old_wakeup, new_wakeup)

        with open(ufs_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(c)
        print("[+] sweet_ufs.c modified")

        # 4. Modify whyred_touch.c
        touch_path = os.path.join(tree, 'bsd', 'dev', 'whyred_touch.c')
        with open(touch_path, 'r', encoding='utf-8') as f:
            c = f.read()

        old_tlmm = '#define WHYRED_TLMM_PA       0x03000000u'
        new_tlmm = '#define WHYRED_TLMM_PA       0x03100000u'
        assert old_tlmm in c, 'old_tlmm not found in whyred_touch.c!'
        c = c.replace(old_tlmm, new_tlmm)

        old_wtdelay = '''static void
wt_delay_ms(uint32_t ms)
{
\textern int hz;
\tif (hz > 0 && ms >= 10) {
\t\tuint32_t ticks = (ms * (uint32_t)hz) / 1000u;
\t\tif (ticks < 1) ticks = 1;
\t\t(void)tsleep(&wt_sleep_chan, PZERO, "wttouch", ticks);
\t} else {
\t\tdelay(ms * 1000);
\t}
}'''

        new_wtdelay = '''static void
wt_delay_ms(uint32_t ms)
{
\tfor (uint32_t i = 0; i < ms; i++) {
\t\tdelay(1000);
\t}
}'''
        assert old_wtdelay in c, 'old_wtdelay not found in whyred_touch.c!'
        c = c.replace(old_wtdelay, new_wtdelay)

        with open(touch_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(c)
        print("[+] whyred_touch.c modified")

        # 5. Modify sweet_keys.c
        keys_path = os.path.join(tree, 'bsd', 'dev', 'sweet_keys.c')
        with open(keys_path, 'r', encoding='utf-8') as f:
            c = f.read()

        old_keys_pa = '''#define KEYS_CORE_PA     0x0c440000u
#define KEYS_OBS_PA      0x0e600000u
#define KEYS_CNFG_PA     0x0c40a000u'''

        new_keys_pa = '''#define KEYS_CORE_PA     0x0800f000u
#define KEYS_OBS_PA      0x09400000u
#define KEYS_CNFG_PA     0x0800a000u'''
        assert old_keys_pa in c, 'old_keys_pa not found in sweet_keys.c!'
        c = c.replace(old_keys_pa, new_keys_pa)

        old_keys_wait = '''static void
keys_wait(void)
{
\tuint64_t deadline;
\tclock_interval_to_deadline(20, NSEC_PER_MSEC, &deadline);
\t(void)assert_wait_deadline(&keys_sleep_chan, THREAD_UNINT, deadline);
\tthread_block(THREAD_CONTINUE_NULL);
}'''

        new_keys_wait = '''static void
keys_wait(void)
{
\tfor (int i = 0; i < 20; i++) {
\t\tdelay(1000);
\t}
}'''
        assert old_keys_wait in c, 'old_keys_wait not found in sweet_keys.c!'
        c = c.replace(old_keys_wait, new_keys_wait)

        with open(keys_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(c)
        print("[+] sweet_keys.c modified")

        # 6. Modify sweet_early.c
        early_path = os.path.join(tree, 'osfmk', 'arm64', 'sweet_early.c')
        with open(early_path, 'r', encoding='utf-8') as f:
            ec = f.read()

        old_early_panic = '''void
sweet_early_panic(const char *fmt, va_list *args)
{
\tif (early_disabled || early_panicking) {
\t\treturn;
\t}'''

        new_early_panic = '''void
sweet_early_panic(const char *fmt, va_list *args)
{
\textern volatile uint32_t *sweet_fb_ptr;
\tvolatile uint32_t *fb = sweet_fb_ptr;
\tif (!fb) {
\t\tfb = early_fb;
\t}
\tif (!fb) {
\t\tfb = (volatile uint32_t *)(uintptr_t)0x9c000000;
\t}
\tif (fb) {
\t\tfor (unsigned int y = 10; y < 110; y++) {
\t\t\tfor (unsigned int x = 20; x < 1060; x++) {
\t\t\t\tfb[y * 1080 + x] = 0x00FF0000u; /* RED */
\t\t\t}
\t\t}
\t\t__asm__ volatile("dsb sy; isb" ::: "memory");
\t}
\tif (early_disabled || early_panicking) {
\t\treturn;
\t}'''
        assert old_early_panic in ec, 'old_early_panic not found in sweet_early.c!'
        ec = ec.replace(old_early_panic, new_early_panic)
        with open(early_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(ec)
        print("[+] sweet_early.c modified")

        # Generate git diff
        diff = subprocess.check_output(['git', 'diff'], cwd=tree, text=True)
        out_patch = os.path.abspath('xnu/patches/0099-whyred-diagnostic-heartbeat-and-whyred-keys.patch')
        with open(out_patch, 'w', encoding='utf-8', newline='\n') as f:
            f.write(diff)
        print(f"[+] Successfully wrote REAL git diff to {out_patch} ({len(diff)} bytes)")

        # Verify clean apply!
        subprocess.run(['git', 'checkout', '.'], cwd=tree, check=True)
        res = subprocess.run(['git', 'apply', '--check', out_patch], cwd=tree, capture_output=True, text=True)
        if res.returncode == 0:
            print("[+] Verified: git apply --check SUCCEEDED with zero errors/warnings!")
        else:
            print(f"[-] git apply --check failed: {res.stderr}")
            exit(1)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == '__main__':
    main()
