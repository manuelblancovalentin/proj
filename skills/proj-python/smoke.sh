#!/usr/bin/env bash
# Smoke test of skills/proj-python/SKILL.md: runs its commands with the real proj in a scratch HOME and a scratch shared registry,
# linking absolute prefixes (folders with a conda-meta folder, nothing is built or run). Name lookups use micromamba when it is installed.
# Writes only inside the scratch folder, needs no sudo. The activation failure check also needs Lmod and is skipped without it.
#   PROJ_BIN=/path/to/bin/proj bash skills/proj-python/smoke.sh      (default: `proj` on PATH, else this checkout)
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
U=$(id -un); G=$(id -gn)
MAMBA_DIR=$(dirname "$(command -v micromamba 2>/dev/null || echo /nonexistent/x)")
mkdir -p "$S/work/demo" "$S/work/mine" "$S/envs/base/conda-meta" "$S/envs/mine/conda-meta" "$S/shared"

proj() {  # PATH has micromamba only when it is installed
  env -i HOME="$S" USER="$U" PATH="/usr/bin:/bin:$MAMBA_DIR" LC_ALL=C.UTF-8 TERM=dumb PROJ_COLOR=never \
    PROJ_HOME="$S/.proj" PROJ_CACHE_HOME="$S/cache" PROJ_SITE_CONFIG="$S/no-site.toml" MAMBA_ROOT_PREFIX="$S/mamba" \
    PROJ_SHARED_REGISTRY="$S/shared" PROJ_GROUP="$G" "$PROJ_BIN" "$@" 2>&1
}
has() { grep -qF -- "$2" <<<"$1"; }

proj --version | grep -q '^proj ' || { bad "proj --version"; exit 1; }
proj create demo --shared --root "$S/work/demo" >/dev/null

out=$(proj set-python-env --env demo "$S/envs/base")
has "$out" "Linked micromamba environment" && ok "set-python-env links a prefix" || bad "set-python-env: $out"
out=$(proj info --env demo)
has "$out" "$S/envs/base" && has "$out" "Python manager       micromamba" && ok "proj info shows the manager and the environment" || bad "info: $out"
out=$(proj set-python-env --env demo "$S/envs/nosuch"); has "$out" "not a micromamba environment prefix" && ok "a prefix that is not an environment is refused" || bad "bad prefix: $out"

if command -v micromamba >/dev/null 2>&1; then
  has "$(proj python-env list)" "base" && ok "proj python-env list lists the manager's environments" || bad "python-env list"
  out=$(proj set-python-env --env demo nosuchenv-zz; echo rc=$?)
  has "$out" "unknown micromamba environment 'nosuchenv-zz'; run \`proj python-env list --manager micromamba\`" && has "$out" "rc=2" && ok "an unknown environment name is an error that says what to run" || bad "unknown name: $out"
else
  skip "micromamba is not installed: name lookups not checked"
fi
out=$(env -i HOME="$S" USER="$U" PATH=/usr/bin:/bin PROJ_HOME="$S/.proj" PROJ_CACHE_HOME="$S/cache" PROJ_SITE_CONFIG="$S/no-site.toml" PROJ_SHARED_REGISTRY="$S/shared" PROJ_GROUP="$G" "$PROJ_BIN" set-python-env --env demo somename 2>&1)
has "$out" "micromamba is not available" && ok "a manager that is not on PATH says so" || bad "no manager: $out"

# Your own environment with a shared project.
RECORD_BEFORE=$(cat "$S/shared/demo/project.toml")
out=$(proj set-python-env --env demo --mine "$S/envs/mine" --manager conda)
has "$out" "The shared environment is unchanged for everyone else" && ok "--mine says the shared environment is unchanged" || bad "--mine: $out"
FILE="$S/.config/proj/projects/demo.toml"
[ -f "$FILE" ] && [ "$(stat -c %a "$FILE")" = 600 ] && grep -q '^manager = "conda"' "$FILE" && grep -q "^environment = \"$S/envs/mine\"" "$FILE" && ok "your link is in ~/.config/proj/projects/demo.toml, mode 600" || bad "personal file: $(cat "$FILE" 2>&1)"
[ "$(cat "$S/shared/demo/project.toml")" = "$RECORD_BEFORE" ] && ok "the shared record is unchanged" || bad "the shared record changed"
out=$(proj info --env demo); has "$out" "Python override" && has "$out" "yours; the shared environment links $S/envs/base" && ok "info shows the override and the shared link" || bad "info override: $out"
out=$(proj status --env demo --json); has "$out" '"environment_source": "override"' && ok "status --json has environment_source: override" || bad "status json: $out"
out=$(proj env show demo); has "$out" "$S/envs/mine" && ok "the generated environment uses yours" || bad "env show: $out"
out=$(env -i HOME="$S/other" USER=other PATH=/usr/bin:/bin PROJ_HOME="$S/other/.proj" PROJ_CACHE_HOME="$S/other/cache" PROJ_SITE_CONFIG="$S/no-site.toml" PROJ_SHARED_REGISTRY="$S/shared" PROJ_GROUP="$G" "$PROJ_BIN" status --env demo --json 2>&1)
has "$out" '"environment_source": "shared"' && ok "another person's view is the shared one" || bad "other view: $out"
out=$(proj set-python-env --env demo --mine --unset)
has "$out" "It uses the shared environment's again" && [ ! -e "$FILE" ] && ok "--mine --unset removes your file" || bad "unset: $out"
out=$(proj set-python-env --env demo --mine --unset); has "$out" "you have no Python override for 'demo'" && ok "unset with nothing set is an error" || bad "unset twice: $out"
# The 0.9.0 location still counts.
mkdir -p "$S/.proj/overrides"
printf 'schema = 1\n\n[python]\nmanager = "micromamba"\nenvironment = "%s"\n' "$S/envs/mine" > "$S/.proj/overrides/demo.toml"
has "$(proj status --env demo --json)" '"environment_source": "override"' && ok "an older ~/.proj/overrides file is still read" || bad "legacy file ignored"
proj set-python-env --env demo --mine --unset >/dev/null
[ ! -e "$S/.proj/overrides/demo.toml" ] && ok "--unset removes the older file too" || bad "legacy file left"
mkdir -p "$S/.config/proj/projects"; printf 'schema = 1\n[python]\nmanager = "pip"\nenvironment = "x"\n' > "$FILE"; chmod 600 "$FILE"
out=$(proj status --env demo); has "$out" "python.manager must be one of" && ok "an invalid file of yours is reported, naming the problem" || bad "invalid file: $out"
rm -f "$FILE"
proj create own --root "$S/work/mine" >/dev/null
out=$(proj set-python-env --env own --mine "$S/envs/mine"); has "$out" "is your own environment: link its Python environment" && ok "--mine is refused for your own environment" || bad "--mine on own: $out"

# Dependency file and stamp.
printf 'name: base\n' > "$S/work/demo/environment.yml"
proj config --env demo python.spec='${project.root}/environment.yml' >/dev/null
has "$(proj status --env demo)" "never stamped" && ok "an unstamped dependency file says so" || bad "never stamped"
has "$(proj python-env stamp --env demo)" "Stamped demo: environment.yml" && has "$(proj status --env demo)" "unchanged since" && ok "stamp records the file; status says unchanged" || bad "stamp"
printf 'dependencies: [numpy]\n' >> "$S/work/demo/environment.yml"
out=$(proj status --env demo; echo rc=$?)
has "$out" "the environment is behind it" && has "$out" "rc=2" && ok "a changed file is drift, exit 2" || bad "behind: $out"
has "$(proj status --env demo --json)" '"state": "behind"' && ok "status --json has python.dependencies.state" || bad "json state"

# Activation needs the manager's shell hook; without it the activation fails and rolls back.
LMOD_INIT=${LMOD_INIT:-/usr/share/lmod/lmod/init/bash}; LMOD_CMD_PATH=${LMOD_CMD_PATH:-/usr/share/lmod/lmod/libexec/lmod}
if [ -r "$LMOD_INIT" ] && [ -x "$LMOD_CMD_PATH" ] && [ -r "$ROOT/shell/init.bash" ]; then
  out=$(env -i HOME="$S" USER="$U" PATH=/usr/bin:/bin LC_ALL=C.UTF-8 TERM=dumb PROJ_HOME="$S/.proj" PROJ_CACHE_HOME="$S/cache" \
    PROJ_SITE_CONFIG="$S/no-site.toml" PROJ_SHARED_REGISTRY="$S/shared" PROJ_GROUP="$G" bash --noprofile --norc -c "
    export LMOD_CMD=$LMOD_CMD_PATH LMOD_ALLOW_ROOT_USE=yes; . $LMOD_INIT; . $ROOT/shell/init.bash
    proj activate demo; echo rc=\$?; echo active=\${PROJ_ACTIVE:-none}" 2>&1)
  has "$out" "shell integration is unavailable; initialize it in your startup file" && has "$out" "active=none" && ok "no manager hook: activation fails, says why, and leaves nothing active" || bad "activation without hook: $out"
else
  skip "Lmod is not installed: the activation failure was not checked"
fi

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }
