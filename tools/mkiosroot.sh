#!/bin/bash
# Build the SWEET iOS root: one case-sensitive HFS+ image holding an iOS OS
# root filesystem plus its cryptexes, for the userdata partition (rd=ufsroot0).
#
#   mkiosroot.sh OS.dmg SYSTEMOS.dmg APPOS.dmg OUT.img [SIZE]     (SIZE default 16G)
#
# The IPSW images are raw APFS with LZBITMAP-compressed files: they are read
# through apfs-fuse (decompressing), so the HFS+ copy is uncompressed. On a
# device /private/preboot is its own volume holding the cryptexes, which
# /System/Cryptexes/{OS,App} link to; here they live inside the one volume.
# Owners, modes, symlinks and hard links are preserved (rsync -aH as root).
#
# The volume is journaled (XNU replays the journal after a panic; Linux only
# mounts it read-write with -o force and leaves the journal empty). SWEET
# additions: /System/Library/Caches/com.apple.dyld hard-links the SystemOS
# cryptex shared cache (ignition_level=1 looks there), and
# /private/var/keybags/systembag.kb is the plain-plist system keybag that
# keybagd reads with /defaults/no-effaceable-storage (tools/mkadt.py).
set -euo pipefail

[[ $# -ge 4 ]] || { sed -n '2,12p' "$0"; exit 2; }
os=$(realpath "$1") sysos=$(realpath "$2") appos=$(realpath "$3") out=$(realpath -m "$4") size=${5:-16G}
[[ ! -e $out ]] || { echo "refusing to overwrite $out" >&2; exit 1; }

work=$(mktemp -d)
mounts=()
cleanup() {
	local busy=0
	for m in "${mounts[@]}"; do
		if mountpoint -q "$m"; then
			sudo umount "$m" 2>/dev/null || sudo umount -l "$m" 2>/dev/null || true
		fi
		mountpoint -q "$m" && busy=1
	done
	# Never recurse into a directory that is still mounted (the root is writable).
	if [[ $busy == 0 ]]; then
		rm -f "$work"/*.dmg
		rmdir "$work"/* "$work" 2>/dev/null || true
	else
		echo "still mounted under $work: left in place" >&2
	fi
}
trap cleanup EXIT

# apfs-fuse splits its options on ',' (e.g. in iPhone10,3 paths): use links.
# Keep the .dmg name: apfs-fuse only parses UDIF images (the OS one is UDIF,
# the cryptexes are raw APFS) when the file name ends in .dmg.
apfs_mount() {
	ln -s "$1" "$work/$2.dmg"
	mkdir -p "$work/$2"
	local apfs_bin
	apfs_bin="$(command -v apfs-fuse 2>/dev/null || echo '/usr/local/bin/apfs-fuse')"
	[ -x "$apfs_bin" ] || apfs_bin="/usr/bin/apfs-fuse"
	echo "[*] Mounting $1 ($2) to $work/$2 with $apfs_bin..."
	sudo "$apfs_bin" "$work/$2.dmg" "$work/$2"
	sleep 1
	mounts+=("$work/$2")
	if ! mountpoint -q "$work/$2"; then
		echo "[-] Warning: $work/$2 is not registered as mountpoint yet"
	fi
	ls -la "$work/$2" || true
}
apfs_mount "$os" os
apfs_mount "$sysos" sysos
apfs_mount "$appos" appos

truncate -s "$size" "$out"
mkfs.hfsplus -s -J -v iOSRoot "$out"
mkdir "$work/root"
sudo mount -t hfsplus -o loop,force "$out" "$work/root"
mounts=("$work/root" "${mounts[@]}")

copy() {
	local src="$1"
	local mount_dir="$(dirname "$src")"
	if [ ! -d "$src" ]; then
		# Check if mount_dir directly contains the filesystem (e.g. System, Library, bin)
		if sudo test -d "$mount_dir/System" || sudo test -d "$mount_dir/bin" || sudo test -d "$mount_dir/Applications"; then
			src="$mount_dir"
		else
			local first_dir
			first_dir=$(sudo find "$mount_dir" -mindepth 1 -maxdepth 1 -type d | head -n 1)
			if [ -n "$first_dir" ] && sudo test -d "$first_dir"; then
				src="$first_dir"
			fi
		fi
	fi
	echo "[*] Copying $src -> ${2#"$work/root"}"
	sudo mkdir -p "$2"
	sudo rsync -aH --numeric-ids "$src/" "$2/"
}
copy "$work/os/root" "$work/root"
copy "$work/sysos/root" "$work/root/private/preboot/Cryptexes/OS"
copy "$work/appos/root" "$work/root/private/preboot/Cryptexes/App"

# Shared cache where dyld looks at ignition level 1: hard links, no extra space.
dsc=private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld
sudo mkdir -p "$work/root/System/Library/Caches/com.apple.dyld"
if [ -d "$work/root/$dsc" ]; then
	for f in "$work/root/$dsc"/*; do
		[ -e "$f" ] || continue
		sudo ln -f "$f" "$work/root/System/Library/Caches/com.apple.dyld/${f##*/}"
	done
fi

# dyld does not search the cryptexes at ignition level 1: hard-link every
# cryptex file that has no counterpart in the OS root (libobjc-trampolines,
# libffi-trampolines, libstdc++, ...) to its root path.
for c in OS App; do
	if [ -d "$work/root/private/preboot/Cryptexes/$c" ]; then
		(cd "$work/root/private/preboot/Cryptexes/$c" && sudo find . ! -type d ! -path './System/Library/Caches/com.apple.dyld/*') |
		while IFS= read -r f; do
			f=${f#./}
			if ! sudo test -e "$work/root/$f" && ! sudo test -L "$work/root/$f"; then
				sudo mkdir -p "$work/root/$(dirname "$f")"
				src="$work/root/private/preboot/Cryptexes/$c/$f"
				# Linux hfsplus cannot hard-link symlinks: copy those.
				if sudo test -L "$src"; then sudo cp -P "$src" "$work/root/$f"; else sudo ln -f "$src" "$work/root/$f"; fi
				echo "linked $c:/$f"
			fi
		done
	fi
done

# logd's log stores, normally made at restore: it checks owner _logd (272)
# and mode, plus a .migrated marker, else asks a helper and crashes
# ("BUG IN LIBTRACE: Failed to migrate directory").
db="$work/root/private/var/db"
sudo install -d -o 272 -g 272 -m 0751 "$db/diagnostics"
sudo install -d -o 272 -g 272 -m 0755 "$db/uuidtext" "$db/diagnostics/timesync"
for d in diagnostics uuidtext diagnostics/timesync; do
	sudo install -o 272 -g 272 -m 0644 /dev/null "$db/$d/.migrated"
done

# System keybag for the built-in AppleKeyStore (no passcode).
sudo install -d -m 0700 -o 0 -g 0 "$work/root/private/var/keybags"
printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
	'<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
	'<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>' |
	sudo install -m 0600 -o 0 -g 0 /dev/stdin "$work/root/private/var/keybags/systembag.kb"

df -h "$work/root"
sudo umount "$work/root"
# Linux hfsplus decomposes some non-ASCII names (localized Shortcuts examples)
# differently from Apple's tables; let fsck_hfs rewrite them, then verify.
sudo fsck.hfsplus -f -y "$out" | grep -v 'Illegal name' || true
sudo fsck.hfsplus -f -n "$out"
