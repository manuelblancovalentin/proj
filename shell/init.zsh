# Interactive Zsh integration for proj. Safe to source repeatedly.
[[ -n ${__PROJ_INITIALIZED-} ]] && return 0
typeset -g __PROJ_INITIALIZED=1

typeset -g PROJ_TOOL_ROOT=${${(%):-%N}:A:h:h}
: ${PROJ_EXECUTABLE:=$PROJ_TOOL_ROOT/bin/proj}
: ${PROJ_GLOBAL_BIN:=${PROJ_TOOL_ROOT:h}/bin}
: ${PROJ_GLOBAL_MAN:=${PROJ_TOOL_ROOT:h}/share/man}
: ${PROJ_GLOBAL_SHARE:=${PROJ_TOOL_ROOT:h}/share}

typeset -g PROJ_COMPLETION_DIR=$PROJ_TOOL_ROOT/shell/completions
if [[ ${fpath[(Ie)$PROJ_COMPLETION_DIR]} -eq 0 ]]; then
  fpath=("$PROJ_COMPLETION_DIR" $fpath)
fi

_proj_log_ok() {
  if (( $+functions[ok] )); then
    ok "$@"
  else
    print -r -- " ✅ - $*"
  fi
}

_proj_log_info() {
  if (( $+functions[info] )); then
    info "$@"
  else
    print -r -- " ℹ️ - $*"
  fi
}

_proj_log_error() {
  if (( $+functions[error] )); then
    error "$@" >&2
  else
    print -u2 -r -- " ❌ - $*"
  fi
}

