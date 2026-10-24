#!/usr/bin/env bash
# Show the pictures CI made for a pull request in one comment (updated on every run).
# Usage: post-pictures.sh <pictures dir> <head sha> [<CI result>]
# The pictures dir holds meta.json ({pr, landmarks, notes}) and PNGs; they are stored on the
# `previews` branch and linked from the comment. Called by ci.yml for branches of this repository and
# by pictures.yml for forks; everything in the dir is treated as data. Needs GH_TOKEN and REPO.
set -euo pipefail
pics=$(cd "$1" && pwd)
sha=$2
result=${3:-success}

[ -f "$pics/meta.json" ] || { echo "no pictures"; exit 0; }
pr=$(jq -r '.pr' "$pics/meta.json")
[[ "$pr" =~ ^[0-9]+$ ]] || { echo "no pull request"; exit 0; }
head=$(gh pr view "$pr" -R "$REPO" --json headRefOid -q .headRefOid)
[ "$head" = "$sha" ] || { echo "pictures are for an older commit of #$pr"; exit 0; }
landmarks=()
while IFS= read -r l; do landmarks+=("$l"); done < <(jq -r '.landmarks[]' "$pics/meta.json" | grep -E '^[a-z0-9_]+/[a-z0-9_]+$' || true)
[ "${#landmarks[@]}" -gt 0 ] || { echo "no landmarks changed"; exit 0; }

dir="pr-$pr/${sha:0:12}"
work=$(mktemp -d)
git -C "$work" init -q
git -C "$work" remote add origin "https://x-access-token:${GH_TOKEN}@github.com/$REPO.git"
if git -C "$work" fetch -q --depth 1 origin previews; then
	git -C "$work" checkout -q FETCH_HEAD
else
	git -C "$work" checkout -q --orphan previews
fi
mkdir -p "$work/$dir"
find "$pics" -maxdepth 1 -type f -name '*.png' -exec cp {} "$work/$dir/" \;
git -C "$work" add -A
git -C "$work" -c user.name="github-actions[bot]" -c user.email="41898282+github-actions[bot]@users.noreply.github.com" \
	commit -q -m "Pictures for #$pr (${sha:0:12})"
git -C "$work" push -q origin HEAD:refs/heads/previews

raw="https://raw.githubusercontent.com/$REPO/previews/$dir"
{
	echo "<!-- sagas-pictures -->"
	echo "### How it looks"
	[ "$result" = success ] || echo "> Some checks did not pass (yet); see the checks below this pull request."
	for l in "${landmarks[@]}"; do
		n=${l/\//-}
		echo
		echo "**$l**"
		echo
		echo "![$l]($raw/$n.png)"
		echo
		echo "Every size next to a player and trees:"
		echo
		echo "![$l at several sizes]($raw/$n-sizes.png)"
	done
	jq -r '.notes[]' "$pics/meta.json" | cut -c1-200 | sed 's/^/> /'
	echo
	echo "Change it by commenting, one command per line (\`/help\` lists them all):"
	echo "\`/size 24\` · \`/bigger\` · \`/smaller\` · \`/site cliff+coast\` · \`/rarity rare\` · \`/door +z\`"
} >"$work/comment.md"
id=$(gh api "repos/$REPO/issues/$pr/comments" --paginate \
	--jq '.[] | select(.body | contains("<!-- sagas-pictures -->")) | .id' | head -n 1)
if [ -n "$id" ]; then
	gh api -X PATCH "repos/$REPO/issues/comments/$id" -F "body=@$work/comment.md" >/dev/null
else
	gh pr comment "$pr" -R "$REPO" --body-file "$work/comment.md"
fi
rm -rf "$work"
