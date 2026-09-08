import os
import subprocess
import datetime


def get_physical_size(path):
    """
    Calculates actual physical disk space allocated for a file or directory in bytes.
    Uses st_blocks on Unix/macOS to correctly account for APFS sparse files and clones.
    """
    total = 0
    try:
        if os.path.islink(path):
            return 0
        if os.path.isfile(path):
            st = os.stat(path, follow_symlinks=False)
            blocks = getattr(st, "st_blocks", 0)
            return blocks * 512 if blocks > 0 else st.st_size
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                st = entry.stat(follow_symlinks=False)
                blocks = getattr(st, "st_blocks", 0)
                total += blocks * 512 if blocks > 0 else st.st_size
            elif entry.is_dir(follow_symlinks=False):
                total += get_physical_size(entry.path)
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return total


def get_dir_size_fast_du(path):
    """
    Uses macOS BSD `du` to quickly calculate directory size in bytes.
    Falls back to `get_physical_size` if `du` fails or times out.
    """
    try:
        res = subprocess.run(
            ["du", "-sk", path],
            capture_output=True,
            text=True,
            timeout=5
        )
        if res.returncode == 0:
            lines = res.stdout.strip().split()
            if lines:
                return int(lines[0]) * 1024
    except Exception:
        pass
    return get_physical_size(path)


def scan_user_caches(min_mb=5):
    """
    Scans ~/Library/Caches to identify space consumed by application cache folders.
    Returns a list of cache entries larger than min_mb.
    """
    caches_dir = os.path.expanduser("~/Library/Caches")
    cache_entries = []
    total_bytes = 0

    if not os.path.exists(caches_dir):
        return total_bytes, cache_entries

    try:
        # Measure top-level cache entries using du
        res = subprocess.run(
            ["du", "-k", "-d", "1", caches_dir],
            capture_output=True,
            text=True,
            timeout=20
        )
        if res.stdout:
            for line in res.stdout.splitlines():
                parts = line.strip().split("\t")
                if len(parts) == 2:
                    kb = int(parts[0])
                    p = parts[1]
                    if p == caches_dir:
                        total_bytes = kb * 1024
                        continue

                    sz_mb = kb / 1024
                    if sz_mb >= min_mb:
                        name = os.path.basename(p)
                        cache_entries.append({
                            "name": name,
                            "path": p,
                            "size_mb": round(sz_mb, 2),
                            "size_bytes": kb * 1024
                        })
    except Exception:
        pass

    return total_bytes, sorted(cache_entries, key=lambda x: x["size_mb"], reverse=True)


def scan_downloads_junk(days_old_threshold=30):
    """
    Scans ~/Downloads for leftover disk images (.dmg), installers (.pkg),
    archives (.zip, .tar.gz), and old stale files.
    """
    downloads_dir = os.path.expanduser("~/Downloads")
    installers = []
    archives = []
    old_files = []
    total_bytes = 0

    installer_exts = {".dmg", ".pkg", ".iso"}
    archive_exts = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".xz"}

    if not os.path.exists(downloads_dir):
        return {
            "total_bytes": 0,
            "installers": [],
            "archives": [],
            "old_files": []
        }

    now = datetime.datetime.now()

    try:
        for item in os.listdir(downloads_dir):
            if item.startswith("."):
                continue

            p = os.path.join(downloads_dir, item)
            try:
                st = os.stat(p, follow_symlinks=False)
                blocks = getattr(st, "st_blocks", 0)
                sz_bytes = blocks * 512 if blocks > 0 else st.st_size
                sz_mb = sz_bytes / (1024 ** 2)
                total_bytes += sz_bytes

                mtime = datetime.datetime.fromtimestamp(st.st_mtime)
                days_old = (now - mtime).days

                file_info = {
                    "name": item,
                    "path": p,
                    "size_mb": round(sz_mb, 2),
                    "size_bytes": sz_bytes,
                    "days_old": days_old,
                    "modified": mtime.strftime("%Y-%m-%d")
                }

                _, ext = os.path.splitext(item)
                ext_lower = ext.lower()

                if ext_lower in installer_exts:
                    installers.append(file_info)
                elif ext_lower in archive_exts:
                    archives.append(file_info)

                if days_old >= days_old_threshold and sz_mb >= 1.0:
                    old_files.append(file_info)
            except Exception:
                pass
    except Exception:
        pass

    return {
        "total_bytes": total_bytes,
        "total_size_mb": round(total_bytes / (1024 ** 2), 2),
        "installers": sorted(installers, key=lambda x: x["size_mb"], reverse=True),
        "archives": sorted(archives, key=lambda x: x["size_mb"], reverse=True),
        "old_files": sorted(old_files, key=lambda x: x["size_mb"], reverse=True)
    }


