#!/usr/bin/env python3
import tempfile
import subprocess
import os
import shutil
import glob

def main():
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run(['git', 'init'], cwd=tmp, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['git', 'config', 'core.autocrlf', 'false'], cwd=tmp, check=True)
        
        # Apply all existing patches 0000..0098 in sorted order
        patches_dir = r'D:\iOS_whyred\xnu\patches'
        patches = sorted(glob.glob(os.path.join(patches_dir, '*.patch')))
        for p in patches:
            name = os.path.basename(p)
            if name.startswith('0099'):
                continue
            res = subprocess.run(['git', 'apply', '--whitespace=nowarn', p], cwd=tmp, capture_output=True, text=True)
            if res.returncode != 0:
                # Some patches might need --reject or might be standalone, check
                print(f"[!] Warning applying {name}: {res.stderr.strip()[:100]}")
        
        # Commit everything as baseline
        subprocess.run(['git', 'add', '-A'], cwd=tmp, check=True)
        subprocess.run(['git', 'commit', '-m', 'baseline up to 0098'], cwd=tmp, check=True, stdout=subprocess.DEVNULL)
        
        # 1. Modify bsd/dev/sweet_sample.c
        sample_path = os.path.join(tmp, 'bsd', 'dev', 'sweet_sample.c')
        assert os.path.exists(sample_path), f"{sample_path} does not exist!"
        with open(sample_path, 'r', encoding='utf-8') as f:
            sample_code = f.read()
        
        orig_hb = """static void
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
}"""
        
        new_hb = """extern boolean_t sweet_ufs_lock_is_free(void);

static void
sweet_hb_thread(__unused void *arg, __unused wait_result_t wr)
{
	uint32_t s = 0;
	uint64_t last_pct = 0;
	uint64_t last_vt = 0;
	while (1) {
		for (int i = 0; i < 1000; i++) {
			delay(1000);
		}
		s++;
		uint64_t pct = __builtin_arm_rsr64("CNTPCT_EL0");
		uint64_t vt = os_atomic_load(&sweet_vtimer_ticks, relaxed);
		boolean_t ufs_free = sweet_ufs_lock_is_free();
		printf("SWEET HB %us (pct=%llu +%llu, vt=%llu +%llu, ufs=%s)\\n",
		    s, (unsigned long long)pct, (unsigned long long)(pct - last_pct),
		    (unsigned long long)vt, (unsigned long long)(vt - last_vt),
		    ufs_free ? "free" : "LOCKED");
		last_pct = pct;
		last_vt = vt;
		sweet_log_wakeup();
		if ((s % 5) == 0) {
			wakeup(&sweet_sample_chan);
		}
	}
}"""
        assert orig_hb in sample_code, "orig_hb not found in sweet_sample.c!"
        sample_code = sample_code.replace(orig_hb, new_hb, 1)
        with open(sample_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(sample_code)
        print("[+] Modified sweet_sample.c")
        
        # 2. Modify bsd/dev/sweet_ufs.c
        ufs_path = os.path.join(tmp, 'bsd', 'dev', 'sweet_ufs.c')
        assert os.path.exists(ufs_path), f"{ufs_path} does not exist!"
        with open(ufs_path, 'r', encoding='utf-8') as f:
            ufs_code = f.read()
        
        orig_wakeup = """void
sweet_log_wakeup(void)
{
	wakeup(&sweet_log_chan);
}"""
        
        new_wakeup = """void
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
}"""
        assert orig_wakeup in ufs_code, "orig_wakeup not found in sweet_ufs.c!"
        ufs_code = ufs_code.replace(orig_wakeup, new_wakeup, 1)
        with open(ufs_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(ufs_code)
        print("[+] Modified sweet_ufs.c")
        
        # 3. Modify bsd/dev/whyred_touch.c
        touch_path = os.path.join(tmp, 'bsd', 'dev', 'whyred_touch.c')
        assert os.path.exists(touch_path), f"{touch_path} does not exist!"
        with open(touch_path, 'r', encoding='utf-8') as f:
            touch_code = f.read()
            
        orig_tlmm = "#define WHYRED_TLMM_PA       0x03000000u"
        new_tlmm = "#define WHYRED_TLMM_PA       0x03100000u"
        assert orig_tlmm in touch_code, "orig_tlmm not found in whyred_touch.c!"
        touch_code = touch_code.replace(orig_tlmm, new_tlmm, 1)
        
        orig_delay = """static void
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
}"""
        new_delay = """static void
wt_delay_ms(uint32_t ms)
{
	for (uint32_t i = 0; i < ms; i++) {
		delay(1000);
	}
}"""
        assert orig_delay in touch_code, "orig_delay not found in whyred_touch.c!"
        touch_code = touch_code.replace(orig_delay, new_delay, 1)
        with open(touch_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(touch_code)
        print("[+] Modified whyred_touch.c")
        
        # 4. Modify bsd/dev/sweet_keys.c
        keys_path = os.path.join(tmp, 'bsd', 'dev', 'sweet_keys.c')
        assert os.path.exists(keys_path), f"{keys_path} does not exist!"
        with open(keys_path, 'r', encoding='utf-8') as f:
            keys_code = f.read()
            
        orig_keys_pa = """#define KEYS_CORE_PA     0x0c440000u
#define KEYS_OBS_PA      0x0e600000u
#define KEYS_CNFG_PA     0x0c40a000u"""
        new_keys_pa = """#define KEYS_CORE_PA     0x0800f000u
#define KEYS_OBS_PA      0x09400000u
#define KEYS_CNFG_PA     0x0800a000u"""
        assert orig_keys_pa in keys_code, "orig_keys_pa not found in sweet_keys.c!"
        keys_code = keys_code.replace(orig_keys_pa, new_keys_pa, 1)
        
        orig_keys_wait = """static void
keys_wait(void)
{
	uint64_t deadline;
	clock_interval_to_deadline(20, NSEC_PER_MSEC, &deadline);
	(void)assert_wait_deadline(&keys_sleep_chan, THREAD_UNINT, deadline);
	thread_block(THREAD_CONTINUE_NULL);
}"""
        new_keys_wait = """static void
keys_wait(void)
{
	for (int i = 0; i < 20; i++) {
		delay(1000);
	}
}"""
        assert orig_keys_wait in keys_code, "orig_keys_wait not found in sweet_keys.c!"
        keys_code = keys_code.replace(orig_keys_wait, new_keys_wait, 1)
        with open(keys_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(keys_code)
        print("[+] Modified sweet_keys.c")
        
        # Generate git diff
        diff = subprocess.check_output(['git', 'diff'], cwd=tmp, text=True)
        out_patch = os.path.join(patches_dir, '0099-whyred-diagnostic-heartbeat-and-whyred-keys.patch')
        with open(out_patch, 'w', encoding='utf-8', newline='\n') as f:
            f.write(diff)
        print(f"[+] Successfully wrote REAL git diff to {out_patch} ({len(diff)} bytes)")
        
        # Verify clean apply!
        subprocess.run(['git', 'checkout', '.'], cwd=tmp, check=True)
        res = subprocess.run(['git', 'apply', '--check', out_patch], cwd=tmp, capture_output=True, text=True)
        if res.returncode == 0:
            print("[+] Verified: git apply --check SUCCEEDED with zero errors/warnings!")
        else:
            print(f"[-] git apply --check failed: {res.stderr}")
            exit(1)
            
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == '__main__':
    main()
