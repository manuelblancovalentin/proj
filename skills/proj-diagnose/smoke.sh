#!/usr/bin/env bash
# Smoke test of skills/proj-diagnose/SKILL.md: runs its commands with the real proj and real Lmod, in a scratch HOME and registry,
# with an INVENTED module (gcc) in a scratch module folder. Writes only inside the scratch folder, needs no sudo, takes a few seconds.
#   PROJ_BIN=/path/to/bin/proj bash skills/proj-diagnose/smoke.sh      (default: `proj` on PATH, else this checkout)
set -u
S=$(mktemp -d)
trap 'chmod -R u+rwx "$S" 2>/dev/null; rm -rf "$S"' EXIT
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
mkdir -p "$S/work/demo" "$S/modules/gcc"
printf 'whatis("Category: compiler")\n' > "$S/modules/gcc/13.3.lua"

run() {
  env -i HOME="$S" USER="$U" PATH=/usr/bin:/bin LC_ALL=C.UTF-8 TERM=dumb PROJ_COLOR=never \
    PROJ_HOME="$S/.proj" PROJ_CACHE_HOME="$S/cache" PROJ_SITE_CONFIG="$S/no-site.toml" MODULEPATH="$S/modules" \
    bash --noprofile --norc -c "
      export LMOD_CMD=$LMOD_CMD_PATH LMOD_ALLOW_ROOT_USE=yes
      . $LMOD_INIT
      . $ROOT/shell/init.bash
      cd \$HOME
      $1" 2>&1
}
plain() { env -i HOME="$S" USER="$U" PATH=/usr/bin:/bin PROJ_COLOR=never PROJ_HOME="$S/.proj" PROJ_CACHE_HOME="$S/cache" PROJ_SITE_CONFIG="$S/no-site.toml" "$PROJ_BIN" "$@" 2>&1; }
has() { grep -qF -- "$2" <<<"$1"; }

run "proj --version" | grep -q '^proj ' || { bad "proj --version"; exit 1; }
run "proj create demo --root $S/work/demo; proj use --env demo gcc/13.3" >/dev/null

out=$(run "proj current; echo rc=\$?; proj status; echo rc=\$?")
has "$out" "rc=1" && has "$out" "No project active." && ok "nothing active: current exits 1, status says so" || bad "idle: $out"

out=$(run "proj info --env demo; proj list; proj env show demo; proj env list")
has "$out" "Project environment: demo" && has "$out" "demo  private" && has "$out" "Compiler modules     gcc/13.3" && ok "info and list read the record" || bad "info/list: $out"
has "$out" "Modulefile:" && has "$out" "project/demo  current" && ok "env show and env list (the generated module is current)" || bad "env: $out"
run "proj create fresh --root $S/work/demo" >/dev/null
has "$(run "proj env list")" "project/fresh  missing" && ok "a module not generated yet is 'missing'" || bad "env list missing"

out=$(run "proj activate demo >/dev/null; proj env list | grep '^demo'; proj status; echo rc=\$?; proj current")
has "$out" "current" && has "$out" "State:        consistent" && has "$out" "rc=0" && ok "an active project is consistent and its module is current" || bad "active: $out"

out=$(run "proj activate demo >/dev/null; module unload gcc/13.3 >/dev/null 2>&1; proj status; echo rc=\$?")
has "$out" "drift: missing modules: gcc/13.3" && has "$out" "rc=2" && ok "a module unloaded by hand is drift, exit 2" || bad "module drift: $out"
out=$(run "proj activate demo >/dev/null; module unload gcc/13.3 >/dev/null 2>&1; proj reload >/dev/null 2>&1; proj status | grep State; module list 2>&1 | grep -c gcc; proj deactivate")
has "$out" "State:        consistent" && has "$out" "deactivated" && ok "proj reload repairs it" || bad "reload repair: $out"
out=$(run "proj activate demo >/dev/null; module unload gcc/13.3 >/dev/null 2>&1; proj deactivate; echo rc=\$?; proj current; echo cur=\$?")
has "$out" "rc=0" && has "$out" "cur=1" && ok "deactivate still works with module drift" || bad "deactivate with drift: $out"

out=$(run "proj doctor; echo rc=\$?")
has "$out" "ok   shell adapter      loaded (bash)" && has "$out" "ok   Lmod" && has "$out" "ok   module function    available" && ok "doctor sees the adapter, Lmod and the module function" || bad "doctor: $out"
has "$out" "ok   metadata           2 project(s) valid" && ok "doctor counts valid records" || bad "doctor metadata: $out"
out=$(plain doctor; echo rc=$?)
has "$out" "FAIL shell adapter      not loaded; run \`proj init\`" && has "$out" "rc=1" && ok "outside the adapter doctor fails the first check and exits 1" || bad "plain doctor: $out"

out=$(plain activate demo); has "$out" "activate must run through the shell integration" && ok "bin/proj cannot activate; it points at proj init" || bad "plain activate: $out"
out=$(plain reload); has "$out" "reload must run through the shell integration" && ok "nor can it reload" || bad "plain reload: $out"
out=$(plain info --env nosuch); has "$out" "unknown project 'nosuch' (searched:" && ok "an unknown name says where it searched" || bad "unknown: $out"

chmod 666 "$S/.proj/envs/demo/project.toml"
out=$(plain list; plain info --env demo)
has "$out" "skipped invalid environment" && has "$out" "is world-writable; refusing to load it" && ok "a world-writable record is refused and named" || bad "world-writable: $out"
chmod 600 "$S/.proj/envs/demo/project.toml"
has "$(plain info --env demo)" "Project environment: demo" && ok "chmod go-w repairs it" || bad "chmod repair"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }
