#!/usr/bin/env bash
# Smoke test of skills/proj-activate/SKILL.md: runs the commands of the skill with the real proj and real Lmod, in a scratch HOME,
# scratch registry and an `env -i` shell. Writes only inside the scratch folder, needs no sudo, takes a few seconds.
#   PROJ_BIN=/path/to/bin/proj bash skills/proj-activate/smoke.sh      (default: `proj` on PATH, else this checkout)
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
mkdir -p "$S/work/demo/$U" "$S/work/other"

# One clean shell per call: scratch HOME, no site configuration, nothing from this machine's proj.
run() {
  env -i HOME="$S" USER="$U" PATH=/usr/bin:/bin LC_ALL=C.UTF-8 TERM=dumb \
    PROJ_HOME="$S/.proj" PROJ_CACHE_HOME="$S/cache" PROJ_SITE_CONFIG="$S/no-site.toml" \
    bash --noprofile --norc -c "
      export LMOD_CMD=$LMOD_CMD_PATH LMOD_ALLOW_ROOT_USE=yes
      . $LMOD_INIT
      . $ROOT/shell/init.bash
      cd \$HOME
      $1" 2>&1
}
has() { grep -qF -- "$2" <<<"$1"; }

run "proj --version" | grep -q '^proj ' || { bad "proj --version"; exit 1; }
run "proj create demo --root $S/work/demo; proj create other --root $S/work/other" >/dev/null
RECORD_BEFORE=$(cat "$S/.proj/envs/demo/project.toml")

out=$(run "proj current; echo current-rc=\$?")
has "$out" "current-rc=1" && ok "proj current exits 1 when nothing is active" || bad "proj current when idle: $out"

out=$(run "proj activate demo; echo here=\$PWD; proj current; proj status | grep State; proj activate other; echo second-rc=\$?; proj deactivate; echo back=\$PWD; proj current; echo idle-rc=\$?")
has "$out" "here=$S/work/demo" && ok "activate lands in the project root" || bad "activate landing: $out"
has "$out" "State:        consistent" && ok "status says consistent" || bad "status: $out"
has "$out" "project 'demo' is already active; deactivate it first" && ok "a second project is refused while one is active" || bad "second activate: $out"
has "$out" "back=$S" && has "$out" "idle-rc=1" && ok "deactivate returns to the starting folder" || bad "deactivate: $out"

# Personal settings: written under the person's configuration, never in the project record.
out=$(run "proj config --env demo --mine 'behavior.activate_directory=\${project.root}/\${user}'; echo set-rc=\$?; proj config --env demo --mine behavior.activate_directory; proj activate demo >/dev/null; echo here=\$PWD; proj reload >/dev/null; echo reloaded=\$PWD; proj deactivate >/dev/null; echo back=\$PWD")
has "$out" "set-rc=0" && ok "--mine sets behavior.activate_directory" || bad "--mine set: $out"
has "$out" '${project.root}/${user}' && ok "--mine KEY prints the value" || bad "--mine print: $out"
has "$out" "here=$S/work/demo/$U" && ok "activation lands in <root>/<user>" || bad "activate_directory landing: $out"
has "$out" "reloaded=$S/work/demo/$U" && ok "proj reload keeps the folder" || bad "reload: $out"
has "$out" "back=$S" && ok "deactivate still returns to where you were" || bad "back: $out"
FILE="$S/.config/proj/projects/demo.toml"
[ -f "$FILE" ] && [ "$(stat -c %a "$FILE")" = 600 ] && ok "the setting is in ~/.config/proj/projects/demo.toml, mode 600" || bad "settings file missing or wrong mode: $(ls -l "$FILE" 2>&1)"
[ "$(cat "$S/.proj/envs/demo/project.toml")" = "$RECORD_BEFORE" ] && ok "the project record is unchanged" || bad "the record changed"
run "proj info --env demo" | grep -q "Your settings" && ok "proj info lists your settings" || bad "proj info lacks Your settings"

out=$(run "proj config --env demo --mine 'behavior.activate_directory=\${project.root}/nobody'; proj activate demo; echo missing=\$PWD; proj deactivate >/dev/null")
has "$out" "missing=$S/work/demo" && ok "a missing folder falls back to the root" || bad "missing folder: $out"
has "$out" "does not exist" && bad "the fallback was not silent without PROJ_VERBOSE: $out" || ok "the fallback is silent without PROJ_VERBOSE"
out=$(run "PROJ_VERBOSE=1 proj activate demo; proj deactivate >/dev/null")
has "$out" "nobody does not exist or cannot be entered; using the project root" && ok "PROJ_VERBOSE=1 says so" || bad "verbose line: $out"

out=$(run "proj config --env demo --mine 'behavior.activate_directory=work'; proj activate demo; echo rel=\$PWD; proj deactivate >/dev/null")
has "$out" "not an absolute path" && has "$out" "rel=$S/work/demo" && ok "a relative template says so and uses the root" || bad "relative template: $out"

out=$(run "proj config --env demo --mine behavior.change_directory=false; proj activate demo; echo stay=\$PWD; proj deactivate >/dev/null")
has "$out" "stay=$S" && ok "change_directory=false keeps the shell where it is" || bad "change_directory=false: $out"

run "proj config --env demo --mine --unset behavior.change_directory; proj config --env demo --mine --unset behavior.activate_directory" >/dev/null
[ ! -e "$FILE" ] && ok "--unset of the last key removes the file" || bad "--unset left $FILE"
out=$(run "proj config --env demo --mine --unset behavior.activate_directory; echo rc=\$?")
has "$out" "rc=2" && ok "unsetting what you never set is an error" || bad "unset of nothing: $out"
out=$(run "proj config --env demo --mine project.root=/x; echo rc=\$?")
has "$out" "is not a setting one person can change" && has "$out" "behavior.run_startup_hooks" && has "$out" "rc=2" && ok "other keys are refused with the list" || bad "refusal: $out"

out=$(run "proj config --env demo hooks.startup='[[\"sh\",\"-c\",\"cd /\"]]' >/dev/null; proj activate demo >/dev/null; echo hook=\$PWD; proj deactivate >/dev/null")
has "$out" "hook=$S/work/demo" && ok "a startup hook that runs cd / does not move the shell" || bad "hook cd: $out"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }
