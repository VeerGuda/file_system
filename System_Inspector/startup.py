import os
import plistlib
import subprocess


def get_launchctl_jobs():
    """
    Retrieves the current status of all launchd jobs via `launchctl list`.
    Returns a dictionary mapping label -> {"pid": int or None, "status": int}.
    """
    jobs = {}
    try:
        res = subprocess.run(
            ["launchctl", "list"],
            capture_output=True,
            text=True,
            timeout=5
        )
        for line in res.stdout.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 3:
                pid_str, status_str, label = parts[0], parts[1], parts[2]
                pid = int(pid_str) if pid_str != "-" else None
                try:
                    status = int(status_str)
                except ValueError:
                    status = 0
                jobs[label] = {"pid": pid, "status": status}
    except Exception:
        pass
    return jobs


def get_running_process_metrics(pids):
    """
    Retrieves live CPU% and Memory% for a list of active PIDs via `ps`.
    Returns a dictionary mapping pid -> {"cpu": float, "mem": float}.
    """
    metrics = {}
    valid_pids = [p for p in pids if p is not None]
    if not valid_pids:
        return metrics

    try:
        pid_str = ",".join(str(p) for p in valid_pids)
        res = subprocess.run(
            ["ps", "-p", pid_str, "-o", "pid,%cpu,%mem"],
            capture_output=True,
            text=True,
            timeout=3
        )
        for line in res.stdout.splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 3:
                p = int(parts[0])
                cpu = float(parts[1])
                mem = float(parts[2])
                metrics[p] = {"cpu": cpu, "mem": mem}
    except Exception:
        pass
    return metrics


