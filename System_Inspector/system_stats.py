import os
import subprocess

stats = os.statvfs("/")

blocks = stats.f_blocks
size = stats.f_frsize
total = blocks * size
free = stats.f_bavail * stats.f_frsize
used = total-free
percent = (used/total) * 100

print("Disk Used:", percent)