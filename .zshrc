if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

export PATH="$HOME/.spicetify:$HOME/.local/bin:$HOME/bin:$PATH"
export ZSH="$HOME/.oh-my-zsh"

if [[ -r "$ZSH/oh-my-zsh.sh" ]]; then
  if [[ -d "$ZSH/custom/themes/powerlevel10k" ]]; then
    ZSH_THEME="powerlevel10k/powerlevel10k"
  else
    ZSH_THEME="robbyrussell"
  fi
  plugins=(git)
  source "$ZSH/oh-my-zsh.sh"
else
  autoload -Uz compinit && compinit
  setopt prompt_subst
  PROMPT='%F{yellow}%n%f@%F{blue}%m%f %F{green}%~%f %# '
fi

[[ -r /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh ]] &&
  source /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh
[[ -r /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ]] &&
  source /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

if command -v fzf >/dev/null 2>&1; then
  source <(fzf --zsh)
fi

HISTFILE="${XDG_STATE_HOME:-$HOME/.local/state}/zsh/history"
mkdir -p "${HISTFILE:h}"
HISTSIZE=10000
SAVEHIST=10000
setopt append_history share_history hist_ignore_dups

[[ -r "$HOME/.p10k.zsh" ]] && source "$HOME/.p10k.zsh"

function y() {
  local tmp cwd
  tmp=$(mktemp -t 'yazi-cwd.XXXXXX')
  yazi "$@" --cwd-file="$tmp"
  IFS= read -r -d '' cwd < "$tmp"
  [[ -n "$cwd" && "$cwd" != "$PWD" ]] && builtin cd -- "$cwd"
  rm -f -- "$tmp"
}