def get_app_developer(exec_path):
    """Extracts code signing authority or vendor name using codesign."""
    if not exec_path or not os.path.exists(exec_path):
        return "Missing Binary"
    try:
        res = subprocess.run(
            ["codesign", "-dvv", exec_path],
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


def get_startup_items(scan_dirs=None):
    """
    Scans macOS launch directories (LaunchAgents and LaunchDaemons),
    parses their property list (.plist) configurations, verifies executable paths,
    and cross-references with active launchd PIDs and live resource usage.
    """
    if scan_dirs is None:
        scan_dirs = [
            ("user_agent", os.path.expanduser("~/Library/LaunchAgents")),
            ("global_agent", "/Library/LaunchAgents"),
            ("system_daemon", "/Library/LaunchDaemons"),
        ]

    launchctl_jobs = get_launchctl_jobs()
    startup_items = []
    active_pids = set()

    # First pass: collect plist configurations
    raw_items = []
    for loc_type, loc_path in scan_dirs:
        if not os.path.exists(loc_path):
            continue

        try:
            files = os.listdir(loc_path)
        except (PermissionError, OSError):
            continue

        for f in files:
            if not f.endswith(".plist"):
                continue

            plist_path = os.path.join(loc_path, f)
            try:
                with open(plist_path, "rb") as fp:
                    pl = plistlib.load(fp)

                label = pl.get("Label", f[:-6])
                prog = pl.get("Program")
                args = pl.get("ProgramArguments", [])

                # Extract primary binary path and full command string
                if prog:
                    exec_path = prog
                    cmd_str = prog
                elif args and isinstance(args, list) and len(args) > 0:
                    exec_path = args[0]
                    cmd_str = " ".join(args)
                else:
                    exec_path = None
                    cmd_str = "None"

                run_at_load = bool(pl.get("RunAtLoad", False))
                keep_alive = bool(pl.get("KeepAlive", False))
                disabled = bool(pl.get("Disabled", False))

                binary_exists = os.path.exists(exec_path) if exec_path else False
                dev = get_app_developer(exec_path) if exec_path else "No Executable Specified"

                job_info = launchctl_jobs.get(label, {})
                pid = job_info.get("pid")
                status_code = job_info.get("status")

                if pid is not None:
                    active_pids.add(pid)

                raw_items.append({
                    "label": label,
                    "plist_path": plist_path,
                    "filename": f,
                    "type": loc_type,
                    "command": cmd_str,
                    "executable": exec_path,
                    "binary_exists": binary_exists,
                    "run_at_load": run_at_load,
                    "keep_alive": keep_alive,
                    "disabled": disabled,
                    "developer": dev,
                    "pid": pid,
                    "status_code": status_code,
                })
            except Exception:
                pass

    # Second pass: query live CPU and Memory metrics for active PIDs
    process_metrics = get_running_process_metrics(active_pids)

    for item in raw_items:
        pid = item["pid"]
        metrics = process_metrics.get(pid, {"cpu": 0.0, "mem": 0.0})
        item["cpu"] = metrics["cpu"]
        item["mem"] = metrics["mem"]
        item["is_running"] = pid is not None
        startup_items.append(item)

    return startup_items


# Analytics: Items configured to auto-start at boot or login
def find_auto_start_items(items):
    return [i for i in items if (i["run_at_load"] or i["keep_alive"]) and not i["disabled"]]


# Analytics: Items currently executing in memory
def find_running_startup_items(items):
    return sorted(
        [i for i in items if i["is_running"]],
        key=lambda x: (x["cpu"], x["mem"]),
        reverse=True
    )


# Analytics: Orphaned / broken startup plists (missing target binary)
def find_orphaned_startup_items(items):
    return [i for i in items if i["executable"] and not i["binary_exists"]]


# Analytics: Unsigned or unverified startup items
def find_unsigned_startup_items(items):
    return [i for i in items if "Unsigned" in i["developer"]]


# Analytics: Group startup items by category type
def group_by_type(items):
    groups = {}
    for i in items:
        t = i["type"]
        if t not in groups:
            groups[t] = {"type": t, "count": 0, "running": 0, "items": []}
        groups[t]["count"] += 1
        if i["is_running"]:
            groups[t]["running"] += 1
        groups[t]["items"].append(i)
    return list(groups.values())


# Analytics: Group startup items by developer/vendor
def group_by_developer(items):
    devs = {}
    for i in items:
        dev = i["developer"]
        if dev not in devs:
            devs[dev] = {"developer": dev, "count": 0, "running": 0, "items": []}
        devs[dev]["count"] += 1
        if i["is_running"]:
            devs[dev]["running"] += 1
        devs[dev]["items"].append(i["label"])
    return list(devs.values())


# Display helpers
def display_startup_items(items):
    print(
        f"{'SERVICE / LABEL':<36} "
        f"{'TYPE':<14} "
        f"{'AUTO-START':<11} "
        f"{'STATUS':<10} "
        f"{'PID':<8} "
        f"{'CPU%':<6} "
        f"{'MEM%':<6} "
        f"{'DEVELOPER'}"
    )
    print("-" * 115)
    for i in items:
        label = i["label"][:34]
        loc_type = i["type"]
        auto = "Yes" if (i["run_at_load"] or i["keep_alive"]) and not i["disabled"] else "No"
        status = "Running" if i["is_running"] else "Inactive"
        pid_str = str(i["pid"]) if i["pid"] else "-"
        cpu_str = f"{i['cpu']:.1f}" if i["is_running"] else "-"
        mem_str = f"{i['mem']:.1f}" if i["is_running"] else "-"
        dev = i["developer"][:25]

        print(
            f"{label:<36} "
            f"{loc_type:<14} "
            f"{auto:<11} "
            f"{status:<10} "
            f"{pid_str:<8} "
            f"{cpu_str:<6} "
            f"{mem_str:<6} "
            f"{dev}"
        )


def display_startup_summary(items):
    total = len(items)
    auto_start = len(find_auto_start_items(items))
    running = len([i for i in items if i["is_running"]])
    orphaned = len(find_orphaned_startup_items(items))

    print(f"Total Startup Configurations: {total}")
    print(f"Auto-Launch at Boot/Login:   {auto_start}")
    print(f"Currently Active / Running:   {running}")
    print(f"Broken / Orphaned Entries:    {orphaned}")


def display_orphaned_items(orphaned_list):
    print(f"{'SERVICE LABEL':<35} {'MISSING BINARY':<45} {'PLIST LOCATION'}")
    print("-" * 115)
    for o in orphaned_list:
        label = o["label"][:33]
        missing = o["executable"][:43] if o["executable"] else "None"
        plist = o["plist_path"]
        print(f"{label:<35} {missing:<45} {plist}")


def display_type_summary(type_groups):
    print(f"{'TYPE':<18} {'TOTAL CONFIGS':<15} {'ACTIVE / RUNNING'}")
    print("-" * 50)
    for g in sorted(type_groups, key=lambda x: x["count"], reverse=True):
        print(f"{g['type']:<18} {g['count']:<15} {g['running']}")


def display_developer_summary(dev_groups):
    print(f"{'DEVELOPER / VENDOR':<35} {'SERVICES':<10} {'ACTIVE / RUNNING'}")
    print("-" * 60)
    for d in sorted(dev_groups, key=lambda x: x["count"], reverse=True):
        dev = d["developer"][:33]
        print(f"{dev:<35} {d['count']:<10} {d['running']}")


if __name__ == "__main__":
    print("Scanning startup agents and background daemons...")
    startup_items = get_startup_items()

    print("\n" + "=" * 60)
    print("OVERALL STARTUP SERVICES SUMMARY")
    print("=" * 60)
    display_startup_summary(startup_items)

    print("\n" + "=" * 60)
    print("ACTIVE BACKGROUND DAEMONS & SERVICES (RUNNING NOW)")
    print("=" * 60)
    running_services = find_running_startup_items(startup_items)
    if running_services:
        display_startup_items(running_services)
    else:
        print("No active background services running.")

    print("\n" + "=" * 60)
    print("ALL STARTUP CONFIGURATIONS (LAUNCH AT LOGIN / BOOT)")
    print("=" * 60)
    display_startup_items(startup_items)

    orphaned = find_orphaned_startup_items(startup_items)
    if orphaned:
        print("\n" + "=" * 60)
        print(f"BROKEN / ORPHANED STARTUP ITEMS ({len(orphaned)} found - CLEANUP CANDIDATES)")
        print("=" * 60)
        display_orphaned_items(orphaned)

    unsigned = find_unsigned_startup_items(startup_items)
    if unsigned:
        print("\n" + "=" * 60)
        print(f"UNSIGNED / UNVERIFIED STARTUP SERVICES ({len(unsigned)} found)")
        print("=" * 60)
        display_startup_items(unsigned)

    print("\n" + "=" * 60)
    print("STARTUP SERVICES BY CATEGORY")
    print("=" * 60)
    type_groups = group_by_type(startup_items)
    display_type_summary(type_groups)

    print("\n" + "=" * 60)
    print("STARTUP SERVICES BY VENDOR / DEVELOPER")
    print("=" * 60)
    dev_groups = group_by_developer(startup_items)
    display_developer_summary(dev_groups)
