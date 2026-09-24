# Register immediately when compinit already ran. Otherwise the completion file
# on fpath is discovered when the user's later compinit runs.
autoload -Uz _proj
(( $+functions[compdef] )) && compdef _proj proj
return 0
