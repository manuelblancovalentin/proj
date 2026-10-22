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

# Draw `proj info` as a dots panel, or as the CLI's plain table without dots.
# A site profile sourced later may redefine this function.
_proj_render_info() {
  emulate -L zsh
  local environment_name=$1
  shift
  if (( ! $+functions[panel_begin] || ! $+functions[panel_row] )); then
    local -i width=5 index
    for (( index = 1; index < $#; index += 2 )); do
      (( ${#argv[index]} > width )) && width=${#argv[index]}
    done
    print -r -- "Project environment: $environment_name"
    printf "%-${width}s  %s\n" FIELD VALUE "${(l:width::-:):-}" -----
    printf "%-${width}s  %s\n" "$@"
    return 0
  fi
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

# Prompt segment: "[proj:<name>] " in front of PROMPT while an environment is
# active, nothing otherwise. A framework that draws the badge itself (dots,
# unless DOTS_PROMPT=never) is left to do so, and PROJ_PROMPT=off disables this.
# PROJ_PROMPT_SEGMENT holds the segment in prompt-escape form for prompts that
# place it themselves (they need prompt_subst).
typeset -g _proj_prompt_badge=''
_proj_prompt_update() {
  emulate -L zsh
  [[ -o interactive ]] || return 0
  local badge=''
  if [[ -n ${PROJ_ACTIVE-} ]]; then
    if [[ -n ${NO_COLOR-} ]]; then
      badge="[proj:${PROJ_ACTIVE}]"
    else
      badge="%F{134}[proj:%f%F{cyan}${PROJ_ACTIVE}%f%F{134}]%f"
    fi
  fi
  typeset -g PROJ_PROMPT_SEGMENT=$badge
  case ${PROJ_PROMPT:-auto} in off|never|0) return 0 ;; esac
  if (( $+functions[dots_prompt_apply] )) && [[ ${DOTS_PROMPT:-always} != (never|0) ]]; then
    return 0
  fi
  # Forget the badge this hook added earlier, then add the current one.
  [[ -n $_proj_prompt_badge && $PROMPT == "$_proj_prompt_badge "* ]] &&
    PROMPT=${PROMPT#"$_proj_prompt_badge "}
  _proj_prompt_badge=''
  if [[ -n $badge ]]; then
    PROMPT="$badge $PROMPT"
    _proj_prompt_badge=$badge
  fi
}

autoload -Uz add-zsh-hook
add-zsh-hook precmd _proj_setup_mamba_alias
add-zsh-hook precmd _proj_prompt_update

source "$PROJ_TOOL_ROOT/shell/completion.zsh"
