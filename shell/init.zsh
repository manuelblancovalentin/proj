# Interactive Zsh integration for proj. Safe to source repeatedly.
[[ -n ${__PROJ_INITIALIZED-} ]] && return 0
typeset -g __PROJ_INITIALIZED=1

typeset -g PROJ_TOOL_ROOT=${${(%):-%N}:A:h:h}
typeset -g PROJ_SHELL_NAME=zsh

typeset -g PROJ_COMPLETION_DIR=$PROJ_TOOL_ROOT/shell/completions
if [[ ${fpath[(Ie)$PROJ_COMPLETION_DIR]} -eq 0 ]]; then
  fpath=("$PROJ_COMPLETION_DIR" $fpath)
fi

_proj_is_function() {
  (( $+functions[$1] ))
}

_proj_cd() {
  builtin cd -q -- "$1"
}

source "$PROJ_TOOL_ROOT/shell/core.sh"

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

autoload -Uz add-zsh-hook
add-zsh-hook precmd _proj_setup_mamba_alias

source "$PROJ_TOOL_ROOT/shell/completion.zsh"
