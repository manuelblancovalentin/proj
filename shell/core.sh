# Parent-shell lifecycle shared by the Zsh and Bash adapters.
#
# The sourcing adapter defines PROJ_TOOL_ROOT, PROJ_SHELL_NAME,
# _proj_is_function, and _proj_cd first. Everything here is portable between
# Bash and Zsh, and sourcing it starts no subprocess. Functions that run under
# Zsh begin with `emulate -L zsh` so user options cannot change their meaning.

: "${PROJ_EXECUTABLE:=$PROJ_TOOL_ROOT/bin/proj}"
: "${PROJ_GLOBAL_BIN:=${PROJ_TOOL_ROOT%/*}/bin}"
: "${PROJ_GLOBAL_MAN:=${PROJ_TOOL_ROOT%/*}/share/man}"
: "${PROJ_GLOBAL_SHARE:=${PROJ_TOOL_ROOT%/*}/share}"

# Prefer a public link layout (such as /tools/bin) when it exposes this very
# checkout; otherwise use the installation's own directories.
if [ "$PROJ_GLOBAL_BIN/proj" -ef "$PROJ_TOOL_ROOT/bin/proj" ]; then
  PROJ_BIN_DIR=$PROJ_GLOBAL_BIN
else
  PROJ_BIN_DIR=$PROJ_TOOL_ROOT/bin
fi
if [ "$PROJ_GLOBAL_MAN/man1/proj.1" -ef "$PROJ_TOOL_ROOT/share/man/man1/proj.1" ]; then
  PROJ_MAN_DIR=$PROJ_GLOBAL_MAN
else
  PROJ_MAN_DIR=$PROJ_TOOL_ROOT/share/man
fi
if [ "$PROJ_GLOBAL_SHARE/tldr/pages/common/proj.md" -ef \
     "$PROJ_TOOL_ROOT/share/tldr/pages/common/proj.md" ]; then
  PROJ_DATA_DIR=$PROJ_GLOBAL_SHARE
else
  PROJ_DATA_DIR=$PROJ_TOOL_ROOT/share
fi

# _proj_prepend_path VARIABLE DIRECTORY [SUFFIX_WHEN_EMPTY]
_proj_prepend_path() {
  local current
  eval "current=\${$1-}"
  case ":$current:" in
    *":$2:"*) return 0 ;;
  esac
  if [ -n "$current" ]; then
    export "$1=$2:$current"
  else
    export "$1=$2${3-}"
  fi
}

_proj_prepend_path PATH "$PROJ_BIN_DIR"
# An empty MANPATH component asks man-db to retain its system defaults.
_proj_prepend_path MANPATH "$PROJ_MAN_DIR" ":"
# TLDR clients discover system pages beneath $XDG_DATA_DIRS/tldr.
_proj_prepend_path XDG_DATA_DIRS "$PROJ_DATA_DIR" ":/usr/local/share:/usr/share"

_proj_log_ok() {
  if _proj_is_function ok; then
    ok "$@"
  else
    printf ' ✅ - %s\n' "$*"
  fi
}

_proj_log_info() {
  if _proj_is_function info; then
    info "$@"
  else
    printf ' ℹ️ - %s\n' "$*"
  fi
}

_proj_log_error() {
  if _proj_is_function error; then
    error "$@" >&2
  else
    printf ' ❌ - %s\n' "$*" >&2
  fi
}

# Install the short spelling after startup files have initialized micromamba.
# An earlier alias breaks parsing of micromamba's generated dormant mamba()
# branch even when the executable itself is named micromamba. A real mamba
# (alias, function, or command, as Miniforge provides) is never shadowed.
_proj_setup_mamba_alias() {
  if ! command -v mamba >/dev/null 2>&1 &&
     { _proj_is_function micromamba || command -v micromamba >/dev/null 2>&1; }; then
    alias mamba=micromamba
  fi
}

_proj_cli() {
  local module_function=0
  _proj_is_function module && module_function=1
  PROJ_SHELL_INTEGRATION=$PROJ_SHELL_NAME PROJ_MODULE_FUNCTION=$module_function \
    command "$PROJ_EXECUTABLE" "$@"
}

_proj_clear_shell_state() {
  unset PROJ_PREVIOUS_PWD PROJ_MAMBA_SHLVL_BEFORE PROJ_LOGIN_MODULES
}

# Remember which modules the login had loaded, for _proj_restore_login_modules.
# The record is a plain shell variable, deliberately not exported: it must not
# reach the tools and hooks that run in this shell. It is replaced (never
# appended to) at each activation, which only happens with no environment
# active, and it is dropped when the environment ends; it can be no larger than
# the limit below, so a very long login is not remembered rather than kept.
_proj_record_login_modules() {
  unset PROJ_LOGIN_MODULES
  [ -n "${LOADEDMODULES-}" ] || return 0
  if [ "${#LOADEDMODULES}" -gt 4096 ]; then
    _proj_log_info 'Your login has too many modules to remember; they will not be restored on deactivate'
    return 0
  fi
  PROJ_LOGIN_MODULES=$LOADEDMODULES
  # `set -a` would export the assignment above.
  if [ -n "${ZSH_VERSION-}" ]; then typeset -g +x PROJ_LOGIN_MODULES; else export -n PROJ_LOGIN_MODULES; fi
}

