#!/usr/bin/env bash
# Smoke test of skills/proj-modules/SKILL.md: runs its commands with the real proj and real Lmod against INVENTED modules in a scratch
# module folder (gcc, cmake, simtool, pdk-demo, suite-team, toola, toolb), a scratch HOME and registries. Writes only inside the scratch folder.
#   PROJ_BIN=/path/to/bin/proj bash skills/proj-modules/smoke.sh      (default: `proj` on PATH, else this checkout)
set -u
S=$(mktemp -d)
trap 'rm -rf "$S"' EXIT
fail=0
ok()   { printf 'ok   %s\n' "$1"; }
bad()  { printf 'FAIL %s\n' "$1"; fail=1; }
skip() { printf 'skip %s\n' "$1"; }

PROJ_BIN=${PROJ_BIN:-$(command -v proj 2>/dev/null || true)}
[ -x "${PROJ_BIN:-}" ] || PROJ_BIN=$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd)/bin/proj
[ -x "$PROJ_BIN" ] || { skip "proj is not installed on this machine"; exit 0; }
ROOT=$(cd "$(dirname "$(readlink -f "$PROJ_BIN")")/.." && pwd)
LMOD_INIT=${LMOD_INIT:-/usr/share/lmod/lmod/init/bash}
LMOD_CMD_PATH=${LMOD_CMD_PATH:-/usr/share/lmod/lmod/libexec/lmod}
[ -r "$LMOD_INIT" ] && [ -x "$LMOD_CMD_PATH" ] || { skip "Lmod is not installed on this machine"; exit 0; }
[ -r "$ROOT/shell/init.bash" ] || { bad "no shell adapter at $ROOT/shell/init.bash"; exit 1; }

U=$(id -un)
mkdir -p "$S/work/demo" "$S/modules" "$S/bin-a" "$S/bin-b" "$S/shared"
module() {  # module <name/version> <category> [bin folder providing mytool]
  mkdir -p "$S/modules/${1%%/*}"
  { printf 'whatis("Category: %s")\n' "$2"; [ -n "${3:-}" ] && printf 'prepend_path("PATH", "%s")\n' "$3"; } > "$S/modules/$1.lua"
}
module gcc/12.2 compiler;        module gcc/13.3 compiler
module cmake/3.30 toolchain;     module simtool/20.1 application;  module simtool/21.1 application
module pdk-demo/1.0 application; module suite-team/5 application
module x/1 application; module pdk-x/1 application; module suite-x/1 application
module toola/1.0 toolchain "$S/bin-a"; module toolb/1.0 application "$S/bin-b"
for x in a b; do printf '#!/bin/sh\necho tool-%s\n' "$x" > "$S/bin-$x/mytool"; chmod +x "$S/bin-$x/mytool"; done

run() {
  env -i HOME="$S" USER="$U" PATH=/usr/bin:/bin LC_ALL=C.UTF-8 TERM=dumb PROJ_COLOR=never \
    PROJ_HOME="$S/.proj" PROJ_CACHE_HOME="$S/cache" PROJ_SITE_CONFIG="$S/no-site.toml" \
    PROJ_SHARED_REGISTRY="$S/shared" PROJ_GROUP="$(id -gn)" MODULEPATH="$S/modules" \
    bash --noprofile --norc -c "
      export LMOD_CMD=$LMOD_CMD_PATH LMOD_ALLOW_ROOT_USE=yes
      . $LMOD_INIT
      . $ROOT/shell/init.bash
      cd \$HOME
      $1" 2>&1
}
has() { grep -qF -- "$2" <<<"$1"; }

run "proj --version" | grep -q '^proj ' || { bad "proj --version"; exit 1; }
run "proj create demo --root $S/work/demo" >/dev/null

out=$(run "proj avail")
has "$out" "Compilers (1)" && has "$out" "Toolchains (2)" && has "$out" "Applications (7)" && ok "proj avail groups the modules by category" || bad "proj avail: $out"
has "$out" "13.3*" && ok "the default version is marked with *" || bad "default marker: $out"
out=$(run "proj avail compiler")
has "$out" "gcc" && ! has "$out" "simtool" && ok "proj avail compiler lists only that category" || bad "proj avail compiler: $out"
out=$(run "proj use --list")
has "$out" "You can use" && has "$out" "cmake" && ok "proj use --list shows what you may add" || bad "proj use --list: $out"
out=$(run "proj catalog")
has "$out" '"schema": 1' && has "$out" '"allowed": true' && ok "proj catalog is JSON with allowed" || bad "proj catalog: $out"

