git worktree list --porcelain > wt_full.txt
total=$(grep -c "^worktree " wt_full.txt)
removed=0
failures=0
detached_clean=0
detached_dirty=0
named_non_main=0

current_path=""
is_detached=false
is_named_non_main=false

while IFS= read -r line; do
    if [[ $line =~ ^worktree\ (.*) ]]; then
        current_path="${BASH_REMATCH[1]}"
        is_detached=false
        is_named_non_main=false
    elif [[ $line == "detached" ]]; then
        is_detached=true
    elif [[ $line =~ ^branch\ refs/heads/(.*) ]]; then
        branch="${BASH_REMATCH[1]}"
        if [[ "$branch" != "main" ]]; then
            is_named_non_main=true
        fi
    elif [[ -z "$line" ]]; then
        if $is_named_non_main; then
            named_non_main=$((named_non_main + 1))
        elif $is_detached; then
            if [[ -d "$current_path" ]]; then
                if [[ -z $(git -C "$current_path" status --porcelain) ]]; then
                    detached_clean=$((detached_clean + 1))
                    if git worktree remove "$current_path" 2>/dev/null || git worktree remove --force "$current_path" 2>/dev/null; then
                        removed=$((removed + 1))
                    else
                        failures=$((failures + 1))
                    fi
                else
                    detached_dirty=$((detached_dirty + 1))
                fi
            fi
        fi
    fi
done < wt_full.txt

# Final recount
git worktree list --porcelain > wt_new.txt
new_total=$(grep -c "^worktree " wt_new.txt)
new_detached_clean=0
new_detached_dirty=0
new_named_non_main=0

current_path=""
is_detached=false
is_named_non_main=false
while IFS= read -r line; do
    if [[ $line =~ ^worktree\ (.*) ]]; then
        is_detached=false
        is_named_non_main=false
    elif [[ $line == "detached" ]]; then
        is_detached=true
    elif [[ $line =~ ^branch\ refs/heads/(.*) ]]; then
        branch="${BASH_REMATCH[1]}"
        if [[ "$branch" != "main" ]]; then
            is_named_non_main=true
        fi
    elif [[ -z "$line" ]]; then
        if $is_named_non_main; then
            new_named_non_main=$((new_named_non_main + 1))
        elif $is_detached; then
            if [[ -z $(git -C "$current_path" status --porcelain 2>/dev/null) ]]; then
                new_detached_clean=$((new_detached_clean + 1))
            else
                new_detached_dirty=$((new_detached_dirty + 1))
            fi
        fi
    fi
done < wt_new.txt

echo "Removed count: $removed"
echo "Failures: $failures"
echo "New Totals:"
echo "  Total: $new_total"
echo "  Detached Clean: $new_detached_clean"
echo "  Detached Dirty: $new_detached_dirty"
echo "  Named non-main: $new_named_non_main"
