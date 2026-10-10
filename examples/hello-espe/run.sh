#!/usr/bin/env bash
# Hello ESPE. Always prints the rational schedule. If xretractor is available,
# runs query.rql offline and checks the stored records against that schedule.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${script_dir}"

python3 oracle.py

xretractor_bin() {
  if [ -n "${XRETRACTOR:-}" ] && [ -x "${XRETRACTOR}" ]; then
    printf '%s\n' "${XRETRACTOR}"
    return 0
  fi
  if command -v xretractor >/dev/null 2>&1; then
    command -v xretractor
    return 0
  fi
  local root candidate
  root=$(cd "${script_dir}/../.." && pwd)
  for candidate in \
    "${root}/build/Debug/src/retractor/xretractor" \
    "${root}/build/Release/src/retractor/xretractor"
  do
    if [ -x "${candidate}" ]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

if ! bin=$(xretractor_bin); then
  echo "engine: skipped (xretractor not found)"
  echo "After install, re-run examples/hello-espe/run.sh"
  echo "  scripts/buildrdb.sh toolchain"
  echo "  scripts/buildrdb.sh conan ninja debug"
  echo "  ninja -C build/Debug install"
  exit 0
fi

echo "engine: ${bin}"
rm -f bus fused wheel_back imu_back wheel imu STREAM_* ./*.desc ./*.meta ./*.shadow
"${bin}" query.rql --name hello-espe -c
"${bin}" query.rql --name hello-espe -r -k -f -u
python3 oracle.py --check-engine