def scan_developer_caches():
    """
    Scans common developer tooling caches: Xcode DerivedData, Homebrew,
    npm, yarn, pnpm, Python pip, uv, and Gradle.
    """
    home = os.path.expanduser("~")
    dev_targets = [
        ("Xcode DerivedData", os.path.join(home, "Library/Developer/Xcode/DerivedData")),
        ("Xcode Archives", os.path.join(home, "Library/Developer/Xcode/Archives")),
        ("Homebrew Cache", os.path.join(home, "Library/Caches/Homebrew")),
        ("npm Cache", os.path.join(home, ".npm")),
        ("pnpm Store", os.path.join(home, ".local/share/pnpm")),
        ("yarn Cache", os.path.join(home, ".yarn/berry/cache")),
        ("pip Cache", os.path.join(home, "Library/Caches/pip")),
        ("uv Cache", os.path.join(home, ".cache/uv")),
        ("Gradle Cache", os.path.join(home, ".gradle/caches")),
        ("CocoaPods Cache", os.path.join(home, "Library/Caches/CocoaPods")),
    ]

    dev_caches = []
    total_bytes = 0

    for name, path in dev_targets:
        if os.path.exists(path):
            sz = get_dir_size_fast_du(path)
            if sz > 1024 * 1024:  # > 1 MB
                sz_mb = sz / (1024 ** 2)
                total_bytes += sz
                dev_caches.append({
                    "name": name,
                    "path": path,
                    "size_mb": round(sz_mb, 2),
                    "size_bytes": sz
                })

    return total_bytes, sorted(dev_caches, key=lambda x: x["size_mb"], reverse=True)


def scan_system_logs():
    """
    Scans user application logs and crash reports in ~/Library/Logs.
    """
    home = os.path.expanduser("~")
    logs_dir = os.path.join(home, "Library/Logs")
    total_bytes = 0
    log_entries = []

    if os.path.exists(logs_dir):
        try:
            for entry in os.scandir(logs_dir):
                p = entry.path
                sz = get_physical_size(p)
                total_bytes += sz
                if sz > 1024 * 1024:  # > 1 MB
                    log_entries.append({
                        "name": entry.name,
                        "path": p,
                        "size_mb": round(sz / (1024 ** 2), 2),
                        "size_bytes": sz
                    })
        except Exception:
            pass

    return total_bytes, sorted(log_entries, key=lambda x: x["size_mb"], reverse=True)


def scan_trash():
    """
    Scans ~/.Trash to measure space occupied by deleted items awaiting empty.
    """
    trash_dir = os.path.expanduser("~/.Trash")
    total_bytes = 0
    items = []

    if os.path.exists(trash_dir):
        try:
            for entry in os.scandir(trash_dir):
                p = entry.path
                sz = get_physical_size(p)
                total_bytes += sz
                items.append({
                    "name": entry.name,
                    "path": p,
                    "size_mb": round(sz / (1024 ** 2), 2),
                    "size_bytes": sz
                })
        except Exception:
            pass

    return total_bytes, sorted(items, key=lambda x: x["size_mb"], reverse=True)


