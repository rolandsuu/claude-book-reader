#!/bin/sh
# Links this repo's skills into ~/.claude/skills, so Claude Code finds them and `git pull` updates them.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"
mkdir -p "$dest"

for skill in "$here"/skills/*/; do
  skill=${skill%/}
  name=$(basename "$skill")
  target="$dest/$name"
  if [ -L "$target" ]; then
    case "$(readlink "$target")" in
      "$here"/*) rm "$target" ;;
      *)
        # A link to a copy kept elsewhere is the user's own install: leave it alone.
        echo "Kept your existing $name skill ($target -> $(readlink "$target")). Remove that link and rerun to use this repo's copy."
        continue
        ;;
    esac
  elif [ -e "$target" ]; then
    backup="$target.backup-$(date +%Y%m%d%H%M%S)"
    mv "$target" "$backup"
    echo "Moved the existing $name skill aside to $backup"
  fi
  ln -s "$skill" "$target"
  echo "Linked $target -> $skill"
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "Note: the reader needs python3. On a Mac: xcode-select --install"
fi
echo "Done. In Claude Code, type /books to open the reader in the side panel."