# Put back the modules the login had loaded that an environment displaced.
# Lmod swaps another version of a tool, or another member of its family, in
# silently and does not remember what it replaced, so without this the login's
# own choice (from the site defaults or a person's own login config) would be
# lost when the environment is deactivated.
_proj_restore_login_modules() {
  [ -n "${PROJ_LOGIN_MODULES-}" ] || return 0
  local rest=$PROJ_LOGIN_MODULES name
  while [ -n "$rest" ]; do
    name=${rest%%:*}
    case $rest in
      *:*) rest=${rest#*:} ;;
      *) rest= ;;
    esac
    case ":${LOADEDMODULES-}:" in
      *":$name:"*) ;;
      *) module load "$name" >/dev/null 2>&1 || _proj_log_info "could not restore $name" ;;
    esac
  done
  return 0
}

# Choose the shell function that activates environments for a manager
# (micromamba, conda, or mamba) and store it in _proj_python_command. mamba 2
# activates only after `mamba shell init`; without it, conda's function manages
# the same environments.
_proj_select_python_command() {
  if _proj_is_function "$1"; then
    _proj_python_command=$1
  elif [ "$1" = mamba ] && _proj_is_function conda; then
    _proj_python_command=conda
  else
    return 1
  fi
}

# Environments are recorded by name or, for shared projects, by prefix path.
_proj_mamba_active() {
  case $1 in
    /*) [ "${CONDA_PREFIX-}" = "$1" ] ;;
    *) [ "${CONDA_DEFAULT_ENV-}" = "$1" ] ;;
  esac
}

_proj_rollback_activation() {
  local project_name=$1 module_name=$2 module_path=$3 mamba_env=$4
  local python_manager=${5:-micromamba}
  if [ -n "$mamba_env" ] && _proj_mamba_active "$mamba_env" &&
     _proj_select_python_command "$python_manager"; then
    "$_proj_python_command" deactivate >/dev/null 2>&1
  fi
  module unload "$module_name" >/dev/null 2>&1
  _proj_restore_login_modules
  module unuse "$module_path" >/dev/null 2>&1
  [ -n "${PROJ_PREVIOUS_PWD-}" ] && _proj_cd "$PROJ_PREVIOUS_PWD"
  _proj_clear_shell_state
}

_proj_activate() {
  [ -n "${ZSH_VERSION-}" ] && emulate -L zsh
  local project_name=$1 project_root=$2 module_name=$3 module_path=$4
  local mamba_env=$5 metadata=$6 change_directory=$7 run_hooks=$8
  local python_manager=${9:-micromamba} restore_login=${10:-1}
  local previous_pwd=$PWD
  local previous_shlvl=${CONDA_SHLVL:-0}

  if ! _proj_is_function module; then
    _proj_log_error 'Lmod is unavailable; run `proj doctor`'
    return 2
  fi
  if [ -n "${PROJ_ACTIVE-}" ]; then
    _proj_log_error \
      "Project '$PROJ_ACTIVE' is already active; deactivate it first"
    return 2
  fi

  module use "$module_path" || return
  if [ "$restore_login" = 1 ]; then _proj_record_login_modules; else unset PROJ_LOGIN_MODULES; fi
  if ! module load "$module_name"; then
    _proj_restore_login_modules
    unset PROJ_LOGIN_MODULES
    module unuse "$module_path" >/dev/null 2>&1
    return 2
  fi

  export PROJ_PREVIOUS_PWD=$previous_pwd
  export PROJ_MAMBA_SHLVL_BEFORE=$previous_shlvl

  if [ -n "$mamba_env" ]; then
    if ! _proj_select_python_command "$python_manager"; then
      _proj_log_error \
        "$python_manager shell integration is unavailable; initialize it in your startup file"
      _proj_rollback_activation \
        "$project_name" "$module_name" "$module_path" "$mamba_env" "$python_manager"
      return 2
    fi
    if ! "$_proj_python_command" activate "$mamba_env"; then
      _proj_rollback_activation \
        "$project_name" "$module_name" "$module_path" "$mamba_env" "$python_manager"
      return 2
    fi
  fi

  if [ "$change_directory" = 1 ] && ! _proj_cd "$project_root"; then
    _proj_rollback_activation \
      "$project_name" "$module_name" "$module_path" "$mamba_env" "$python_manager"
    return 2
  fi

  if [ "$run_hooks" = 1 ] && ! _proj_cli _hook startup "$project_name"; then
    _proj_cli _hook shutdown "$project_name" >/dev/null 2>&1
    _proj_rollback_activation \
      "$project_name" "$module_name" "$module_path" "$mamba_env" "$python_manager"
    return 2
  fi

  _proj_log_ok "Project '$project_name' activated 🚀"
}

_proj_deactivate() {
  [ -n "${ZSH_VERSION-}" ] && emulate -L zsh
  local project_name=$1 module_name=$2 module_path=$3
  local mamba_env=$4 metadata=$5 change_directory=$6
  local python_manager=${7:-micromamba}
  local previous_pwd=${PROJ_PREVIOUS_PWD-}
  local expected_shlvl=${PROJ_MAMBA_SHLVL_BEFORE:-0}

  if [ "${PROJ_ACTIVE-}" != "$project_name" ]; then
    _proj_log_error 'Active project state has drifted; run `proj status`'
    return 2
  fi
  if [ -n "$mamba_env" ] &&
     { ! _proj_mamba_active "$mamba_env" ||
       [ "${CONDA_SHLVL:-0}" -ne $(( expected_shlvl + 1 )) ]; }; then
    _proj_log_error \
      'Python environment state has drifted; refusing unsafe deactivation'
    return 2
  fi
  if [ -n "$mamba_env" ] && ! _proj_select_python_command "$python_manager"; then
    _proj_log_error "$python_manager shell integration is unavailable"
    return 2
  fi

  _proj_cli _hook shutdown "$project_name" || return

  if [ -n "$mamba_env" ] && ! "$_proj_python_command" deactivate; then
    _proj_log_error "$python_manager deactivation failed"
    return 2
  fi
  if ! module unload "$module_name"; then
    _proj_log_error 'Lmod project unload failed'
    return 2
  fi
  _proj_restore_login_modules
  module unuse "$module_path" >/dev/null 2>&1
  _proj_clear_shell_state

  if [ "$change_directory" = 1 ] && [ -n "$previous_pwd" ] && [ -d "$previous_pwd" ]; then
    _proj_cd "$previous_pwd"
  fi
  _proj_log_ok "Project '$project_name' deactivated ✨"
}

# Reload the active environment after `proj use`/`proj unuse` changed its module
# list. The cached modulefile still has the old dependency list, so unloading
# it first makes Lmod unload exactly what it loaded; then the file is
# regenerated and loaded again. A failed reload leaves the shell clean, as a
# failed activation does; the change itself is already saved.
_proj_reapply() {
  [ -n "${ZSH_VERSION-}" ] && emulate -L zsh
  local project_name=$1 module_name=$2 module_path=$3
  local mamba_env=${4-} python_manager=${5:-micromamba}

  if ! _proj_is_function module; then
    _proj_log_error 'Lmod is unavailable; run `proj doctor`'
    return 2
  fi
  if [ "${PROJ_ACTIVE-}" != "$project_name" ]; then
    _proj_log_error 'Active project state has drifted; run `proj status`'
    return 2
  fi
  if ! module unload "$module_name"; then
    _proj_log_error 'Lmod project unload failed'
    return 2
  fi
  _proj_restore_login_modules
  if ! _proj_cli _materialize "$project_name" || ! module load "$module_name"; then
    _proj_log_error \
      "Could not reload '$project_name'; the change is saved. Fix the problem, then run: proj activate $project_name"
    _proj_rollback_activation \
      "$project_name" "$module_name" "$module_path" "$mamba_env" "$python_manager"
    return 2
  fi
  _proj_log_ok "Project '$project_name' updated in this shell 🔄"
}

_proj_no_active() {
  _proj_log_info 'No project is active'
}

proj() {
  [ -n "${ZSH_VERSION-}" ] && emulate -L zsh
  local code
  case ${1-} in
    activate|deactivate)
      code=$(_proj_cli _shell "$@") || return
      eval "$code"
      ;;
    info)
      # Any adapter or site profile may define _proj_render_info to draw the
      # metadata (it receives the name, then label/value pairs).
      if _proj_is_function _proj_render_info; then
        code=$(_proj_cli _info-code "${@:2}") || return
        eval "$code"
      else
        _proj_cli "$@"
      fi
      ;;
    use|unuse)
      # The CLI edits the metadata and, for the active environment, leaves a
      # snippet in this file for the shell to evaluate.
      local code_file use_status
      if code_file=$(mktemp "${TMPDIR:-/tmp}/proj-code.XXXXXX" 2>/dev/null); then
        export PROJ_SHELL_CODE_FILE=$code_file
        _proj_cli "$@"
        use_status=$?
        unset PROJ_SHELL_CODE_FILE
        code=
        [ -s "$code_file" ] && code=$(cat "$code_file")
        rm -f -- "$code_file"
      else
        _proj_cli "$@"
        use_status=$?
      fi
      if [ "$use_status" -eq 0 ] && [ -n "$code" ]; then
        eval "$code"
        return
      fi
      return "$use_status"
      ;;
    '') _proj_cli --help ;;
    *) _proj_cli "$@" ;;
  esac
}
