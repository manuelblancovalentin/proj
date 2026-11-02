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
  _proj_prompt_end
}

# Prompt tokens. While an environment is active the prompt marker may carry a
# few small emoji, each shown while an environment variable is set (the Python
# token while CONDA_PREFIX is, the wolf token while WOLF_ACTIVE_ENV is). The
# table comes from proj's configuration and is passed in at activation; the
# adapters evaluate it at every prompt with shell builtins only, so a
# `conda activate` or `wolf activate` typed inside the environment shows up at
# the next prompt. The table is exported as PROJ_PROMPT_TABLE (one
# `name|emoji|plain|VARIABLE` row per line) so a shell started inside the
# environment draws the same tokens; PROJ_PROMPT_TOKENS lists the token names
# proj draws, for other tools (a tool that draws its own marker hides it while
# its name is listed). Both exist only while an environment is active and proj
# is the one drawing the marker.
#
# Inside an environment the Python manager's own "(environment)" prefix is
# switched off (CONDA_CHANGEPS1 for conda and mamba, MAMBA_CHANGEPS1 for
# micromamba), and only while the python token is there to say the same thing.
# The person's own values come back when the environment ends; a prefix already
# in the prompt before activation is not touched.

# Whether proj will draw the marker: PROJ_PROMPT=off leaves the prompt alone,
# and in Zsh a framework that draws the badge itself (dots) takes over.
_proj_prompt_drawn() {
  case ${PROJ_PROMPT-auto} in off|never|0) return 1 ;; esac
  if [ -n "${ZSH_VERSION-}" ] && _proj_is_function dots_prompt_apply; then
    case ${DOTS_PROMPT:-always} in never|0) ;; *) return 1 ;; esac
  fi
  return 0
}

# Succeeds when the tokens should be written in ASCII: the person asked for it
# (PROJ_PLAIN_PROMPT), the terminal is the Linux console or "dumb", or the
# locale is not UTF-8.
_proj_prompt_is_plain() {
  case ${PROJ_PLAIN_PROMPT-} in ''|0|off|no|false) ;; *) return 0 ;; esac
  case ${TERM-} in linux|dumb) return 0 ;; esac
  case ${LC_ALL:-${LC_CTYPE:-${LANG-}}} in
    *[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) return 1 ;;
  esac
  return 0
}

# Set _proj_prompt_text to the tokens to show now, separated by spaces.
_proj_prompt_tokens() {
  _proj_prompt_text=
  [ -n "${PROJ_PROMPT_TABLE-}" ] || return 0
  local rest=$PROJ_PROMPT_TABLE row name glyph plain variable value text= use_plain=0
  local nl='
'
  _proj_prompt_is_plain && use_plain=1
  while [ -n "$rest" ]; do
    row=${rest%%"$nl"*}
    case $rest in
      *"$nl"*) rest=${rest#*"$nl"} ;;
      *) rest= ;;
    esac
    name=${row%%|*}; row=${row#*|}
    glyph=${row%%|*}; row=${row#*|}
    plain=${row%%|*}; variable=${row#*|}
    case $variable in ''|[0-9]*|*[!A-Za-z0-9_]*) continue ;; esac
    eval "value=\${$variable-}"
    [ -n "$value" ] || continue
    if [ "$use_plain" = 1 ] || [ -z "$glyph" ]; then glyph=$plain; fi
    text=${text:+$text }$glyph
  done
  _proj_prompt_text=$text
}

# A plain shell variable, never exported: used for the person's own values that
# are put back when the environment ends.
_proj_unexport() {
  if [ -n "${ZSH_VERSION-}" ]; then typeset -g +x "$1"; else export -n "$1"; fi
}

_proj_prompt_begin() {
  [ -n "${ZSH_VERSION-}" ] && emulate -L zsh
  local table=${1-} hide_prefix=${2-1} variable names= row rest nl='
'
  _proj_prompt_end
  [ -n "$table" ] || return 0
  _proj_prompt_drawn || return 0
  export PROJ_PROMPT_TABLE=$table
  rest=$table
  while [ -n "$rest" ]; do
    row=${rest%%"$nl"*}
    case $rest in
      *"$nl"*) rest=${rest#*"$nl"} ;;
      *) rest= ;;
    esac
    names=${names:+$names }${row%%|*}
  done
  export PROJ_PROMPT_TOKENS=$names
  case " $names " in *" python "*) ;; *) return 0 ;; esac
  [ "$hide_prefix" = 1 ] || return 0
  for variable in CONDA_CHANGEPS1 MAMBA_CHANGEPS1; do
    eval "if [ \"\${$variable+set}\" = set ]; then _PROJ_SAVED_$variable=\"set:\$$variable\"; else _PROJ_SAVED_$variable=unset; fi"
    _proj_unexport "_PROJ_SAVED_$variable"
    export "$variable=false"
  done
}

_proj_prompt_end() {
  [ -n "${ZSH_VERSION-}" ] && emulate -L zsh
  local variable saved
  for variable in CONDA_CHANGEPS1 MAMBA_CHANGEPS1; do
    eval "saved=\${_PROJ_SAVED_$variable-}"
    case $saved in
      set:*) export "$variable=${saved#set:}" ;;
      unset) unset "$variable" ;;
    esac
    unset "_PROJ_SAVED_$variable"
  done
  unset PROJ_PROMPT_TABLE PROJ_PROMPT_TOKENS
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
  local prompt_table=${11-} hide_prefix=${12:-1}
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
  _proj_prompt_begin "$prompt_table" "$hide_prefix"

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
