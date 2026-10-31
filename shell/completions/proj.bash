# Native Bash completion for proj. Candidates that need discovery (projects,
# Python environments, Lmod modules) are computed only when Tab is pressed.

_proj_complete_available_modules() {
  local line
  while IFS= read -r line; do
    line=${line#"${line%%[![:space:]]*}"}
    line=${line%%[[:space:]]*}
    case $line in
      ''|*:|*/|project/*) continue ;;
    esac
    printf '%s\n' "$line"
  done < <(module --terse avail 2>&1)
}

_proj_complete() {
  local cur=${COMP_WORDS[COMP_CWORD]}
  local prev=${COMP_WORDS[COMP_CWORD-1]}
  local command=${COMP_WORDS[1]-}
  local candidates=''
  local IFS=$'\n'

  if (( COMP_CWORD == 1 )); then
    candidates=$'create\nlist\navail\nuse\nunuse\nactivate\ndeactivate\nshare\nunshare\naccess\nremove\nupgrade\ncurrent\nstatus\ninfo\nconfig\nconfigmenu'
    candidates+=$'\nset-python-env\npython-env\nmodule\nenv\ndoctor\ninit\ninstall\n--version'
  elif [[ $prev == --env || $prev == --project ]]; then
    candidates=$(_proj_cli _complete projects 2>/dev/null)
  elif [[ $command == init && $prev == --shell ]]; then
    candidates=$'zsh\nbash'
  elif [[ $prev == --manager ]]; then
    candidates=$'micromamba\nconda\nmamba'
  elif [[ $prev == --use ]]; then
    candidates=$(_proj_cli _complete uses 2>/dev/null)
  elif [[ $command == create && $prev == --from ]]; then
    candidates=$(_proj_cli _complete projects 2>/dev/null)
  elif [[ $command == create && $prev == --python ]]; then
    candidates=$(_proj_cli python-env list 2>/dev/null)
  elif [[ $command == create && $prev == --root ]] ||
       [[ $command == init && $prev == --rc ]]; then
    compopt -o default 2>/dev/null
    COMPREPLY=()
    return 0
  else
    case $command in
      activate)
        (( COMP_CWORD == 2 )) && candidates=$(_proj_cli _complete projects 2>/dev/null)
        ;;
      upgrade)
        candidates=$'--check\n--yes\n--force\n--ref'
        ;;
      use)
        if [[ $cur == -* ]]; then
          candidates=$'--env\n--list'
        else
          candidates=$(_proj_cli _complete uses 2>/dev/null)
        fi
        ;;
      unuse)
        if [[ $cur == -* ]]; then
          candidates=--env
        else
          candidates=$(_proj_cli _complete used 2>/dev/null)
        fi
        ;;
      remove)
        if (( COMP_CWORD == 2 )); then
          candidates=$(_proj_cli _complete projects 2>/dev/null)
        else
          candidates=$'--yes\n--delete-files\n--keep-files'
        fi
        ;;
      share)
        if (( COMP_CWORD == 2 )); then
          candidates=$(_proj_cli _complete projects 2>/dev/null)
        else
          candidates=$'--group\n--group-writable\n--private'
        fi
        ;;
      access)
        if (( COMP_CWORD == 2 )); then
          candidates=$(_proj_cli _complete projects 2>/dev/null)
        else
          candidates=$'--owner-only\n--group-writable\n--private'
        fi
        ;;
      unshare)
        if (( COMP_CWORD == 2 )); then
          candidates=$(_proj_cli _complete projects 2>/dev/null)
        else
          candidates=--force
        fi
        ;;
      create)
        (( COMP_CWORD >= 3 )) && candidates=$'--root\n--from\n--python\n--shared\n--group\n--group-writable\n--private\n--use'
        ;;
      config)
        candidates=$'--env\nproject.description\nproject.root\nproject.shell'
        candidates+=$'\npython.manager\npython.environment\npython.spec\npaths.prepend'
        candidates+=$'\nhooks.startup\nhooks.shutdown'
        ;;
      info)
        candidates=--env
        ;;
      avail)
        candidates=$'compiler\ntoolchain\napplication\nproject\n--json'
        ;;
      configmenu)
        candidates=$'--env\n--setup'
        ;;
      set-python-env)
        candidates=$(_proj_cli python-env list 2>/dev/null)
        candidates+=$'\n--env\n--manager'
        ;;
      python-env)
        if (( COMP_CWORD == 2 )); then
          candidates=$'list\nstamp'
        elif [[ ${COMP_WORDS[2]} == stamp ]]; then
          candidates=--env
        else
          candidates=--manager
        fi
        ;;
      module)
        case $COMP_CWORD in
          2) candidates=$'list\nadd\nremove' ;;
          3) candidates=$'project\ntoolchain\napplication\ncompiler' ;;
          4)
            case ${COMP_WORDS[2]} in
              add) candidates=$(_proj_complete_available_modules) ;;
              remove)
                candidates=$(_proj_cli module list "${COMP_WORDS[3]}" 2>/dev/null)
                ;;
            esac
            ;;
          *) candidates=--env ;;
        esac
        ;;
      env)
        if (( COMP_CWORD == 2 )); then
          candidates=$'list\nshow'
        elif [[ ${COMP_WORDS[2]} == show && COMP_CWORD -eq 3 ]]; then
          candidates=$(_proj_cli _complete projects 2>/dev/null)
        fi
        ;;
      init)
        candidates=$'--shell\n--rc\n--reverse'
        ;;
    esac
  fi
  COMPREPLY=($(compgen -W "$candidates" -- "$cur"))
  if (( COMP_CWORD == 1 )) && [[ -n $cur ]]; then
    # The everyday commands win a shared prefix, so "proj a<Tab>" and
    # "proj ac<Tab>" complete activate even though avail and access also
    # start that way. Keep this list identical to the zsh completion.
    local everyday=$'activate\ndeactivate\nlist\nstatus\ncurrent\nuse\nunuse\ncreate\ninfo'
    local preferred
    preferred=$(compgen -W "$everyday" -- "$cur")
    [[ -n $preferred ]] && COMPREPLY=($preferred)
  fi
}

complete -F _proj_complete proj
