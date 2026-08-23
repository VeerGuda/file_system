# Statically Prints all system stats
import os
import subprocess
stats = os.statvfs("/")

#gets blocks & size, and compares how much is used - how much is free
def cpu_usage():
    blocks = stats.f_blocks
    size = stats.f_frsize
    total = blocks * size
    free = stats.f_bavail * stats.f_frsize
    used = total-free
    return (used/total) * 100

#pulls from vm_stat which gives memory info in pages
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

    page_size = os.sysconf("SC_PAGE_SIZE")
    free_bytes = stats["Pages free"] * page_size
    active_bytes = stats["Pages active"] * page_size
    inactive_bytes = stats["Pages inactive"] * page_size
    wired_bytes = stats["Pages wired down"] * page_size
    compressed_bytes = stats["Pages occupied by compressor"] * page_size
    gb = 1024 ** 3
    return (free_bytes/gb, active_bytes/gb, inactive_bytes/gb, wired_bytes/gb, compressed_bytes/gb)   




usage = cpu_usage()
print(f"CPU Usage: {usage:.1f}%")

result = memory_usage()
print(result)