out=$(run "proj use --env demo gcc cmake simtool/20.1; proj use --env demo")
has "$out" "Added simtool/20.1 (application) to demo" && has "$out" "demo uses 3 modules" && ok "proj use adds by name and by name/version" || bad "proj use: $out"
has "$out" "It takes effect the next time demo is activated" && ok "an inactive project is not reloaded" || bad "inactive wording: $out"
out=$(run "proj use --env demo gcc/12.2")
has "$out" "Replaced gcc with gcc/12.2 (same module)" && ok "the same module is replaced, not duplicated" || bad "replace: $out"
out=$(run "proj use --env demo team pdk-demo; proj use --env demo")
has "$out" "suite-team" && has "$out" "pdk-demo" && ok "a bare name finds suite-<name>; a full name works" || bad "suite/pdk lookup: $out"
out=$(run "proj use --env demo zzz; echo rc=\$?")
has "$out" "no module matches 'zzz'" && has "$out" "rc=2" && ok "an unknown name is an error, not a guess" || bad "unknown name: $out"
out=$(run "proj unuse --env demo cmake; proj use --env demo")
has "$out" "Removed cmake from demo" && ! grep -q "^cmake " <<<"$out" && ok "proj unuse removes it" || bad "unuse: $out"

# The low-level form edits the list only; an active project needs proj reload.
run "proj unuse --env demo gcc simtool suite-team pdk-demo" >/dev/null
out=$(run "proj module add toolchain toola/1.0 --env demo; proj module add application toolb/1.0 --env demo; proj module list application --env demo")
has "$out" "Added 'toolb/1.0' to 'demo' application modules" && has "$out" "toolb/1.0" && ok "proj module add and list" || bad "module add: $out"
out=$(run "proj activate demo >/dev/null; mytool; proj module add compiler gcc/13.3 --env demo >/dev/null; echo before=\$(module list 2>&1 | grep -c gcc); proj reload >/dev/null; echo after=\$(module list 2>&1 | grep -c gcc); proj deactivate >/dev/null")
has "$out" "tool-b" && ok "the application's command beats the toolchain's on PATH (loaded last, found first)" || bad "PATH order: $out"
has "$out" "before=0" && has "$out" "after=1" && ok "proj module add does not reload; proj reload applies it" || bad "reload: $out"
out=$(run "proj use --env demo gcc/12.2 >/dev/null; proj activate demo >/dev/null; proj use --env demo gcc/13.3; proj deactivate >/dev/null")
has "$out" "updated in this shell" && ok "proj use reloads the active project by itself" || bad "use reload: $out"
out=$(run "proj module remove application toolb/1.0 --env demo; proj module remove application toolb/1.0 --env demo; echo rc=\$?")
has "$out" "Removed 'toolb/1.0'" && has "$out" "rc=2" && ok "proj module remove, and removing what is not there is an error" || bad "module remove: $out"
out=$(run "proj use --env demo project/x; echo rc=\$?")
has "$out" "no module matches 'project'" && has "$out" "rc=2" && ok "the project/ namespace cannot be added" || bad "project/ namespace: $out"
out=$(run "proj use --env demo x; echo rc=\$?")
has "$out" "'x' matches several modules (x, pdk-x, suite-x)" && has "$out" "rc=2" && ok "x, pdk-x and suite-x together are ambiguous, never a guess" || bad "ambiguity: $out"

# A private environment of the same name hides the shared one for the person who made it.
run "proj create twin --shared --root $S/work/demo" >/dev/null
mkdir -p "$S/.proj/envs/twin"; sed 's/^description = .*/description = "private copy"/' "$S/shared/twin/project.toml" > "$S/.proj/envs/twin/project.toml"
out=$(run "proj info --env twin | grep -E '^(Description|Scope)'")
has "$out" "private" && ok "a private environment of the same name wins; info says Scope: private" || bad "shadowing: $out"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }
