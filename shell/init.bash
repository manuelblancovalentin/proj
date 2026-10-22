# Interactive Bash integration for proj. Safe to source repeatedly.
[ -n "${__PROJ_INITIALIZED-}" ] && return 0
__PROJ_INITIALIZED=1

__proj_source=${BASH_SOURCE[0]}
# Resolving a symlink needs readlink; the usual direct source starts nothing.
[ -L "$__proj_source" ] && __proj_source=$(readlink -f -- "$__proj_source")
case $__proj_source in
  /*) ;;
  *) __proj_source=$PWD/$__proj_source ;;
esac
__proj_source=${__proj_source%/*}
PROJ_TOOL_ROOT=${__proj_source%/*}
PROJ_SHELL_NAME=bash
unset __proj_source

_proj_is_function() {
  declare -F "$1" >/dev/null
}

_proj_cd() {
  builtin cd -- "$1" >/dev/null
}

. "$PROJ_TOOL_ROOT/shell/core.sh"
. "$PROJ_TOOL_ROOT/shell/completions/proj.bash"

# Defer the mamba alias to the first prompt, after micromamba's hook.
# PROMPT_COMMAND is an array from Bash 5.1 on, and may still be a string.
case "$(declare -p PROMPT_COMMAND 2>/dev/null)" in
  "declare -a"*)
    [[ " ${PROMPT_COMMAND[*]} " == *" _proj_setup_mamba_alias "* ]] ||
      PROMPT_COMMAND=(_proj_setup_mamba_alias "${PROMPT_COMMAND[@]}")
    ;;
  *)
    case ";${PROMPT_COMMAND-};" in
      *";_proj_setup_mamba_alias;"*) ;;
      *) PROMPT_COMMAND="_proj_setup_mamba_alias${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
    esac
    ;;
esac

# Prompt segment: "[proj:<name>] " while an environment is active, nothing
# otherwise. The hook only maintains PROJ_PROMPT_SEGMENT (no subprocess) and,
# unless the prompt already mentions it, puts a reference to it in front of PS1.
# A prompt that wants the segment elsewhere includes ${PROJ_PROMPT_SEGMENT}
# itself; PROJ_PROMPT=off leaves PS1 alone. \001 and \002 are readline's
# "non-printing" markers, the form that survives parameter expansion.
_proj_prompt_update() {
  local name=${PROJ_ACTIVE-}
  if [ -z "$name" ]; then
    PROJ_PROMPT_SEGMENT=
  elif [ -n "${NO_COLOR-}" ]; then
    PROJ_PROMPT_SEGMENT="[proj:$name]"
  else
    PROJ_PROMPT_SEGMENT=$'\001\e[38;5;134m\002[proj:\001\e[36m\002'$name$'\001\e[38;5;134m\002]\001\e[0m\002'
  fi
  case ${PROJ_PROMPT-auto} in off|never|0) return 0 ;; esac
  case ${PS1-} in
    ''|*PROJ_PROMPT_SEGMENT*) ;;
    *) shopt -q promptvars && PS1='${PROJ_PROMPT_SEGMENT:+$PROJ_PROMPT_SEGMENT }'$PS1 ;;
  esac
  return 0
}

case "$(declare -p PROMPT_COMMAND 2>/dev/null)" in
  "declare -a"*)
    [[ " ${PROMPT_COMMAND[*]} " == *" _proj_prompt_update "* ]] ||
      PROMPT_COMMAND+=(_proj_prompt_update)
    ;;
  *)
    case ";${PROMPT_COMMAND-};" in
      *";_proj_prompt_update;"*) ;;
      *) PROMPT_COMMAND="${PROMPT_COMMAND:+${PROMPT_COMMAND%;};}_proj_prompt_update" ;;
    esac
    ;;
esac
