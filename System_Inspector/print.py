import psutil

print("CPU:", psutil.cpu_percent(interval=1))
print("RAM:", psutil.virtual_memory().percent)
print("Disk:", psutil.disk_usage("/").percent)

for proc in psutil.process_iter(
    ["pid", "name", "memory_info", "exe"]
):
    try:
        print(proc.info)
    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied
    ):
        pass