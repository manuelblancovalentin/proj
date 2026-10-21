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
case ";${PROMPT_COMMAND-};" in
  *";_proj_setup_mamba_alias;"*) ;;
  *) PROMPT_COMMAND="_proj_setup_mamba_alias${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
