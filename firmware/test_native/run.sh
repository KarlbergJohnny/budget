#!/bin/sh
# Kompilerar och kör enhetstesterna för vagn_common på datorn.
set -e
cd "$(dirname "$0")/../.."
out="${TMPDIR:-/tmp}/vagn_test_common"
g++ -std=c++17 -Wall -Wextra -Werror -I firmware/lib/vagn_common/src \
  firmware/test_native/test_common.cpp -o "$out"
"$out"
