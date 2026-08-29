# Statically Prints all system stats
import os
import subprocess
import time
stats = os.statvfs("/")

#gets blocks & size, and compares how much is used - how much is free
def disk_usage():
    blocks = stats.f_blocks
    size = stats.f_frsize
    total = blocks * size
    free = stats.f_bavail * stats.f_frsize
    used = total-free
    return (used/total) * 100

#pulls from vm_stat which gives memory info in pages, converts from pages to raw stats
def memory_usage():
    output = subprocess.run(
        ["vm_stat"],
        capture_output=True,
        text=True
    )
    lines = output.stdout.splitlines()
    stats = {}
    for line in lines[1:]:
        key, value = line.split(":", 1)
        value = value.strip().rstrip(".")
        stats[key] = int(value.strip())

    output = subprocess.run(
    ["sysctl", "-n", "hw.memsize"],
    capture_output=True,
    text=True
    )

    total_bytes = int(output.stdout.strip())
    page_size = os.sysconf("SC_PAGE_SIZE")
    free_bytes = stats["Pages free"] * page_size
    active_bytes = stats["Pages active"] * page_size
    inactive_bytes = stats["Pages inactive"] * page_size
    wired_bytes = stats["Pages wired down"] * page_size
    compressed_bytes = stats["Pages occupied by compressor"] * page_size
    gb = 1024 ** 3
    return (total_bytes/gb,free_bytes/gb, active_bytes/gb, inactive_bytes/gb, wired_bytes/gb, compressed_bytes/gb)   

def cpu_usage():
    output = subprocess.run(
        ["top", "-l", "1","-n","0"],
        capture_output=True,
        text=True
    )
    ret = ""
    for line in output.stdout.splitlines():
        if "CPU usage" in line:
            parts = line.split(",")
            idle_part = parts[2].strip()
            idle = float(idle_part.split("%")[0])
            return 100 - idle

def uptime():
    output = subprocess.run(
        ["sysctl", "-n", "kern.boottime"],
        capture_output=True,
        text=True
    )
    text = output.stdout
    sec_part = text.split("sec = ")[1]
    boot_time = int(sec_part.split(",")[0])
    uptime_seconds = time.time() - boot_time
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    return (days, hours, minutes)
    



usage = disk_usage()
print(f"Disk Usage: {usage:.1f}%")

result = memory_usage()
print(f"Total: {result[0]:.2f} GB")
print(f"Free: {result[1]:.2f} GB")
print(f"Active: {result[2]:.2f} GB")
print(f"Inactive: {result[3]:.2f} GB")
print(f"Wired: {result[4]:.2f} GB")
print(f"Compressed: {result[5]:.2f} GB")

print(f"CPU Usage: {cpu_usage():.2f}%")
days, hours, minutes = uptime()
print(f"Uptime: {days} days, {hours} hours, {minutes} minutes")