_proj_render_info() {
  emulate -L zsh
  local environment_name=$1
  shift
  panel_begin
  panel_title "Project Environment · $environment_name"
  local label value styled_label styled_value
  while (( $# >= 2 )); do
    label=$1
    value=$2
    shift 2
    dots_style_string "$CLR_CYAN$CLR_BOLD" "$label"
    styled_label=$REPLY
    dots_style_string "$CLR_YELLOW" "$value"
    styled_value=$REPLY
    panel_row "  $styled_label: $styled_value"
  done
  panel_end
}

if [[ -d $PROJ_GLOBAL_BIN && ${path[(Ie)$PROJ_GLOBAL_BIN]} -eq 0 ]]; then
  path=("$PROJ_GLOBAL_BIN" $path)
fi

# Announce presence in the dots welcome table, if dots is loaded. This is
# presentation-only: dots does not discover or manage proj. dots treats the
# description as an opaque, already-styled string, so proj colors the tool
# names it mentions (Lmod, micromamba) the same command color dots itself
# uses, when dots' palette is available.
if (( $+functions[dots_register_tool] )); then
  local -a _proj_info=()
  man -w proj >/dev/null 2>&1 && _proj_info+=('man proj')
  _proj_info+=('tldr proj')
  local _proj_lmod=Lmod _proj_mamba=micromamba
  if (( $+functions[dots_style_string] )); then
    dots_style_string "$CLR_CMD" 'Lmod'; _proj_lmod=$REPLY
    dots_style_string "$CLR_CMD" 'micromamba'; _proj_mamba=$REPLY
  fi
  dots_register_tool proj '🧭' \
    "Metadata-driven project environment manager ($_proj_lmod + $_proj_mamba)." \
    "${_proj_info[@]}"
  unset _proj_info _proj_lmod _proj_mamba
fi

# TLDR clients discover system pages beneath $XDG_DATA_DIRS/tldr.
if [[ :${XDG_DATA_DIRS:-/usr/local/share:/usr/share}: != *:$PROJ_GLOBAL_SHARE:* ]]; then
  export XDG_DATA_DIRS="$PROJ_GLOBAL_SHARE:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"
fi

# An empty MANPATH component asks man-db to retain its system defaults.
if [[ :${MANPATH-}: != *:$PROJ_GLOBAL_MAN:* ]]; then
  if [[ -n ${MANPATH-} ]]; then
    export MANPATH="$PROJ_GLOBAL_MAN:$MANPATH"
  else
    export MANPATH="$PROJ_GLOBAL_MAN:"
  fi
fi

# Install the short spelling after startup files have initialized micromamba.
# An earlier alias breaks parsing of micromamba's generated dormant mamba()
# branch even when the executable itself is named micromamba.
_proj_setup_mamba_alias() {
  if (( ! $+aliases[mamba] && ! $+functions[mamba] )) &&
     (( $+functions[micromamba] || $+commands[micromamba] )); then
    alias mamba=micromamba
  fi
}
autoload -Uz add-zsh-hook
add-zsh-hook precmd _proj_setup_mamba_alias

_proj_cli() {
  local module_function=0
  (( $+functions[module] )) && module_function=1
  PROJ_SHELL_INTEGRATION=1 PROJ_MODULE_FUNCTION=$module_function \
    command "$PROJ_EXECUTABLE" "$@"
}

_proj_clear_shell_state() {
  unset PROJ_PREVIOUS_PWD PROJ_MAMBA_SHLVL_BEFORE
}

_proj_rollback_activation() {
  local project_name=$1 module_name=$2 module_path=$3 mamba_env=$4
  if [[ -n $mamba_env && ${CONDA_DEFAULT_ENV-} == $mamba_env ]] &&
     (( $+functions[micromamba] )); then
    micromamba deactivate >/dev/null 2>&1
  fi
  module unload "$module_name" >/dev/null 2>&1
  module unuse "$module_path" >/dev/null 2>&1
  [[ -n ${PROJ_PREVIOUS_PWD-} ]] && builtin cd -q -- "$PROJ_PREVIOUS_PWD"
  _proj_clear_shell_state
}

_proj_activate() {
  emulate -L zsh
  local project_name=$1 project_root=$2 module_name=$3 module_path=$4
  local mamba_env=$5 metadata=$6 change_directory=$7 run_hooks=$8
  local previous_pwd=$PWD
  local previous_shlvl=${CONDA_SHLVL:-0}

  if (( ! $+functions[module] )); then
    _proj_log_error 'Lmod is unavailable; run `proj doctor`'
    return 2
  fi
  if [[ -n ${PROJ_ACTIVE-} ]]; then
    _proj_log_error \
      "Project '$PROJ_ACTIVE' is already active; deactivate it first"
    return 2
  fi

  module use "$module_path" || return
  if ! module load "$module_name"; then
    module unuse "$module_path" >/dev/null 2>&1
    return 2
  fi

  export PROJ_PREVIOUS_PWD=$previous_pwd
  export PROJ_MAMBA_SHLVL_BEFORE=$previous_shlvl

  if [[ -n $mamba_env ]]; then
    if (( ! $+functions[micromamba] )); then
      _proj_log_error 'Micromamba shell integration is unavailable'
      _proj_rollback_activation \
        "$project_name" "$module_name" "$module_path" "$mamba_env"
      return 2
    fi
    if ! micromamba activate "$mamba_env"; then
      _proj_rollback_activation \
        "$project_name" "$module_name" "$module_path" "$mamba_env"
      return 2
    fi
  fi

  if [[ $change_directory == 1 ]] &&
     ! builtin cd -q -- "$project_root"; then
    _proj_rollback_activation \
      "$project_name" "$module_name" "$module_path" "$mamba_env"
    return 2
  fi

  if [[ $run_hooks == 1 ]] &&
     ! _proj_cli _hook startup "$project_name"; then
    _proj_cli _hook shutdown "$project_name" >/dev/null 2>&1
    _proj_rollback_activation \
      "$project_name" "$module_name" "$module_path" "$mamba_env"
    return 2
  fi

  _proj_log_ok "Project '$project_name' activated 🚀"
}

_proj_deactivate() {
  emulate -L zsh
  local project_name=$1 module_name=$2 module_path=$3
  local mamba_env=$4 metadata=$5 change_directory=$6
  local previous_pwd=${PROJ_PREVIOUS_PWD-}
  local expected_shlvl=${PROJ_MAMBA_SHLVL_BEFORE:-0}

  if [[ ${PROJ_ACTIVE-} != "$project_name" ]]; then
    _proj_log_error 'Active project state has drifted; run `proj status`'
    return 2
  fi
  if [[ -n $mamba_env ]] &&
     [[ ${CONDA_DEFAULT_ENV-} != "$mamba_env" ||
        ${CONDA_SHLVL:-0} -ne $(( expected_shlvl + 1 )) ]]; then
    _proj_log_error \
      'Micromamba state has drifted; refusing unsafe deactivation'
    return 2
  fi

  _proj_cli _hook shutdown "$project_name" || return

  if [[ -n $mamba_env ]] && ! micromamba deactivate; then
    _proj_log_error 'Micromamba deactivation failed'
    return 2
  fi
  if ! module unload "$module_name"; then
    _proj_log_error 'Lmod project unload failed'
    return 2
  fi
  module unuse "$module_path" >/dev/null 2>&1
  _proj_clear_shell_state

  if [[ $change_directory == 1 && -n $previous_pwd && -d $previous_pwd ]]; then
    builtin cd -q -- "$previous_pwd"
  fi
  _proj_log_ok "Project '$project_name' deactivated ✨"
}

_proj_no_active() {
  _proj_log_info 'No project is active'
}

proj() {
  emulate -L zsh
  case ${1-} in
    activate|deactivate)
      local code
      code=$(_proj_cli _shell "$@") || return
      eval "$code"
      ;;
    info)
      if (( $+functions[panel_begin] && $+functions[panel_row] )); then
        local code
        code=$(_proj_cli _info-code "${@:2}") || return
        eval "$code"
      else
        _proj_cli "$@"
      fi
      ;;
    '') _proj_cli --help ;;
    *) _proj_cli "$@" ;;
  esac
}

source "$PROJ_TOOL_ROOT/shell/completion.zsh"
