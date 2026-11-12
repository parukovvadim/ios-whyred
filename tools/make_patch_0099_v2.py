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
        # Copy orig tree to tmp
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

        old_hb = '''extern void delay(int);
extern void sweet_log_wakeup(void);
_Atomic uint64_t sweet_vtimer_ticks = 0;

static void
sweet_hb_thread(__unused void *arg, __unused wait_result_t wr)
{
	uint32_t s = 0;
	while (1) {
		for (int i = 0; i < 1000; i++) {
			delay(1000);
		}
		s++;
		printf("SWEET HB %us (vt=%llu)\\n", s, (unsigned long long)os_atomic_load(&sweet_vtimer_ticks, relaxed));
		sweet_log_wakeup();
		if ((s % 5) == 0) {
			wakeup(&sweet_sample_chan);
		}
	}
}'''

        new_hb = '''static volatile uint32_t *sweet_fb_ptr = NULL;
static void
sweet_fb_indicator(uint32_t s)
{
	if (!sweet_fb_ptr) {
		extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
		sweet_fb_ptr = (volatile uint32_t *)ml_io_map(0x9d400000u, 0x40000u);
	}
	if (sweet_fb_ptr) {
		uint32_t color = (s & 1) ? 0x00FF00u : 0x0000FFu;
		for (int y = 0; y < 20; y++) {
			for (int x = 0; x < 20; x++) {
				sweet_fb_ptr[y * 1080 + x] = color;
			}
		}
	}
}

static volatile uint32_t *sweet_wdt_ptr = NULL;
static void
sweet_pet_hw_watchdog(void)
{
	if (!sweet_wdt_ptr) {
		extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
		sweet_wdt_ptr = (volatile uint32_t *)ml_io_map(0x17817000u, 0x1000u);
		if (sweet_wdt_ptr) {
			sweet_wdt_ptr[0x08 / 4] = 0;
			printf("SWEET WDT: disabled APSS HW watchdog at 0x17817000\\n");
		}
	}
	if (sweet_wdt_ptr) {
		sweet_wdt_ptr[0x08 / 4] = 0;
		sweet_wdt_ptr[0x04 / 4] = 1;
	}
}

extern void delay(int);
extern void sweet_log_wakeup(void);
extern boolean_t sweet_ufs_lock_is_free(void);
_Atomic uint64_t sweet_vtimer_ticks = 0;

static void
sweet_hb_thread(__unused void *arg, __unused wait_result_t wr)
{
	uint32_t s = 0;
	uint64_t last_pct = 0, last_vt = 0;
	sweet_pet_hw_watchdog();
	__asm__ volatile("mrs %0, cntpct_el0" : "=r"(last_pct));
	last_vt = os_atomic_load(&sweet_vtimer_ticks, relaxed);

	while (1) {
		uint64_t target_pct = last_pct + 19200000ull;
		while (1) {
			uint64_t now_pct = 0;
			__asm__ volatile("mrs %0, cntpct_el0" : "=r"(now_pct));
			if (now_pct >= target_pct) {
				break;
			}
			delay(20000);
		}
		s++;
		sweet_fb_indicator(s);
		sweet_pet_hw_watchdog();

		uint64_t pct = 0;
		__asm__ volatile("mrs %0, cntpct_el0" : "=r"(pct));
		uint64_t vt = os_atomic_load(&sweet_vtimer_ticks, relaxed);
		uint64_t mpidr = 0;
		__asm__ volatile("mrs %0, mpidr_el1" : "=r"(mpidr));
		uint32_t cpuid = (uint32_t)(mpidr & 0xFF);
		uint64_t d_pct = pct - last_pct;
		uint64_t d_vt = vt - last_vt;
		last_pct = pct;
		last_vt = vt;

		printf("SWEET HB %us (cpu=%u, pct=%llu +%llu, vt=%llu +%llu, ufs=%s)\\n",
		    s, cpuid,
		    (unsigned long long)pct, (unsigned long long)d_pct,
		    (unsigned long long)vt, (unsigned long long)d_vt,
		    sweet_ufs_lock_is_free() ? "free" : "LOCKED");
		sweet_log_wakeup();
		if ((s % 3) == 0) {
			wakeup(&sweet_sample_chan);
		}
	}
}'''
        assert old_hb in c, "old_hb not found in sweet_sample.c!"
        c = c.replace(old_hb, new_hb)
        with open(sample_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(c)
        print("[+] sweet_sample.c modified")

        # 2. Modify sweet_ufs.c
        ufs_path = os.path.join(tree, 'bsd', 'dev', 'sweet_ufs.c')
        with open(ufs_path, 'r', encoding='utf-8') as f:
            c = f.read()

        # 2a. Add sd_poll_spin before sd_reset_lines
        old_sd_reset = '''static void
sd_reset_lines(void)
{
	uint64_t deadline;
	nanoseconds_to_absolutetime(100ull * NSEC_PER_MSEC, &deadline);
	deadline += mach_absolute_time();
	ufs_wr(SD_CLK, ufs_rd(SD_CLK) | (6u << 24));    /* SRST_CMD | SRST_DAT */
	while ((ufs_rd(SD_CLK) >> 24) & 6) {
		if (mach_absolute_time() > deadline) {
			break;
		}
		delay(1);
	}
	ufs_wr(SD_ISTS, 0xffffffff);
}'''

        new_sd_reset = '''static inline void
sd_poll_spin(void)
{
	for (volatile int s = 0; s < 50; s++) {
		__asm__ volatile("isb" ::: "memory");
	}
}

static void
sd_reset_lines(void)
{
	uint64_t deadline;
	nanoseconds_to_absolutetime(100ull * NSEC_PER_MSEC, &deadline);
	deadline += mach_absolute_time();
	ufs_wr(SD_CLK, ufs_rd(SD_CLK) | (6u << 24));    /* SRST_CMD | SRST_DAT */
	while ((ufs_rd(SD_CLK) >> 24) & 6) {
		if (mach_absolute_time() > deadline) {
			break;
		}
		sd_poll_spin();
	}
	ufs_wr(SD_ISTS, 0xffffffff);
}'''
        assert old_sd_reset in c, "old_sd_reset not found in sweet_ufs.c!"
        c = c.replace(old_sd_reset, new_sd_reset)

        # 2b. In sd_xfer_one replace the remaining 4 delay(1) with sd_poll_spin()
        old_xfer_body = '''	/* 1. Wait for CMD (0x1), DAT (0x2), and DAT active (0x4) lines to be free */
	while (ufs_rd(SD_PRES) & 7) {
		if (mach_absolute_time() > deadline) {
			printf("SWEET SDHCI: inhibit stuck before CMD, state %08x\\n", ufs_rd(SD_PRES));
			sd_reset_lines();
			return EBUSY;
		}
		delay(1);
	}

	/* 2. Wait for card to release DAT0 busy (bit 20: 1 = ready, 0 = busy programming) */
	while (!(ufs_rd(SD_PRES) & (1u << 20))) {
		if (mach_absolute_time() > deadline) {
			printf("SWEET SDHCI: card busy on DAT0 before CMD, state %08x\\n", ufs_rd(SD_PRES));
			sd_reset_lines();
			return EBUSY;
		}
		delay(1);
	}

	uint32_t idx = write ? (nblocks > 1 ? 25 : 24) : (nblocks > 1 ? 18 : 17);
	uint32_t tm = 0x03 | (nblocks > 1 ? 0x24 : 0) | (write ? 0 : 0x10);
	ufs_wr(SD_ISTS, 0xffffffff);
	ufs_wr(SD_ADMA_LO, (uint32_t)(su.dma_pa + DMA_UCD));
	ufs_wr(SD_ADMA_HI, (uint32_t)((su.dma_pa + DMA_UCD) >> 32));
	ufs_wr(SD_BLK, (nblocks << 16) | UFS_BLOCK);
	ufs_wr(SD_ARG, sector);
	ufs_wr(SD_CMD, (((idx << 8) | 0x3au) << 16) | tm);   /* R1, CRC+index check, data present */

	uint32_t ists;
	for (;;) {
		ists = ufs_rd(SD_ISTS);
		if (ists & (1u << 15)) {  /* Error Interrupt */
			printf("SWEET SDHCI: CMD%u sector 0x%x x%u failed, ISTS %08x ADMAERR %08x STATE %08x\\n",
			    idx, sector, nblocks, ists, ufs_rd(SD_ADMA_ERR), ufs_rd(SD_PRES));
			sd_reset_lines();
			return EIO;
		}
		if (ists & 2u) {                        /* transfer complete */
			break;
		}
		if (mach_absolute_time() > deadline) {
			printf("SWEET SDHCI: CMD%u sector 0x%x timed out, ISTS %08x STATE %08x ADMAERR %08x\\n",
			    idx, sector, ists, ufs_rd(SD_PRES), ufs_rd(SD_ADMA_ERR));
			sd_reset_lines();
			return ETIMEDOUT;
		}
		delay(1);
	}
	ufs_wr(SD_ISTS, ists);
	if (write) {
		while (!(ufs_rd(SD_PRES) & (1u << 20))) {       /* DAT0 low: card busy programming */
			if (mach_absolute_time() > deadline) {
				printf("SWEET SDHCI: write busy timeout on sector 0x%x\\n", sector);
				sd_reset_lines();
				return ETIMEDOUT;
			}
			delay(1);
		}
	}'''

        new_xfer_body = '''	/* 1. Wait for CMD (0x1), DAT (0x2), and DAT active (0x4) lines to be free */
	while (ufs_rd(SD_PRES) & 7) {
		if (mach_absolute_time() > deadline) {
			printf("SWEET SDHCI: inhibit stuck before CMD, state %08x\\n", ufs_rd(SD_PRES));
			sd_reset_lines();
			return EBUSY;
		}
		sd_poll_spin();
	}

	/* 2. Wait for card to release DAT0 busy (bit 20: 1 = ready, 0 = busy programming) */
	while (!(ufs_rd(SD_PRES) & (1u << 20))) {
		if (mach_absolute_time() > deadline) {
			printf("SWEET SDHCI: card busy on DAT0 before CMD, state %08x\\n", ufs_rd(SD_PRES));
			sd_reset_lines();
			return EBUSY;
		}
		sd_poll_spin();
	}

	uint32_t idx = write ? (nblocks > 1 ? 25 : 24) : (nblocks > 1 ? 18 : 17);
	uint32_t tm = 0x03 | (nblocks > 1 ? 0x24 : 0) | (write ? 0 : 0x10);
	ufs_wr(SD_ISTS, 0xffffffff);
	ufs_wr(SD_ADMA_LO, (uint32_t)(su.dma_pa + DMA_UCD));
	ufs_wr(SD_ADMA_HI, (uint32_t)((su.dma_pa + DMA_UCD) >> 32));
	ufs_wr(SD_BLK, (nblocks << 16) | UFS_BLOCK);
	ufs_wr(SD_ARG, sector);
	ufs_wr(SD_CMD, (((idx << 8) | 0x3au) << 16) | tm);   /* R1, CRC+index check, data present */

	uint32_t ists;
	for (;;) {
		ists = ufs_rd(SD_ISTS);
		if (ists & (1u << 15)) {  /* Error Interrupt */
			printf("SWEET SDHCI: CMD%u sector 0x%x x%u failed, ISTS %08x ADMAERR %08x STATE %08x\\n",
			    idx, sector, nblocks, ists, ufs_rd(SD_ADMA_ERR), ufs_rd(SD_PRES));
			sd_reset_lines();
			return EIO;
		}
		if (ists & 2u) {                        /* transfer complete */
			break;
		}
		if (mach_absolute_time() > deadline) {
			printf("SWEET SDHCI: CMD%u sector 0x%x timed out, ISTS %08x STATE %08x ADMAERR %08x\\n",
			    idx, sector, ists, ufs_rd(SD_PRES), ufs_rd(SD_ADMA_ERR));
			sd_reset_lines();
			return ETIMEDOUT;
		}
		sd_poll_spin();
	}
	ufs_wr(SD_ISTS, ists);
	if (write) {
		while (!(ufs_rd(SD_PRES) & (1u << 20))) {       /* DAT0 low: card busy programming */
			if (mach_absolute_time() > deadline) {
				printf("SWEET SDHCI: write busy timeout on sector 0x%x\\n", sector);
				sd_reset_lines();
				return ETIMEDOUT;
			}
			sd_poll_spin();
		}
	}'''
        assert old_xfer_body in c, "old_xfer_body not found in sweet_ufs.c!"
        c = c.replace(old_xfer_body, new_xfer_body)

        # 2c. Modify sweet_ufs_strategy logging
        old_strat_start = '''static void
sweet_ufs_strategy(buf_t bp)
{
	static int ufs_strat_count = 0;
	int error = 0;
	caddr_t vaddr = NULL;
	uint64_t off = (uint64_t)buf_blkno(bp) * su.secsize;
	uint32_t count = buf_count(bp);
	uint64_t part_bytes = su.nblocks * UFS_BLOCK;

	bool rd = buf_flags(bp) & B_READ;

	if (ufs_strat_count < 50) {
		printf("SWEET UFS: strat #%d %s blk=%llu cnt=%u (off=0x%llx)\\n",
		    ufs_strat_count, rd ? "R" : "W", (unsigned long long)buf_blkno(bp), count, (unsigned long long)off);
	}'''

        new_strat_start = '''static void
sweet_ufs_strategy(buf_t bp)
{
	static uint32_t ufs_strat_count = 0;
	int error = 0;
	caddr_t vaddr = NULL;
	uint64_t off = (uint64_t)buf_blkno(bp) * su.secsize;
	uint32_t count = buf_count(bp);
	uint64_t part_bytes = su.nblocks * UFS_BLOCK;

	bool rd = buf_flags(bp) & B_READ;
	uint32_t s_num = os_atomic_inc_orig(&ufs_strat_count, relaxed);

	if (s_num < 100 || (s_num % 10 == 0)) {
		printf("SWEET UFS: strat #%u %s blk=%llu cnt=%u\\n",
		    s_num, rd ? "R" : "W", (unsigned long long)buf_blkno(bp), count);
	}'''
        assert old_strat_start in c, "old_strat_start not found in sweet_ufs.c!"
        c = c.replace(old_strat_start, new_strat_start)

        old_strat_done = '''done:
	if (error) {
		buf_seterror(bp, error);
	}
	if (ufs_strat_count < 50) {
		printf("SWEET UFS: strat #%d done err=%d\\n", ufs_strat_count++, error);
	}
	buf_biodone(bp);'''

        new_strat_done = '''done:
	if (error) {
		buf_seterror(bp, error);
	}
	if (error || s_num < 100 || (s_num % 10 == 0)) {
		printf("SWEET UFS: strat #%u done %s blk=%llu err=%d\\n",
		    s_num, rd ? "R" : "W", (unsigned long long)buf_blkno(bp), error);
	}
	buf_biodone(bp);'''
        assert old_strat_done in c, "old_strat_done not found in sweet_ufs.c!"
        c = c.replace(old_strat_done, new_strat_done)

        # 2d. In sweet_log_thread use lck_mtx_try_lock
        old_log_lock = '''		uint64_t pos = total - flushed >= SWEET_LOG_SIZE ? total - SWEET_LOG_SIZE : flushed;
		int error = 0;

		lck_mtx_lock(&sweet_ufs_lock);
		while (pos < total && !error) {'''

        new_log_lock = '''		uint64_t pos = total - flushed >= SWEET_LOG_SIZE ? total - SWEET_LOG_SIZE : flushed;
		int error = 0;

		if (!lck_mtx_try_lock(&sweet_ufs_lock)) {
			(void)tsleep(&sweet_log_chan, PZERO, "sweetlog_busy", hz / 10);
			continue;
		}
		while (pos < total && !error) {'''
        assert old_log_lock in c, "old_log_lock not found in sweet_ufs.c!"
        c = c.replace(old_log_lock, new_log_lock)

        # 2e. Add sweet_ufs_lock_is_free
        old_wakeup = '''void
sweet_log_wakeup(void)
{
	wakeup(&sweet_log_chan);
}'''

        new_wakeup = '''void
sweet_log_wakeup(void)
{
	wakeup(&sweet_log_chan);
}

boolean_t
sweet_ufs_lock_is_free(void)
{
	if (lck_mtx_try_lock(&sweet_ufs_lock)) {
		lck_mtx_unlock(&sweet_ufs_lock);
		return TRUE;
	}
	return FALSE;
}'''
        assert old_wakeup in c, "old_wakeup not found in sweet_ufs.c!"
        c = c.replace(old_wakeup, new_wakeup)

        with open(ufs_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(c)
        print("[+] sweet_ufs.c modified")

        # 3. Modify whyred_touch.c
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
	extern int hz;
	if (hz > 0 && ms >= 10) {
		uint32_t ticks = (ms * (uint32_t)hz) / 1000u;
		if (ticks < 1) ticks = 1;
		(void)tsleep(&wt_sleep_chan, PZERO, "wttouch", ticks);
	} else {
		delay(ms * 1000);
	}
}'''

        new_wtdelay = '''static void
wt_delay_ms(uint32_t ms)
{
	for (uint32_t i = 0; i < ms; i++) {
		delay(1000);
	}
}'''
        assert old_wtdelay in c, 'old_wtdelay not found in whyred_touch.c!'
        c = c.replace(old_wtdelay, new_wtdelay)

        with open(touch_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(c)
        print("[+] whyred_touch.c modified")

        # 4. Modify sweet_keys.c
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
	uint64_t deadline;
	clock_interval_to_deadline(20, NSEC_PER_MSEC, &deadline);
	(void)assert_wait_deadline(&keys_sleep_chan, THREAD_UNINT, deadline);
	thread_block(THREAD_CONTINUE_NULL);
}'''

        new_keys_wait = '''static void
keys_wait(void)
{
	for (int i = 0; i < 20; i++) {
		delay(1000);
	}
}'''
        assert old_keys_wait in c, 'old_keys_wait not found in sweet_keys.c!'
        c = c.replace(old_keys_wait, new_keys_wait)

        with open(keys_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(c)
        print("[+] sweet_keys.c modified")

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
