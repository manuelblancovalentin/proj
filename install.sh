#!/bin/sh
# Installer for proj, a project environment manager built on Lmod.
#
#   sh install.sh [options]                      from a checkout or release
#   curl -fsSL <raw-url>/install.sh | sh         downloads the sources
#   curl -fsSL <raw-url>/install.sh | sh -s -- --yes --prefix ~/opt/proj
#
# Run `sh install.sh --help` for every option. Prompts read from the terminal,
# so piping the script into sh stays interactive.
set -eu

PROJ_REPO=${PROJ_REPO:-manuelblancovalentin/proj}
PROJ_REF=${PROJ_REF:-master}
INSTALLED_ITEMS='bin proj shell share templates docs README.md'
MARKER=.proj-install

prefix=
mode=
group=
registry=
shared_registry=
source_dir=
init=
shell_name=
system_init=
install_deps=
python_manager=
batch=0
tmp=
stage=
created_prefix=
installed=0

usage() {
  cat <<EOF
Usage: install.sh [options]

Installs proj, then optionally initializes your shell. Without options every
choice is asked interactively with a default shown in brackets.

  --prefix DIR            installation directory (default: /opt/proj, or
                          ~/.local/opt/proj when /opt is not writable)
  --mode private|shared   private: only you; shared: members of a group
                          (default: shared when run as root, else private)
  --group NAME            group for shared mode (default: proj)
  --registry DIR          private environment registry (default: ~/.proj/envs)
  --shared-registry DIR   shared environment registry (default: PREFIX/envs)
  --python-manager NAME   default Python environment manager: micromamba,
                          conda, or mamba (default: the first one found);
                          on an existing installation, updates the setting
  --shell LIST            shells to initialize: zsh, bash, or zsh,bash
                          (default: ask for each installed shell, suggesting
                          yes for the current and login shells)
  --init / --no-init      add proj to your shell startup file
  --system-init / --no-system-init
                          as root, add proj to the system-wide startup files
  --install-deps / --no-install-deps
                          offer to install missing Lmod and micromamba
  --source DIR            install from this source tree instead of downloading
  --ref REF               branch or tag to download (default: $PROJ_REF)
  -y, --yes               accept defaults; never prompt
  -h, --help              show this help

Environment: PROJ_REPO (default $PROJ_REPO), PROJ_REF.
EOF
}

say() { printf '%s\n' "$*"; }
note() { printf '  - %s\n' "$*"; }
warn() { printf 'proj-install: warning: %s\n' "$*" >&2; }
die() { printf 'proj-install: error: %s\n' "$*" >&2; exit 1; }

# Remove temporary files and, unless the installation finished, a prefix that
# this run created, so an interrupted or failed run can simply start over.
cleanup() {
  if [ -n "$tmp" ]; then rm -rf -- "$tmp"; fi
  if [ -n "$stage" ]; then rm -rf -- "$stage"; fi
  if [ "$installed" = 0 ] && [ -n "$created_prefix" ]; then
    rm -rf -- "$created_prefix"
  fi
}

# A trapped INT would otherwise resume the script after the handler, which
# turned Ctrl+C at a prompt into "accept the default". Exit explicitly.
abort() {
  trap - EXIT HUP INT TERM
  cleanup
  if [ "$installed" = 1 ]; then
    printf '\nproj-install: aborted; proj is installed in %s, rerun to finish setup\n' \
      "$prefix" >&2
  else
    printf '\nproj-install: aborted; nothing was installed\n' >&2
  fi
  exit 130
}
trap cleanup EXIT
trap abort HUP INT TERM

interactive() {
  [ "$batch" = 0 ] && (: </dev/tty) 2>/dev/null
}

# ask VARIABLE QUESTION DEFAULT
ask() {
  _answer=
  if interactive; then
    printf '%s [%s]: ' "$2" "$3" >/dev/tty
    IFS= read -r _answer </dev/tty || _answer=
  fi
  [ -n "$_answer" ] || _answer=$3
  eval "$1=\$_answer"
}

# confirm QUESTION DEFAULT(yes|no)
confirm() {
  ask _reply "$1 (yes/no)" "$2"
  case $_reply in
    [Yy]*) return 0 ;;
    *) return 1 ;;
  esac
}

expand_home() {
  case $1 in
    '~') printf '%s\n' "$HOME" ;;
    '~/'*) printf '%s/%s\n' "$HOME" "${1#\~/}" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

toml_string() {
  printf '"%s"' "$(printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g')"
}

is_root() { [ "$(id -u)" = 0 ]; }

sudo_prefix() {
  if is_root; then
    printf '\n'
  elif command -v sudo >/dev/null 2>&1; then
    printf 'sudo \n'
  else
    return 1
  fi
}

lmod_present() {
  [ -n "${LMOD_CMD-}" ] && [ -x "$LMOD_CMD" ] && return 0
  command -v lmod >/dev/null 2>&1 && return 0
  for candidate in /usr/share/lmod/lmod/libexec/lmod \
    /opt/apps/lmod/lmod/libexec/lmod /usr/local/lmod/lmod/libexec/lmod; do
    [ -x "$candidate" ] && return 0
  done
  return 1
}

lmod_package_command() {
  if command -v apt-get >/dev/null 2>&1; then
    printf 'apt-get install -y lmod\n'
  elif command -v dnf >/dev/null 2>&1; then
    printf 'dnf install -y Lmod\n'
  elif command -v yum >/dev/null 2>&1; then
    printf 'yum install -y Lmod\n'
  elif command -v zypper >/dev/null 2>&1; then
    printf 'zypper install -y lua-lmod\n'
  else
    return 1
  fi
}

download() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$1" -O "$2"
  else
    die "curl or wget is required to download $1"
  fi
}

while [ $# -gt 0 ]; do
  case $1 in
    --prefix) prefix=${2?--prefix needs a directory}; shift ;;
    --mode) mode=${2?--mode needs private or shared}; shift ;;
    --group) group=${2?--group needs a name}; shift ;;
    --registry) registry=${2?--registry needs a directory}; shift ;;
    --shared-registry) shared_registry=${2?--shared-registry needs a directory}; shift ;;
    --shell) shell_name=${2?--shell needs zsh or bash}; shift ;;
    --source) source_dir=${2?--source needs a directory}; shift ;;
    --ref) PROJ_REF=${2?--ref needs a branch or tag}; shift ;;
    --init) init=yes ;;
    --no-init) init=no ;;
    --system-init) system_init=yes ;;
    --no-system-init) system_init=no ;;
    --install-deps) install_deps=yes ;;
    --python-manager) python_manager=${2?--python-manager needs a name}; shift ;;
    --no-install-deps) install_deps=no ;;
    -y|--yes) batch=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown option: $1" ;;
  esac
  shift
done

# --- Sources -----------------------------------------------------------------

if [ -z "$source_dir" ]; then
  script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd) || script_dir=
  if [ -n "$script_dir" ] && [ -f "$script_dir/proj/cli.py" ]; then
    source_dir=$script_dir
  else
    tmp=$(mktemp -d "${TMPDIR:-/tmp}/proj-install.XXXXXX")
    url="https://github.com/$PROJ_REPO/archive/$PROJ_REF.tar.gz"
    say "Downloading proj from $url"
    download "$url" "$tmp/proj.tar.gz"
    mkdir "$tmp/src"
    tar -xzf "$tmp/proj.tar.gz" -C "$tmp/src" --strip-components=1
    source_dir=$tmp/src
  fi
fi
source_dir=$(CDPATH= cd -- "$source_dir" && pwd -P)
[ -f "$source_dir/proj/cli.py" ] || die "not a proj source tree: $source_dir"
version=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$source_dir/proj/__init__.py")
say "Installing proj $version"

# --- Requirements ------------------------------------------------------------

# proj prefers the system interpreter so project environments cannot replace
# its runtime. Where that one cannot read TOML (Python before 3.11 without
# tomli), record the python3 found on PATH instead.
reads_toml() {
  "$1" -c '
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli
sys.exit(sys.version_info < (3, 9))
' 2>/dev/null
}
python=
for candidate in /usr/bin/python3 "$(command -v python3 2>/dev/null || true)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ] && reads_toml "$candidate"; then
    python=$candidate
    break
  fi
done
[ -n "$python" ] ||
  die "proj needs Python 3.11+, or Python 3.9+ with tomli (python3 -m pip install tomli)"
