import os
import plistlib
import subprocess
import datetime


def get_dir_size(path):
    """Calculates total size of a directory in bytes using scandir."""
    total = 0
    try:
        for entry in os.scandir(path):
            if entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
            elif entry.is_dir(follow_symlinks=False):
                total += get_dir_size(entry.path)
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return total


def get_app_type(path):
    """Classifies an application based on its installation location."""
    if path.startswith("/System/"):
        return "system"
    if "/Utilities" in path:
        return "utility"
    if "/Applications" in path:
        return "user_app"
    return "other"


def get_app_developer(app_path):
    """Extracts the code signing authority or developer name using codesign."""
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


def get_installed_software(scan_dirs=None):
    """
    Scans the system for installed applications and collects structured metadata:
    name, version, bundle ID, disk size, category type, developer authority,
    and modification dates.
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
                except Exception:
                    pass

            size_bytes = get_dir_size(app_path)
            size_mb = size_bytes / (1024 ** 2)
            dev = get_app_developer(app_path)
            app_type = get_app_type(app_path)

            try:
                mtime = os.path.getmtime(app_path)
                last_modified = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            except Exception:
                last_modified = "Unknown"

            software = {
                "name": str(name),
                "version": str(version),
                "bundle_id": str(bundle_id),
                "path": app_path,
                "size_mb": round(size_mb, 2),
                "size_bytes": size_bytes,
                "type": app_type,
                "developer": dev,
                "last_modified": last_modified,
                "min_os": str(min_os)
            }

            software_list.append(software)

    return software_list


# Top N largest software
def top_software_by_size(software_list, n):
    return sorted(
        software_list,
        key=lambda s: s["size_mb"],
        reverse=True
    )[:n]


# Group software by category type (user_app, system, utility, other)
def group_by_type(software_list):
    groups = {}
    for app in software_list:
        app_type = app["type"]
        if app_type not in groups:
            groups[app_type] = {
                "type": app_type,
                "count": 0,
                "total_size_mb": 0.0,
                "apps": []
            }
        groups[app_type]["count"] += 1
        groups[app_type]["total_size_mb"] += app["size_mb"]
        groups[app_type]["apps"].append(app)

    return list(groups.values())


# Group software by developer / publisher
def group_by_developer(software_list):
    devs = {}
    for app in software_list:
        dev = app["developer"]
        if dev not in devs:
            devs[dev] = {
                "developer": dev,
                "count": 0,
                "total_size_mb": 0.0,
                "apps": []
            }
        devs[dev]["count"] += 1
        devs[dev]["total_size_mb"] += app["size_mb"]
        devs[dev]["apps"].append(app["name"])

    return list(devs.values())


# Top N developers by disk footprint
def top_developers_by_size(dev_groups, n):
    return sorted(
        dev_groups,
        key=lambda d: d["total_size_mb"],
        reverse=True
    )[:n]


# Filter software by type
def filter_by_type(software_list, app_type):
    return [app for app in software_list if app["type"] == app_type]


# Find unsigned / unknown applications
def find_unsigned_software(software_list):
    return [app for app in software_list if "Unsigned" in app["developer"]]


# Display helpers
def display_software(software_list):
    print(f"{'APPLICATION':<32} {'VERSION':<14} {'SIZE (MB)':<12} {'TYPE':<12} {'DEVELOPER'}")
    print("-" * 95)
    for s in software_list:
        name = s["name"][:30]
        version = str(s["version"])[:12]
        size_str = f"{s['size_mb']:.1f}"
        app_type = s["type"]
        dev = s["developer"][:30]

        print(
            f"{name:<32} "
            f"{version:<14} "
            f"{size_str:<12} "
            f"{app_type:<12} "
            f"{dev}"
        )


def display_software_summary(software_list):
    total_count = len(software_list)
    total_size_mb = sum(s["size_mb"] for s in software_list)
    total_size_gb = total_size_mb / 1024

    print(f"Total Applications: {total_count}")
    print(f"Total Disk Space Used: {total_size_mb:.2f} MB ({total_size_gb:.2f} GB)")


def display_type_summary(type_groups):
    print(f"{'TYPE':<15} {'COUNT':<10} {'TOTAL SIZE (MB)':<18} {'TOTAL SIZE (GB)'}")
    print("-" * 60)
    for g in sorted(type_groups, key=lambda x: x["total_size_mb"], reverse=True):
        size_gb = g["total_size_mb"] / 1024
        print(
            f"{g['type']:<15} "
            f"{g['count']:<10} "
            f"{g['total_size_mb']:<18.1f} "
            f"{size_gb:.2f} GB"
        )


def display_developer_summary(dev_groups):
    print(f"{'DEVELOPER':<35} {'APPS':<8} {'TOTAL SIZE (MB)':<18} {'TOTAL SIZE (GB)'}")
    print("-" * 75)
    for d in dev_groups:
        size_gb = d["total_size_mb"] / 1024
        dev_name = d["developer"][:33]
        print(
            f"{dev_name:<35} "
            f"{d['count']:<8} "
            f"{d['total_size_mb']:<18.1f} "
            f"{size_gb:.2f} GB"
        )


if __name__ == "__main__":
    print("Scanning installed software...")
    software_list = get_installed_software()

    print("\nOVERALL SOFTWARE SUMMARY")
    display_software_summary(software_list)

    print("\nTOP 10 APPLICATIONS BY SIZE")
    largest_apps = top_software_by_size(software_list, 10)
    display_software(largest_apps)

    print("\nAPPLICATIONS BY CATEGORY")
    type_groups = group_by_type(software_list)
    display_type_summary(type_groups)

    print("\nTOP 10 DEVELOPERS / VENDORS BY DISK FOOTPRINT")
    dev_groups = group_by_developer(software_list)
    top_devs = top_developers_by_size(dev_groups, 10)
    display_developer_summary(top_devs)

    unsigned_apps = find_unsigned_software(software_list)
    if unsigned_apps:
        print(f"\nUNSIGNED / UNVERIFIED APPLICATIONS ({len(unsigned_apps)} found)")
        display_software(unsigned_apps)
