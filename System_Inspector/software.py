import os
import plistlib
import subprocess
import datetime
import struct


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


def get_binary_arch(app_path, executable_name):
    """
    Determines binary architecture (Apple Silicon arm64, Intel x86_64, Universal)
    by reading the Mach-O header directly.
    """
    if not executable_name:
        return "Unknown"
    exec_path = os.path.join(app_path, "Contents", "MacOS", executable_name)
    if not os.path.exists(exec_path) or not os.path.isfile(exec_path):
        return "Unknown"

    try:
        with open(exec_path, "rb") as f:
            magic = f.read(4)
            if len(magic) < 4:
                return "Unknown"

            # Universal / Fat binary
            if magic in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
                return "Universal"

            # 64-bit Mach-O
            if magic in (b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe"):
                endian = "<" if magic == b"\xcf\xfa\xed\xfe" else ">"
                cputype = struct.unpack(f"{endian}I", f.read(4))[0]
                # CPU_TYPE_ARM64 = 0x0100000C, CPU_TYPE_X86_64 = 0x01000007
                if cputype == 0x0100000C:
                    return "Apple Silicon (arm64)"
                elif cputype == 0x01000007:
                    return "Intel (x86_64)"
                return f"Mach-O 64 ({hex(cputype)})"
    except Exception:
        pass
    return "Unknown"


def get_app_developer(app_path):
    """Extracts code signing authority or developer name using codesign."""
    try:
        res = subprocess.run(
            ["codesign", "-dvv", app_path],
            capture_output=True,
            text=True,
            timeout=3
        )
        for line in res.stderr.splitlines():
            if line.startswith("Authority=Developer ID Application:"):
                val = line.split(":", 1)[1].strip()
                if "(" in val and val.endswith(")"):
                    val = val[:val.rfind("(")].strip()
                return val
            elif line.startswith("Authority=Apple Mac OS Application Signing"):
                return "Apple (Mac App Store)"
            elif line.startswith("Authority=Software Signing"):
                return "Apple System"
            elif "Apple Root CA" in line:
                return "Apple"
    except Exception:
        pass
    return "Unknown / Unsigned"


def get_app_type(path):
    """Classifies an application based on its installation location."""
    if path.startswith("/System/"):
        return "system"
    if "/Utilities" in path:
        return "utility"
    if "/Applications" in path:
        return "user_app"
    return "other"


def index_library_directories():
    """
    Indexes top-level directories in user Library locations to speed up
    associated data matching without redundant directory traversals.
    """
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, "Library", "Application Support"),
        os.path.join(home, "Library", "Caches"),
        os.path.join(home, "Library", "Containers"),
        os.path.join(home, "Library", "Logs"),
        os.path.join(home, "Library", "Saved Application State"),
        "/Library/Application Support"
    ]

    entries = []
    for root in roots:
        if os.path.exists(root):
            try:
                for entry in os.scandir(root):
                    entries.append((entry.name, entry.path))
            except (PermissionError, OSError):
                pass
    return entries


def find_associated_data(name, bundle_id, developer, indexed_lib_entries):
    """
    Finds associated Application Support, Cache, Container, and Log directories
    belonging to an application and calculates their total disk usage.
    """
    search_terms = {name.lower()}
    if " " in name:
        search_terms.add(name.replace(" ", "").lower())

    bid_lower = bundle_id.lower() if bundle_id and bundle_id != "Unknown" else ""
    if bid_lower:
        search_terms.add(bid_lower)
        search_terms.add(f"{bid_lower}.savedstate")

    matched_paths = []
    for ename, epath in indexed_lib_entries:
        elower = ename.lower()
        is_match = False

        if elower in search_terms:
            is_match = True
        elif bid_lower and (elower.startswith(bid_lower + ".") or elower.startswith(bid_lower + "-")):
            is_match = True

        if is_match:
            matched_paths.append(epath)

    total_bytes = 0
    detailed_paths = []
    for p in set(matched_paths):
        sz = get_physical_size(p)
        if sz > 0:
            total_bytes += sz
            detailed_paths.append({"path": p, "size_mb": round(sz / (1024 ** 2), 2)})

    return total_bytes, detailed_paths


def get_last_used_dates(app_paths):
    """
    Queries macOS Spotlight metadata (kMDItemLastUsedDate) in a single batch call.
    Returns a dictionary mapping app_path -> last_used_string (YYYY-MM-DD or Never).
    """
    last_used_map = {}
    if not app_paths:
        return last_used_map

    try:
        cmd = ["mdls", "-name", "kMDItemLastUsedDate"] + app_paths
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]

        for i, line in enumerate(lines):
            if i < len(app_paths):
                path = app_paths[i]
                if "=" in line:
                    val = line.split("=", 1)[1].strip()
                    if val == "(null)" or val == "None" or not val:
                        last_used_map[path] = "Never"
                    else:
                        # Value format: "2026-09-08 00:43:41 +0000"
                        date_str = val.split()[0]
                        last_used_map[path] = date_str
                else:
                    last_used_map[path] = "Unknown"
    except Exception:
        for p in app_paths:
            last_used_map[p] = "Unknown"

    return last_used_map


def get_installed_software(scan_dirs=None):
    """
    Scans the system for installed applications and collects comprehensive metadata:
    - App bundle size & associated Library/Cache data size
    - Architecture (Apple Silicon / Intel / Universal)
    - Last used activity & last modified dates
    - Code signing developer authority & application category
    """
    if scan_dirs is None:
        scan_dirs = [
            "/Applications",
            os.path.expanduser("~/Applications"),
            "/System/Applications",
            "/System/Applications/Utilities"
        ]

    software_list = []
    seen_paths = set()
    app_paths_for_batch = []
    preliminary_apps = []

    # Index library entries once for rapid associated data matching
    indexed_lib = index_library_directories()

    for base_dir in scan_dirs:
        if not os.path.exists(base_dir):
            continue

        try:
            entries = os.listdir(base_dir)
        except (PermissionError, OSError):
            continue

        for item in entries:
            if not item.endswith(".app"):
                continue

            app_path = os.path.join(base_dir, item)
            if app_path in seen_paths:
                continue
            seen_paths.add(app_path)

            plist_path = os.path.join(app_path, "Contents", "Info.plist")

            name = item[:-4]
            version = "Unknown"
            bundle_id = "Unknown"
            min_os = "Unknown"
            executable_name = None

            if os.path.exists(plist_path):
                try:
                    with open(plist_path, "rb") as f:
                        plist = plistlib.load(f)
                        name = (
                            plist.get("CFBundleDisplayName")
                            or plist.get("CFBundleName")
                            or name
                        )
                        version = (
                            plist.get("CFBundleShortVersionString")
                            or plist.get("CFBundleVersion")
                            or version
                        )
                        bundle_id = plist.get("CFBundleIdentifier") or bundle_id
                        min_os = plist.get("LSMinimumSystemVersion") or min_os
                        executable_name = plist.get("CFBundleExecutable")
                except Exception:
                    pass

            app_size_bytes = get_physical_size(app_path)
            app_size_mb = app_size_bytes / (1024 ** 2)
            dev = get_app_developer(app_path)
            app_type = get_app_type(app_path)
            arch = get_binary_arch(app_path, executable_name)

            try:
                mtime = os.path.getmtime(app_path)
                last_modified = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            except Exception:
                last_modified = "Unknown"

            # Associated data calculation
            data_bytes, associated_paths = find_associated_data(
                str(name), str(bundle_id), dev, indexed_lib
            )
            data_size_mb = data_bytes / (1024 ** 2)
            total_size_mb = app_size_mb + data_size_mb

            app_data = {
                "name": str(name),
                "version": str(version),
                "bundle_id": str(bundle_id),
                "path": app_path,
                "app_size_mb": round(app_size_mb, 2),
                "data_size_mb": round(data_size_mb, 2),
                "total_size_mb": round(total_size_mb, 2),
                "architecture": arch,
                "type": app_type,
                "developer": dev,
                "last_modified": last_modified,
                "min_os": str(min_os),
                "associated_paths": associated_paths
            }

            preliminary_apps.append(app_data)
            app_paths_for_batch.append(app_path)

    # Batch query last used dates via Spotlight metadata
    last_used_map = get_last_used_dates(app_paths_for_batch)

    for app in preliminary_apps:
        app["last_used"] = last_used_map.get(app["path"], "Unknown")
        software_list.append(app)

    return software_list


# Analytics: Top applications by total combined size (app + data)
def top_software_by_total_size(software_list, n):
    return sorted(
        software_list,
        key=lambda s: s["total_size_mb"],
        reverse=True
    )[:n]


# Analytics: Top applications with largest associated support / cache data
def top_software_by_data_size(software_list, n):
    return sorted(
        software_list,
        key=lambda s: s["data_size_mb"],
        reverse=True
    )[:n]


# Analytics: Unused applications (never opened or not opened in threshold days)
def find_unused_software(software_list, days_threshold=90):
    unused = []
    now = datetime.datetime.now()

    for app in software_list:
        if app["type"] == "system":
            continue

        last_used = app["last_used"]
        if last_used == "Never":
            unused.append(app)
        elif last_used not in ("Unknown", "None"):
            try:
                dt = datetime.datetime.strptime(last_used, "%Y-%m-%d")
                days_ago = (now - dt).days
                if days_ago >= days_threshold:
                    app_copy = dict(app)
                    app_copy["days_inactive"] = days_ago
                    unused.append(app_copy)
            except Exception:
                pass

    return sorted(unused, key=lambda x: x["total_size_mb"], reverse=True)


# Analytics: Intel x86_64 software running via Rosetta 2
def find_intel_rosetta_software(software_list):
    return [app for app in software_list if "Intel" in app["architecture"]]


# Analytics: Unsigned or unverified applications
def find_unsigned_software(software_list):
    return [app for app in software_list if "Unsigned" in app["developer"]]


# Analytics: Group software by type
def group_by_type(software_list):
    groups = {}
    for app in software_list:
        app_type = app["type"]
        if app_type not in groups:
            groups[app_type] = {
                "type": app_type,
                "count": 0,
                "app_size_mb": 0.0,
                "data_size_mb": 0.0,
                "total_size_mb": 0.0
            }
        groups[app_type]["count"] += 1
        groups[app_type]["app_size_mb"] += app["app_size_mb"]
        groups[app_type]["data_size_mb"] += app["data_size_mb"]
        groups[app_type]["total_size_mb"] += app["total_size_mb"]

    return list(groups.values())


# Analytics: Group software by developer
def group_by_developer(software_list):
    devs = {}
    for app in software_list:
        dev = app["developer"]
        if dev not in devs:
            devs[dev] = {
                "developer": dev,
                "count": 0,
                "total_size_mb": 0.0
            }
        devs[dev]["count"] += 1
        devs[dev]["total_size_mb"] += app["total_size_mb"]

    return list(devs.values())


# Analytics: Top developers by total disk usage
def top_developers_by_size(dev_groups, n):
    return sorted(
        dev_groups,
        key=lambda d: d["total_size_mb"],
        reverse=True
    )[:n]


# Display formatting helpers
def display_software(software_list):
    print(
        f"{'APPLICATION':<28} "
        f"{'VERSION':<10} "
        f"{'ARCH':<16} "
        f"{'APP (MB)':<10} "
        f"{'DATA (MB)':<10} "
        f"{'TOTAL (MB)':<11} "
        f"{'LAST USED'}"
    )
    print("-" * 105)
    for s in software_list:
        name = s["name"][:26]
        version = str(s["version"])[:9]
        arch = s["architecture"][:15]
        app_sz = f"{s['app_size_mb']:.1f}"
        data_sz = f"{s['data_size_mb']:.1f}"
        total_sz = f"{s['total_size_mb']:.1f}"
        last_used = s["last_used"]

        print(
            f"{name:<28} "
            f"{version:<10} "
            f"{arch:<16} "
            f"{app_sz:<10} "
            f"{data_sz:<10} "
            f"{total_sz:<11} "
            f"{last_used}"
        )


def display_software_summary(software_list):
    total_count = len(software_list)
    total_app_mb = sum(s["app_size_mb"] for s in software_list)
    total_data_mb = sum(s["data_size_mb"] for s in software_list)
    total_mb = total_app_mb + total_data_mb

    print(f"Total Applications: {total_count}")
    print(f"App Bundles Storage:  {total_app_mb:.2f} MB ({total_app_mb / 1024:.2f} GB)")
    print(f"Associated Data/Cache:{total_data_mb:.2f} MB ({total_data_mb / 1024:.2f} GB)")
    print(f"Total Disk Footprint: {total_mb:.2f} MB ({total_mb / 1024:.2f} GB)")


def display_unused_software(unused_list):
    print(
        f"{'APPLICATION':<30} "
        f"{'APP (MB)':<12} "
        f"{'DATA (MB)':<12} "
        f"{'TOTAL (MB)':<12} "
        f"{'STATUS / LAST USED'}"
    )
    print("-" * 90)
    for u in unused_list:
        name = u["name"][:28]
        status = "Never Opened" if u["last_used"] == "Never" else f"{u.get('days_inactive', '')} days ago ({u['last_used']})"
        print(
            f"{name:<30} "
            f"{u['app_size_mb']:<12.1f} "
            f"{u['data_size_mb']:<12.1f} "
            f"{u['total_size_mb']:<12.1f} "
            f"{status}"
        )


def display_type_summary(type_groups):
    print(f"{'TYPE':<12} {'COUNT':<8} {'APP (MB)':<12} {'DATA (MB)':<12} {'TOTAL (GB)'}")
    print("-" * 60)
    for g in sorted(type_groups, key=lambda x: x["total_size_mb"], reverse=True):
        total_gb = g["total_size_mb"] / 1024
        print(
            f"{g['type']:<12} "
            f"{g['count']:<8} "
            f"{g['app_size_mb']:<12.1f} "
            f"{g['data_size_mb']:<12.1f} "
            f"{total_gb:.2f} GB"
        )


def display_developer_summary(dev_groups):
    print(f"{'DEVELOPER / VENDOR':<35} {'APPS':<8} {'TOTAL (MB)':<14} {'TOTAL (GB)'}")
    print("-" * 70)
    for d in dev_groups:
        size_gb = d["total_size_mb"] / 1024
        dev_name = d["developer"][:33]
        print(
            f"{dev_name:<35} "
            f"{d['count']:<8} "
            f"{d['total_size_mb']:<14.1f} "
            f"{size_gb:.2f} GB"
        )


if __name__ == "__main__":
    print("Performing comprehensive software scan...")
    software_list = get_installed_software()

    print("\n" + "=" * 50)
    print("OVERALL SOFTWARE & STORAGE SUMMARY")
    print("=" * 50)
    display_software_summary(software_list)

    print("\n" + "=" * 50)
    print("TOP 10 APPLICATIONS BY TOTAL FOOTPRINT (APP + DATA)")
    print("=" * 50)
    largest_total = top_software_by_total_size(software_list, 10)
    display_software(largest_total)

    print("\n" + "=" * 50)
    print("TOP 5 APPLICATIONS WITH LARGEST ASSOCIATED CACHE/DATA")
    print("=" * 50)
    data_hogs = top_software_by_data_size(software_list, 5)
    display_software(data_hogs)

    print("\n" + "=" * 50)
    print("UNUSED / ABANDONED SOFTWARE (CLEANUP CANDIDATES)")
    print("=" * 50)
    unused_apps = find_unused_software(software_list, days_threshold=90)
    if unused_apps:
        display_unused_software(unused_apps[:10])
    else:
        print("No unused software found.")

    intel_apps = find_intel_rosetta_software(software_list)
    if intel_apps:
        print("\n" + "=" * 50)
        print(f"LEGACY INTEL / ROSETTA 2 APPLICATIONS ({len(intel_apps)} found)")
        print("=" * 50)
        display_software(intel_apps)

    print("\n" + "=" * 50)
    print("APPLICATIONS BY CATEGORY")
    print("=" * 50)
    type_groups = group_by_type(software_list)
    display_type_summary(type_groups)

    print("\n" + "=" * 50)
    print("TOP 10 DEVELOPERS BY TOTAL STORAGE FOOTPRINT")
    print("=" * 50)
    dev_groups = group_by_developer(software_list)
    top_devs = top_developers_by_size(dev_groups, 10)
    display_developer_summary(top_devs)

    unsigned_apps = find_unsigned_software(software_list)
    if unsigned_apps:
        print("\n" + "=" * 50)
        print(f"UNSIGNED / UNVERIFIED APPLICATIONS ({len(unsigned_apps)} found)")
        print("=" * 50)
        display_software(unsigned_apps)