if [ "$python" != /usr/bin/python3 ]; then
  warn "/usr/bin/python3 cannot read TOML; proj will run with $python"
fi

# Shells to initialize. Many people run a shell other than their login shell
# (for example zsh started from bash on a cluster), so consider the shell that
# launched this installer, the login shell, and every other supported shell
# installed here. --shell zsh,bash restricts the choice.
login_shell=${SHELL##*/}
parent_shell=$(ps -o comm= -p "$PPID" 2>/dev/null || true)
parent_shell=${parent_shell#-}
parent_shell=${parent_shell##*/}
shells=
if [ -n "$shell_name" ]; then
  candidates=$(printf '%s' "$shell_name" | tr ',' ' ')
else
  candidates="$parent_shell $login_shell zsh bash"
fi
for candidate in $candidates; do
  case $candidate in
    zsh|bash) ;;
    *)
      [ -n "$shell_name" ] && die "unsupported shell '$candidate'; use zsh and/or bash"
      continue
      ;;
  esac
  command -v "$candidate" >/dev/null 2>&1 || continue
  case " $shells " in
    *" $candidate "*) ;;
    *) shells="$shells $candidate" ;;
  esac
done

rc_for() {
  case $1 in
    zsh) printf '%s/.zshrc\n' "${ZDOTDIR:-$HOME}" ;;
    bash) printf '%s/.bashrc\n' "$HOME" ;;
  esac
}

if ! lmod_present; then
  warn "Lmod was not found; proj needs it to activate environments"
  if command=$(lmod_package_command) && sudo=$(sudo_prefix); then
    if [ "$install_deps" = yes ] ||
       { [ -z "$install_deps" ] && confirm "Install Lmod now with: ${sudo}$command" no; }; then
      # shellcheck disable=SC2086
      ${sudo}$command || warn "Lmod installation failed; install it manually"
    else
      note "Install it later with: ${sudo}$command"
    fi
  else
    note "Ask your administrator to install Lmod."
  fi
fi

case $python_manager in
  ''|micromamba|conda|mamba) ;;
  *) die "--python-manager must be micromamba, conda, or mamba, not '$python_manager'" ;;
esac

# The first conda-family manager found here, in order of preference.
detect_python_manager() {
  if command -v micromamba >/dev/null 2>&1; then
    printf 'micromamba\n'
  elif [ -n "${CONDA_EXE-}" ] || command -v conda >/dev/null 2>&1; then
    printf 'conda\n'
  elif command -v mamba >/dev/null 2>&1; then
    printf 'mamba\n'
  else
    return 1
  fi
}

detected_manager=$(detect_python_manager) || detected_manager=
if [ -z "$detected_manager" ] && [ -z "$python_manager" ]; then
  say "No micromamba, conda, or mamba was found (optional; needed only for Python environments)."
  is_root && note "sudo hides your own PATH; an existing conda can be chosen below."
  if is_root; then
    note "Each user can install it with: \"\${SHELL}\" <(curl -L micro.mamba.pm/install.sh)"
  elif [ "$install_deps" = yes ] ||
       { [ -z "$install_deps" ] && interactive &&
         confirm "Install micromamba for $(id -un) with its official installer" no; }; then
    [ -n "$tmp" ] || tmp=$(mktemp -d "${TMPDIR:-/tmp}/proj-install.XXXXXX")
    download https://micro.mamba.pm/install.sh "$tmp/micromamba-install.sh"
    if interactive; then
      "${SHELL:-bash}" "$tmp/micromamba-install.sh" </dev/tty ||
        warn "micromamba installation failed"
    else
      "${SHELL:-bash}" "$tmp/micromamba-install.sh" </dev/null ||
        warn "micromamba installation failed"
    fi
  fi
fi

# --- Mode ---------------------------------------------------------------------

if [ -z "$mode" ]; then
  if is_root; then default_mode=shared; else default_mode=private; fi
  say ''
  say 'private: only you can see and use your environments.'
  say 'shared:  members of a group can activate everyone'\''s shared environments;'
  say '         each environment is changed only by its creator unless created'
  say '         with --group-writable. Private environments remain available.'
  ask mode 'Installation mode (private/shared)' "$default_mode"
fi
case $mode in
  private|shared) ;;
  *) die "mode must be private or shared, not '$mode'" ;;
esac

if [ "$mode" = shared ]; then
  [ -n "$group" ] || ask group 'Group whose members share environments' proj
  if ! getent group "$group" >/dev/null 2>&1; then
    if is_root && confirm "Group '$group' does not exist. Create it" yes; then
      groupadd "$group"
    else
      die "group '$group' does not exist; an administrator can run: sudo groupadd $group"
    fi
  fi
  if ! is_root && ! id -nG | tr ' ' '\n' | grep -qx "$group"; then
    warn "you are not in group '$group'; ask for: sudo usermod -aG $group $(id -un)"
  fi
fi

# --- Location -----------------------------------------------------------------

if [ -z "$prefix" ]; then
  default_prefix=/opt/proj
  if [ "$mode" = private ] && ! is_root && ! [ -w /opt ] && ! [ -w /opt/proj ]; then
    default_prefix=$HOME/.local/opt/proj
  fi
fi

while :; do
  if [ -z "$prefix" ]; then
    ask prefix 'Install proj into' "$default_prefix"
  fi
  prefix=$(expand_home "$prefix")
  problem=
  new_prefix=
  case $prefix in
    /*)
      # Remember the top-most directory this run creates, so cleanup also
      # removes parents that mkdir -p adds.
      probe=$prefix
      while [ -n "$probe" ] && ! [ -e "$probe" ]; do
        new_prefix=$probe
        probe=${probe%/*}
      done
      ;;
    *) problem="the installation directory must be an absolute path" ;;
  esac
  if [ -z "$problem" ] && [ -e "$prefix" ]; then
    if [ "$(CDPATH= cd -- "$prefix" 2>/dev/null && pwd -P)" = "$source_dir" ] ||
       [ -e "$prefix/.git" ]; then
      problem="$prefix is a source checkout; choose another directory"
    elif ! [ -f "$prefix/$MARKER" ] && [ -n "$(ls -A "$prefix" 2>/dev/null)" ]; then
      problem="$prefix exists and is not a proj installation"
    fi
  fi
  if [ -z "$problem" ] && ! mkdir -p "$prefix" 2>/dev/null; then
    problem="cannot create $prefix (try another directory, or run with sudo)"
  fi
  if [ -z "$problem" ] && ! [ -w "$prefix" ]; then
    problem="$prefix is not writable"
  fi
  [ -z "$problem" ] && break
  if [ -n "$new_prefix" ] && [ -d "$new_prefix" ]; then rm -rf -- "$new_prefix"; fi
  interactive || die "$problem"
  warn "$problem"
  prefix=
done
prefix=$(CDPATH= cd -- "$prefix" && pwd -P)
[ -n "$new_prefix" ] && created_prefix=$new_prefix

upgrade=0
[ -f "$prefix/$MARKER" ] && upgrade=1
config_file=$prefix/etc/config.toml
write_config=1
if [ -f "$config_file" ]; then
  write_config=0
  say "Keeping the existing configuration at $config_file"
fi

if [ "$write_config" = 1 ]; then
  if [ "$mode" = private ] && [ -z "$registry" ]; then
    ask registry 'Store your environments in' '~/.proj/envs'
  fi
  [ -n "$registry" ] || registry='~/.proj/envs'
  # A leading ~ stays literal so each user's own home directory is used.
  case $registry in
    /*|'~'|'~/'*) ;;
    *) die "the registry must be an absolute path or start with ~/" ;;
  esac
  if [ "$mode" = shared ] && [ -z "$shared_registry" ]; then
    ask shared_registry 'Store shared environments in' "$prefix/envs"
  fi
  if [ -z "$python_manager" ]; then
    ask python_manager 'Python environment manager (micromamba/conda/mamba)' \
      "${detected_manager:-micromamba}"
  fi
  case $python_manager in
    micromamba|conda|mamba) ;;
    *) die "the Python environment manager must be micromamba, conda, or mamba" ;;
  esac
fi

# --- Files ------------------------------------------------------------------

stage=$(mktemp -d "$prefix/.install.XXXXXX")
for item in $INSTALLED_ITEMS; do
  cp -R "$source_dir/$item" "$stage/$item"
done
find "$stage" -name __pycache__ -prune -exec rm -rf {} +
chmod -R u+rwX,go+rX,go-w "$stage"
for item in $INSTALLED_ITEMS; do
  rm -rf -- "${prefix:?}/$item"
  mv "$stage/$item" "$prefix/$item"
done
rmdir "$stage"
stage=
printf '%s\n' "$version" >"$prefix/$MARKER"
chmod go+rx "$prefix"

if [ "$write_config" = 1 ]; then
  mkdir -p "$prefix/etc"
  {
    say '# Written by the proj installer; `proj doctor` shows the effective values.'
    say '# Users may override keys in ~/.config/proj/config.toml.'
    say 'schema = 1'
    say "registry = $(toml_string "$registry")"
    if [ "$mode" = shared ]; then
      say "shared_registry = $(toml_string "$(expand_home "$shared_registry")")"
      say "group = $(toml_string "$group")"
    fi
    say "python_manager = $(toml_string "$python_manager")"
  } >"$config_file"
  chmod 644 "$config_file"
elif [ -n "$python_manager" ]; then
  # An explicit choice on upgrade replaces only that key.
  grep -v '^python_manager = ' "$config_file" >"$config_file.new" || :
  say "python_manager = $(toml_string "$python_manager")" >>"$config_file.new"
  chmod 644 "$config_file.new"
  mv "$config_file.new" "$config_file"
  note "set python_manager = \"$python_manager\" in $config_file"
fi
if [ "$python" = /usr/bin/python3 ]; then
  rm -f "$prefix/etc/python"
else
  mkdir -p "$prefix/etc"
  printf '%s\n' "$python" >"$prefix/etc/python"
fi

if [ "$mode" = shared ] && [ -n "$shared_registry" ]; then
  shared_registry=$(expand_home "$shared_registry")
  mkdir -p "$shared_registry"
  # setgid keeps the group on new environments; sticky stops members from
  # removing or renaming environments they do not own.
  if chgrp "$group" "$shared_registry" && chmod 3770 "$shared_registry"; then
    note "shared registry $shared_registry (group $group, mode 3770)"
  else
    warn "could not set group and mode on $shared_registry; as root run:"
    warn "  chgrp $group $shared_registry && chmod 3770 $shared_registry"
  fi
fi

installed=1
if [ "$upgrade" = 1 ]; then
  say "Upgraded proj in $prefix"
else
  say "Installed proj in $prefix"
fi

# --- Shell initialization -----------------------------------------------------

proj_bin=$prefix/bin/proj

if is_root; then
  system_files=
  for candidate in /etc/zsh/zshrc /etc/zshrc /etc/bash.bashrc /etc/bashrc; do
    [ -f "$candidate" ] && system_files="$system_files $candidate"
  done
  if [ -n "$system_files" ] &&
     { [ "$system_init" = yes ] ||
       { [ -z "$system_init" ] &&
         confirm "Enable proj for every user via$system_files" no; }; }; then
    for file in $system_files; do
      case $file in
        *zsh*) "$proj_bin" init --shell zsh --rc "$file" ;;
        *) "$proj_bin" init --shell bash --rc "$file" ;;
      esac
    done
  else
    note "Each user can enable proj with: $proj_bin init"
  fi
elif [ -n "$shells" ] && [ "$init" != no ]; then
  for candidate in $shells; do
    rc=$(rc_for "$candidate")
    # Default to yes for shells you evidently use.
    default=no
    if [ -n "$shell_name" ] || [ "$candidate" = "$parent_shell" ] ||
       [ "$candidate" = "$login_shell" ] || [ -f "$rc" ]; then
      default=yes
    fi
    if [ "$init" = yes ]; then
      [ "$default" = yes ] && "$proj_bin" init --shell "$candidate"
    elif confirm "Initialize proj for $candidate in $rc" "$default"; then
      "$proj_bin" init --shell "$candidate"
    fi
  done
else
  note "Initialize later with: $proj_bin init --shell zsh|bash"
fi

say ''
say "Open a new shell, then run:  proj --version && proj doctor"
if [ "$mode" = shared ]; then
  say "Create a shared environment: proj create <name> --shared [--group-writable]"
fi
