#!/usr/bin/env bash
# Smoke test of skills/proj-create-share/SKILL.md: runs its commands with the real proj in a scratch HOME with a scratch shared
# registry (your own primary group as the registry group). Writes only inside the scratch folder, needs no sudo and no Lmod.
#   PROJ_BIN=/path/to/bin/proj bash skills/proj-create-share/smoke.sh      (default: `proj` on PATH, else this checkout)
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
U=$(id -un); G=$(id -gn)
mkdir -p "$S/work/demo" "$S/work/other" "$S/shared"

proj() {
  env -i HOME="$S" USER="$U" PATH=/usr/bin:/bin LC_ALL=C.UTF-8 TERM=dumb PROJ_COLOR=never \
    PROJ_HOME="$S/.proj" PROJ_CACHE_HOME="$S/cache" PROJ_SITE_CONFIG="$S/no-site.toml" \
    PROJ_SHARED_REGISTRY="$S/shared" PROJ_GROUP="$G" "$PROJ_BIN" "$@" 2>&1
}
has() { grep -qF -- "$2" <<<"$1"; }

proj --version | grep -q '^proj ' || { bad "proj --version"; exit 1; }

out=$(proj create demo --root "$S/work/demo")
[ -f "$S/.proj/envs/demo/project.toml" ] && ok "a private environment is one file in ~/.proj/envs" || bad "create: $out"
out=$(proj list)
has "$out" "private" && ok "proj list shows scope private" || bad "list: $out"
out=$(proj create demo --root "$S/work/demo"); rc=$?
has "$out" "already exists" && ok "a name that exists is refused" || bad "duplicate create: $out"

out=$(proj create demo2 --from demo --root "$S/work/other")
has "$out" "successfully created" && ok "--from makes a copy under a new name" || bad "--from: $out"
proj create withuse --root "$S/work/other" --use gcc >/dev/null 2>&1; true

out=$(proj share demo)
has "$out" "now shared with group $G" && has "$out" "run its hooks and aliases as themselves" && ok "share moves it and says hooks run as members" || bad "share: $out"
[ -f "$S/shared/demo/project.toml" ] && [ ! -e "$S/.proj/envs/demo" ] && ok "the private copy is gone after share" || bad "share left a copy"
out=$(proj list)
has "$out" "shared" && has "$out" "$U:$G" && ok "proj list shows shared and owner user:group" || bad "list after share: $out"
out=$(proj create demo --root "$S/work/demo"); has "$out" "already exists" && ok "a name in the shared registry is refused too" || bad "shared duplicate: $out"

out=$(proj access demo)
has "$out" "only its creator can change it" && ok "default level: owner-only" || bad "access: $out"
mode() { stat -c '%a' "$1"; }
proj access demo --group-writable >/dev/null
[ "$(mode "$S/shared/demo")" = 2775 ] && [ "$(mode "$S/shared/demo/project.toml")" = 664 ] && ok "--group-writable is 2775/664" || bad "group-writable modes: $(mode "$S/shared/demo") $(mode "$S/shared/demo/project.toml")"
proj access demo --private >/dev/null
[ "$(mode "$S/shared/demo")" = 2770 ] && [ "$(mode "$S/shared/demo/project.toml")" = 660 ] && ok "--private is 2770/660" || bad "private modes"
proj access demo --owner-only >/dev/null
[ "$(mode "$S/shared/demo")" = 2755 ] && [ "$(mode "$S/shared/demo/project.toml")" = 644 ] && ok "--owner-only is 2755/644" || bad "owner-only modes"
out=$(proj access demo2); has "$out" "only a shared environment has an access level" && ok "a private environment has no access level" || bad "access on private: $out"

out=$(proj create fromstart --shared --root "$S/work/other")
has "$out" "Scope: shared" && ok "proj create --shared creates it shared from the start" || bad "create --shared: $out"

out=$(proj unshare demo)
has "$out" "is private again" && [ -f "$S/.proj/envs/demo/project.toml" ] && [ ! -e "$S/shared/demo" ] && ok "unshare brings it back to ~/.proj/envs" || bad "unshare: $out"

out=$(proj remove demo2 </dev/null); rc=$?
[ "$rc" != 0 ] && [ -f "$S/.proj/envs/demo2/project.toml" ] && ok "remove without a terminal needs --yes and changed nothing" || bad "remove without --yes: rc=$rc $out"
out=$(proj remove demo2 --yes)
has "$out" "Removed environment 'demo2'" && [ -d "$S/work/other" ] && [ ! -e "$S/.proj/envs/demo2/project.toml" ] && ok "remove --yes deletes the record and keeps the project folder" || bad "remove: $out"

out=$(proj create bad --shared --group nosuchgroup-zz --root "$S/work/other"); rc=$?
[ "$rc" != 0 ] && ok "--group of a group you are not in is refused" || bad "--group: rc=$rc $out"
out=$(env -i HOME="$S" PATH=/usr/bin:/bin PROJ_HOME="$S/.proj" PROJ_CACHE_HOME="$S/cache" PROJ_SITE_CONFIG="$S/no-site.toml" "$PROJ_BIN" share demo 2>&1)
has "$out" "no shared registry is configured" && ok "without a shared registry configured, share says so" || bad "no registry: $out"
has "$(proj create bad2 --shared --group nosuchgroup-zz --root "$S/work/other")" "group 'nosuchgroup-zz' does not exist" && ok "--group of an unknown group says so" || bad "--group message"

[ "$fail" = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }
