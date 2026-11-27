#!/usr/bin/env bash
# Reclaim disposable build artifacts only; never prune volumes or backups.
set -euo pipefail
available_kb=$(df -Pk / | awk 'NR==2 {print $4}')
if (( available_kb < 2097152 )); then
  printf 'Low disk space: reclaiming dangling images and old unused build cache.\n'
  docker image prune --force
  docker builder prune --force --filter until=24h
fi
available_kb=$(df -Pk / | awk 'NR==2 {print $4}')
df -h /
if (( available_kb < 1048576 )); then
  echo 'Less than 1 GiB available after conservative cleanup; deployment stopped.' >&2
  exit 1
fi