def scan_large_files(min_mb=100, scan_dirs=None):
    """
    Scans common user directories for individual large files >= min_mb.
    Excludes hidden system and library container paths to prevent duplicate counts.
    """
    home = os.path.expanduser("~")
    if scan_dirs is None:
        scan_dirs = [
            os.path.join(home, "Downloads"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Desktop"),
            os.path.join(home, "Movies"),
            os.path.join(home, "Music"),
        ]

    large_files = []
    now = datetime.datetime.now()

    for folder in scan_dirs:
        if not os.path.exists(folder):
            continue

        for root, dirs, files in os.walk(folder):
            # Exclude virtual environments, git repositories, and node_modules
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in ("node_modules", ".venv", "venv", ".git", "DerivedData")
            ]

            for f in files:
                if f.startswith("."):
                    continue

                fp = os.path.join(root, f)
                try:
                    st = os.stat(fp, follow_symlinks=False)
                    blocks = getattr(st, "st_blocks", 0)
                    sz_bytes = blocks * 512 if blocks > 0 else st.st_size
                    sz_mb = sz_bytes / (1024 ** 2)

                    if sz_mb >= min_mb:
                        mtime = datetime.datetime.fromtimestamp(st.st_mtime)
                        days_old = (now - mtime).days
                        rel_path = os.path.relpath(fp, home)

                        large_files.append({
                            "name": f,
                            "path": fp,
                            "location": f"~/{rel_path}",
                            "size_mb": round(sz_mb, 2),
                            "size_bytes": sz_bytes,
                            "days_old": days_old,
                            "modified": mtime.strftime("%Y-%m-%d")
                        })
                except Exception:
                    pass

    return sorted(large_files, key=lambda x: x["size_mb"], reverse=True)


def get_file_cleanup_snapshot():
    """
    Collects a full storage hygiene snapshot across all categories:
    Caches, Downloads, Developer Tools, Logs, Trash, and Large Files.
    """
    cache_bytes, cache_entries = scan_user_caches()
    downloads_data = scan_downloads_junk()
    dev_bytes, dev_entries = scan_developer_caches()
    log_bytes, log_entries = scan_system_logs()
    trash_bytes, trash_entries = scan_trash()
    large_files = scan_large_files()

    installer_bytes = sum(i["size_bytes"] for i in downloads_data["installers"])
    archive_bytes = sum(a["size_bytes"] for a in downloads_data["archives"])

    # Safe cleanable space: Trash + Leftover installers + Developer caches + Logs
    safe_cleanable_bytes = trash_bytes + installer_bytes + dev_bytes + log_bytes
    total_junk_bytes = safe_cleanable_bytes + cache_bytes

    return {
        "summary": {
            "safe_cleanable_mb": round(safe_cleanable_bytes / (1024 ** 2), 2),
            "safe_cleanable_gb": round(safe_cleanable_bytes / (1024 ** 3), 2),
            "total_caches_mb": round(cache_bytes / (1024 ** 2), 2),
            "total_caches_gb": round(cache_bytes / (1024 ** 3), 2),
            "trash_mb": round(trash_bytes / (1024 ** 2), 2),
            "downloads_mb": downloads_data["total_size_mb"],
            "dev_caches_mb": round(dev_bytes / (1024 ** 2), 2),
            "logs_mb": round(log_bytes / (1024 ** 2), 2),
            "large_files_count": len(large_files),
            "large_files_total_mb": round(sum(f["size_mb"] for f in large_files), 2)
        },
        "caches": cache_entries,
        "downloads": downloads_data,
        "developer_caches": dev_entries,
        "logs": log_entries,
        "trash": trash_entries,
        "large_files": large_files
    }


