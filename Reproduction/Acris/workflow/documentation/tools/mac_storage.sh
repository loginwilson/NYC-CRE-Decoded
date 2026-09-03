#!/bin/zsh
# Storage check for the office Mac: local disk + every attached volume, and what it
# means in pulling time at 1x40 (PDFs land at ~11 GB per hour, ~260 GB per day).
echo "== local disk =="
df -h / | tail -1 | awk '{printf "  %s  size %s  used %s  free %s (%s used)\n", $1, $2, $3, $4, $5}'
free_gb=$(df -g / | tail -1 | awk '{print $4}')
echo "  -> about $((free_gb / 11)) hours of 1x40 pulling before the local disk is full (slice needs 6.4 GB of that first)"
echo
echo "== attached volumes =="
found=0
for v in /Volumes/*; do
  [ -d "$v" ] || continue
  case "$v" in */Macintosh\ HD*) continue;; esac
  line=$(df -h "$v" 2>/dev/null | tail -1)
  [ -n "$line" ] || continue
  found=1
  fs=$(diskutil info "$v" 2>/dev/null | awk -F': *' '/File System Personality/ {print $2}')
  vfree=$(df -g "$v" | tail -1 | awk '{print $4}')
  echo "$line" | awk -v v="$v" -v fs="$fs" -v h=$((vfree / 11)) -v d=$((vfree / 260)) '{printf "  %-28s size %s  free %s  format %s  -> ~%s h / ~%s days of 1x40\n", v, $2, $4, fs, h, d}'
done
[ $found -eq 1 ] || echo "  (none - plug in the office drive; format it exFAT so Windows can read it at home)"
echo
echo "== python =="
python3 --version 2>/dev/null || echo "  python3 not found - install 3.12 (python.org or brew)"
python3 -c "import requests, PIL, img2pdf; print('  requests / Pillow / img2pdf: installed')" 2>/dev/null || echo "  missing packages -> python3 -m pip install requests pillow img2pdf"
