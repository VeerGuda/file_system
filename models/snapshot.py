"""
models/snapshot.py

Unified System Snapshot model.
Collects data once across all 5 system collectors and cross-references
processes, software, and startup entries into an integrated machine state.
"""

import os
import json
import datetime

from System_Inspector.system_stats import get_system_stats
from System_Inspector.processes import get_processes, group_by_application
from System_Inspector.startup import get_startup_items
from System_Inspector.software import get_installed_software
from System_Inspector.files import get_file_cleanup_snapshot


def match_startup_to_processes(startup_entries, processes):
    """
    Cross-references startup entries with live running processes.
    Enriches startup items with matching PIDs and running status.
    """
    # Create lookup map of running command basenames and full paths to PIDs
    cmd_to_pids = {}
    for p in processes:
        cmd = p.get("command", "")
        pid = p.get("pid")
        basename = os.path.basename(cmd)

        if cmd not in cmd_to_pids:
            cmd_to_pids[cmd] = []
        cmd_to_pids[cmd].append(pid)

        if basename not in cmd_to_pids:
            cmd_to_pids[basename] = []
        cmd_to_pids[basename].append(pid)

    for entry in startup_entries:
        matching_pids = []
        exec_path = entry.get("executable")

        if exec_path:
            # Check full executable path
            if exec_path in cmd_to_pids:
                matching_pids.extend(cmd_to_pids[exec_path])
            # Check executable basename
            exec_base = os.path.basename(exec_path)
            if exec_base in cmd_to_pids:
                matching_pids.extend(cmd_to_pids[exec_base])

        # If already matched via launchctl list, include it
        if entry.get("pid") and entry["pid"] not in matching_pids:
            matching_pids.append(entry["pid"])

        unique_pids = sorted(list(set(matching_pids)))
        entry["matching_pids"] = unique_pids
        entry["running"] = len(unique_pids) > 0


def build_application_inventory(installed_apps, grouped_running_apps, startup_entries):
    """
    Merges installed apps, running apps, and startup entries into a unified
    application inventory to answer:
    'Is this app installed? Is it running? Does it start automatically? How much CPU/RAM/Disk does it use?'
    """
    inventory = {}

    # 1. Index installed applications
    for app in installed_apps:
        name = app.get("name")
        app_path = app.get("path", "")
        folder_name = os.path.basename(app_path).replace(".app", "") if app_path else name

        entry = {
            "name": folder_name if folder_name else name,
            "display_name": name,
            "bundle_id": app.get("bundle_id"),
            "version": app.get("version"),
            "path": app_path,
            "installed": True,
            "running": False,
            "startup": False,
            "cpu_percent": 0.0,
            "mem_percent": 0.0,
            "process_count": 0,
            "app_size_bytes": app.get("app_size_bytes", 0),
            "data_size_bytes": sum(p.get("size_mb", 0) for p in app.get("associated_paths", [])) * (1024 ** 2),
            "total_size_mb": app.get("total_size_mb", 0.0),
            "architecture": app.get("architecture", "Unknown"),
            "developer": app.get("developer", "Unknown"),
            "last_used": app.get("last_used", "Unknown"),
            "type": app.get("type", "user_app"),
            "startup_labels": [],
            "matching_pids": []
        }

        # Index under both keys for flexible matching
        inventory[name.lower()] = entry
        if folder_name and folder_name.lower() != name.lower():
            inventory[folder_name.lower()] = entry

    # 2. Merge running applications
    for gapp in grouped_running_apps:
        name = gapp.get("name")
        key = name.lower()
        if key not in inventory:
            # Running process not in /Applications (e.g. system daemon, CLI tool)
            inventory[key] = {
                "name": name,
                "bundle_id": None,
                "version": None,
                "path": gapp.get("command"),
                "installed": False,
                "running": True,
                "startup": False,
                "cpu_percent": round(gapp.get("cpu", 0.0), 2),
                "mem_percent": round(gapp.get("mem", 0.0), 2),
                "process_count": gapp.get("count", 1),
                "app_size_bytes": 0,
                "data_size_bytes": 0,
                "total_size_mb": 0.0,
                "architecture": "Unknown",
                "developer": "Unknown",
                "last_used": "Running",
                "type": gapp.get("type", "other"),
                "startup_labels": [],
                "matching_pids": []
            }
        else:
            inventory[key]["running"] = True
            inventory[key]["cpu_percent"] = round(gapp.get("cpu", 0.0), 2)
            inventory[key]["mem_percent"] = round(gapp.get("mem", 0.0), 2)
            inventory[key]["process_count"] = gapp.get("count", 1)

    # 3. Merge startup entries
    for sentry in startup_entries:
        label = sentry.get("label", "")
        exec_path = sentry.get("executable") or ""

        matched = False
        # Try matching by app name or executable path
        for key, item in inventory.items():
            app_name = item["name"].lower()
            if (app_name in label.lower()) or (item["path"] and item["path"] in exec_path):
                item["startup"] = True
                item["startup_labels"].append(label)
                if sentry.get("matching_pids"):
                    item["matching_pids"].extend(sentry["matching_pids"])
                matched = True

        if not matched:
            # Standalone background daemon
            key = label.lower()
            inventory[key] = {
                "name": label,
                "bundle_id": label,
                "version": None,
                "path": exec_path,
                "installed": True,
                "running": sentry.get("is_running", False),
                "startup": True,
                "cpu_percent": round(sentry.get("cpu", 0.0), 2),
                "mem_percent": round(sentry.get("mem", 0.0), 2),
                "process_count": 1 if sentry.get("is_running") else 0,
                "app_size_bytes": 0,
                "data_size_bytes": 0,
                "total_size_mb": 0.0,
                "architecture": "Unknown",
                "developer": sentry.get("developer", "Unknown"),
                "last_used": "Unknown",
                "type": sentry.get("type", "daemon"),
                "startup_labels": [label],
                "matching_pids": sentry.get("matching_pids", [])
            }

    # Deduplicate objects
    unique_inventory = []
    seen_ids = set()
    for item in inventory.values():
        item_id = id(item)
        if item_id not in seen_ids:
            seen_ids.add(item_id)
            unique_inventory.append(item)

    return unique_inventory


def build_snapshot(scan_dirs=None):
    """
    Executes all 5 system collectors in one single pass and builds a unified machine snapshot.
    Collects once -> reusable across all analytical modules.
    """
    timestamp = datetime.datetime.now().isoformat()

    # 1. Hardware & System Vitals
    system_data = get_system_stats()

    # 2. Processes
    processes_data = get_processes()
    grouped_apps = group_by_application(processes_data)

    # 3. Startup & Persistence Services
    startup_data = get_startup_items()
    match_startup_to_processes(startup_data, processes_data)

    # 4. Installed Software Inventory
    software_data = get_installed_software(scan_dirs=scan_dirs)

    # 5. File & Storage Hygiene
    files_data = get_file_cleanup_snapshot()

    # 6. Cross-reference into unified application inventory
    app_inventory = build_application_inventory(software_data, grouped_apps, startup_data)

    snapshot = {
        "timestamp": timestamp,
        "system": system_data,
        "processes": processes_data,
        "grouped_apps": grouped_apps,
        "applications": software_data,
        "application_inventory": app_inventory,
        "startup_entries": startup_data,
        "files": files_data
    }

    return snapshot


def save_snapshot_json(snapshot, file_path):
    """Saves the snapshot dictionary to a JSON file."""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, default=str)


def load_snapshot_json(file_path):
    """Loads a previously saved snapshot dictionary from JSON."""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)