# Display Helpers
def display_files_summary(summary):
    print(f"Direct Safe Cleanup Potential: {summary['safe_cleanable_mb']:.2f} MB ({summary['safe_cleanable_gb']:.2f} GB)")
    print(f"User App Caches:              {summary['total_caches_mb']:.2f} MB ({summary['total_caches_gb']:.2f} GB)")
    print(f"Developer Caches:             {summary['dev_caches_mb']:.2f} MB")
    print(f"Downloads Folder Total:       {summary['downloads_mb']:.2f} MB ({summary['downloads_mb']/1024:.2f} GB)")
    print(f"System & App Logs:            {summary['logs_mb']:.2f} MB")
    print(f"Trash Storage:                {summary['trash_mb']:.2f} MB")
    print(f"Large Files Tracked (>=100MB):{summary['large_files_count']} files ({summary['large_files_total_mb']/1024:.2f} GB)")


def display_downloads_junk(downloads):
    installers = downloads["installers"]
    if not installers:
        print("No leftover disk images (.dmg/.pkg) found in Downloads.")
        return

    print(f"{'INSTALLER / DISK IMAGE':<40} {'SIZE (MB)':<12} {'AGE':<12} {'MODIFIED'}")
    print("-" * 80)
    for i in installers[:10]:
        name = i["name"][:38]
        sz = f"{i['size_mb']:.1f}"
        age = f"{i['days_old']} days"
        print(f"{name:<40} {sz:<12} {age:<12} {i['modified']}")


def display_developer_caches(dev_caches):
    if not dev_caches:
        print("No developer cache bloat detected.")
        return

    print(f"{'DEVELOPER TOOL':<30} {'SIZE (MB)':<14} {'LOCATION'}")
    print("-" * 85)
    for d in dev_caches:
        name = d["name"][:28]
        sz = f"{d['size_mb']:.1f}"
        loc = d["path"]
        print(f"{name:<30} {sz:<14} {loc}")


def display_cache_breakdown(caches, top_n=10):
    if not caches:
        print("No significant application caches found.")
        return

    print(f"{'APPLICATION CACHE':<38} {'SIZE (MB)':<14} {'PATH'}")
    print("-" * 85)
    for c in caches[:top_n]:
        name = c["name"][:36]
        sz = f"{c['size_mb']:.1f}"
        p = c["path"]
        print(f"{name:<38} {sz:<14} {p}")


def display_large_files(large_files, top_n=10):
    if not large_files:
        print("No large files (>= 100 MB) found.")
        return

    print(f"{'FILE NAME':<38} {'SIZE (MB)':<12} {'AGE':<12} {'LOCATION'}")
    print("-" * 95)
    for f in large_files[:top_n]:
        name = f["name"][:36]
        sz = f"{f['size_mb']:.1f}"
        age = f"{f['days_old']} days"
        loc = f["location"][:32]
        print(f"{name:<38} {sz:<12} {age:<12} {loc}")


if __name__ == "__main__":
    print("Scanning system files, caches, installers, and storage hygiene...")
    snapshot = get_file_cleanup_snapshot()

    print("\n" + "=" * 65)
    print("STORAGE HYGIENE & CLEANUP SUMMARY")
    print("=" * 65)
    display_files_summary(snapshot["summary"])

    print("\n" + "=" * 65)
    print("LEFTOVER INSTALLERS & DISK IMAGES (.dmg / .pkg in ~/Downloads)")
    print("=" * 65)
    display_downloads_junk(snapshot["downloads"])

    print("\n" + "=" * 65)
    print("DEVELOPER TOOLING CACHES (REBUILDABLE JUNK)")
    print("=" * 65)
    display_developer_caches(snapshot["developer_caches"])

    print("\n" + "=" * 65)
    print("TOP 10 APPLICATION CACHES (~/Library/Caches)")
    print("=" * 65)
    display_cache_breakdown(snapshot["caches"], top_n=10)

    print("\n" + "=" * 65)
    print("TOP 10 LARGEST FILES ON DISK (>= 100 MB)")
    print("=" * 65)
    display_large_files(snapshot["large_files"], top_n=10)
