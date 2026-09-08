import subprocess
import os


def get_processes():
    output = subprocess.run(
        ["ps", "-axo", "pid,ppid,%cpu,%mem,comm"],
        capture_output=True,
        text=True
    )

    lines = output.stdout.splitlines()
    processes = []

    for line in lines[1:]:
        parts = line.strip().split(None, 4)

        process = {
            "pid": int(parts[0]),
            "ppid": int(parts[1]),
            "cpu": float(parts[2]),
            "mem": float(parts[3]),
            "command": parts[4]
        }

        processes.append(process)

    return processes

#top n cpu processes
def top_cpu(processes, n):
    return sorted(
        processes,
        key=lambda p: p["cpu"],
        reverse=True
    )[:n]

#top n mem processes
def top_mem(processes, n):
    return sorted(
        processes,
        key=lambda p: p["mem"],
        reverse=True
    )[:n]


def get_app_name(command):
    if ".app/" in command:
        before_app = command.split(".app/")[0]
        return before_app.split("/")[-1]

    return os.path.basename(command)


def group_by_application(processes):
    apps = {}

    for process in processes:
        app = get_app_name(process["command"])

        if app not in apps:
            apps[app] = {
                "name": app,
                "cpu": 0.0,
                "mem": 0.0,
                "count": 0,
                "command": process["command"],
                "type": get_app_type(process["command"])
            }

        apps[app]["cpu"] += process["cpu"]
        apps[app]["mem"] += process["mem"]
        apps[app]["count"] += 1

    return list(apps.values())

def get_app_type(command):
    if command.startswith("/System/"):
        return "system"

    if command.startswith("/usr/"):
        return "system"

    if ".app/" in command:
        return "user_app"

    return "other"


def top_apps_cpu(apps, n):
    return sorted(
        apps,
        key=lambda app: app["cpu"],
        reverse=True
    )[:n]


def top_apps_mem(apps, n):
    return sorted(
        apps,
        key=lambda app: app["mem"],
        reverse=True
    )[:n]

def display_processes(processes):
    print(f"{'PID':<8} {'PPID':<8} {'CPU%':<8} {'MEM%':<8} {'PROCESS'}")

    for p in processes:
        name = os.path.basename(p["command"])

        print(
            f"{p['pid']:<8} "
            f"{p['ppid']:<8} "
            f"{p['cpu']:<8.1f} "
            f"{p['mem']:<8.1f} "
            f"{name}"
        )

def display_apps(apps):
    print(
        f"{'APP':<30} "
        f"{'TYPE':<12} "
        f"{'CPU%':<10} "
        f"{'MEM%':<10} "
        f"{'PROCESSES'}"
    )

    for app in apps:
        print(
            f"{app['name']:<30} "
            f"{app['type']:<12} "
            f"{app['cpu']:<10.1f} "
            f"{app['mem']:<10.1f} "
            f"{app['count']}"
        )

def build_process_tree(processes):
    tree = {}

    for process in processes:
        parent = process["ppid"]

        if parent not in tree:
            tree[parent] = []

        tree[parent].append(process)

    return tree


def make_node(process, tree):
    return {
        "pid": process["pid"],
        "name": os.path.basename(process["command"]),
        "cpu": process["cpu"],
        "mem": process["mem"],
        "children": [
            make_node(child, tree)
            for child in tree.get(process["pid"], [])
        ]
    }

def create_process_tree(processes):
    tree = build_process_tree(processes)

    all_pids = {p["pid"] for p in processes}

    roots = [
        p for p in processes
        if p["ppid"] not in all_pids
    ]

    return [
        make_node(root, tree)
        for root in roots
    ]

def display_tree(node, indent=0):
    prefix = "  " * indent

    print(
        f"{prefix}{node['name']} "
        f"(PID {node['pid']}, "
        f"CPU {node['cpu']:.1f}%, "
        f"MEM {node['mem']:.1f}%)"
    )

    for child in node["children"]:
        display_tree(child, indent + 1)

def find_subtree(nodes, target_pid):
    for node in nodes:
        if node["pid"] == target_pid:
            return node

        result = find_subtree(node["children"], target_pid)

        if result is not None:
            return result

    return None

if __name__ == "__main__":
    processes = get_processes()

    cpu_processes = top_cpu(processes, 10)
    mem_processes = top_mem(processes, 10)

    apps = group_by_application(processes)

    cpu_apps = top_apps_cpu(apps, 10)
    mem_apps = top_apps_mem(apps, 10)

    print("\nTOP CPU PROCESSES")
    display_processes(cpu_processes)

    print("\nTOP MEMORY PROCESSES")
    display_processes(mem_processes)

    print("\nTOP APPLICATIONS BY CPU")
    display_apps(cpu_apps)

    print("\nTOP APPLICATIONS BY MEMORY")
    display_apps(mem_apps)

    print("\nPROCESS TREE: ")

    process_tree = create_process_tree(processes)

    for root in process_tree:
        display_tree(root)

    chrome_tree = find_subtree(process_tree, 30200)

    print("\nChrome Tree:\n")
    if chrome_tree:
        display_tree(chrome_tree)