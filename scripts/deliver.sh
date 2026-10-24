#!/usr/bin/env bash
# Release every package whose files changed since its last release: a GitHub release with the zip,
# then ContentDB. Called by .github/workflows/deliver.yml after the packs are built on main, so one
# approved pull request is the only human step. Versions are dates: 2026.10.24, then 2026.10.24.2.
#
# Environment: GH_TOKEN (gh), CONTENTDB_TOKEN and AVANTI_CONTENTDB_USER (without a token, ContentDB
# is skipped and the run says what it would release), AVANTI (path to the avanti CLI),
# DRY_RUN=1 to only print the plan.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

today=$(date -u +%Y.%m.%d)
sagas() { uv run --project tools sagas "$@"; }

dir_of() { if [ "$1" = sagas_pack ]; then echo mods; else echo "mods/$1"; fi; }

last_tag() { git tag -l "$1-v*" --sort=-creatordate | head -n 1; }

next_version() {
	local v=$today n=2
	while git rev-parse -q --verify "refs/tags/$1-v$v" >/dev/null; do
		v="$today.$n"
		n=$((n + 1))
	done
	echo "$v"
}

# Exported files only: what .gitattributes export-ignores never reaches players.
changed() {
	local tag
	tag=$(last_tag "$1")
	[ -z "$tag" ] && return 0
	! git diff --quiet "$tag" HEAD -- "$(dir_of "$1")" ':!mods/tools' ':!mods/screenshots' ':!mods/sagas/test'
}

# New and updated landmarks, and who contributed them (commit authors and Co-authored-by trailers).
notes() {
	local pkg=$1 tag saga range
	tag=$(last_tag "$pkg")
	range=${tag:+$tag..}HEAD
	case "$pkg" in
	sagas_pack) echo "All sagas in one modpack." ;;
	sagas) git log --format='- %s' "$range" -- mods/sagas tools | head -n 30 ;;
	*)
		saga=${pkg#sagas_}
		if [ -n "$tag" ]; then
			git diff --name-status "$tag" HEAD -- "content/$saga" |
				awk '$2 ~ /landmark.toml$/ { split($2, p, "/"); print ($1 == "A" ? "- New: " : "- Updated: ") p[3] }'
		else
			git ls-files "content/$saga" | awk -F/ '/landmark.toml$/ { print "- New: " $3 }'
		fi
		echo
		echo "Thanks to: $(
			git log --format='%an%n%(trailers:key=Co-authored-by,valueonly)' "$range" -- "content/$saga" |
				sed 's/ <.*//' | grep -v -e '^$' -e 'github-actions' | sort -u | paste -sd ', ' -
		)"
		;;
	esac
}

contentdb() {
	local pkg=$1 version=$2 dir commit ref
	dir=$(dir_of "$pkg")
	if [ -z "${CONTENTDB_TOKEN:-}" ]; then
		echo "  ContentDB: no token here; would release $pkg $version from $dir"
		return 0
	fi
	# ContentDB imports a git ref of the whole repository: tag the package folder's tree on its own.
	commit=$(git commit-tree "$(git rev-parse "HEAD:$dir")" -p HEAD -m "$pkg $version: package tree of $(git rev-parse HEAD)")
	ref="cdb/$pkg/$version"
	git tag -a "$ref" "$commit" -m "$pkg $version for ContentDB"
	git push -q origin "refs/tags/$ref"
	if ! "$AVANTI" cdb release "$ref" "$dir" --title "$version"; then
		echo "::warning::ContentDB release of $pkg $version failed"
		local title="ContentDB: create the package $pkg"
		if ! gh issue list --state open --search "\"$title\" in:title" --json number -q '.[0].number' | grep -q .; then
			gh issue create --title "$title" --body "deliver.sh could not release \`$pkg\` $version to ContentDB. A new saga needs its ContentDB package created once by a maintainer (docs/releasing.md); the next release after that goes out on its own. Until then the saga ships in \`sagas_pack\`." || true
		fi
	fi
}

release() {
	local pkg=$1 version name tag
	version=$(next_version "$pkg")
	tag="$pkg-v$version"
	echo "== $tag"
	if [ -n "${DRY_RUN:-}" ]; then
		notes "$pkg" | sed 's/^/   /'
		return 0
	fi
	if [ "$pkg" = sagas_pack ]; then name=pack; else name=$pkg; fi
	sagas package "$name" --version "$version" --out dist
	git tag -a "$tag" -m "$pkg $version"
	git push -q origin "refs/tags/$tag"
	notes "$pkg" >"dist/$pkg-notes.md"
	gh release create "$tag" "dist/$pkg-$version.zip" --title "$pkg $version" --notes-file "dist/$pkg-notes.md"
	contentdb "$pkg" "$version"
}

packages=(sagas)
for d in mods/sagas_*/; do
	[ -f "$d/mod.conf" ] && packages+=("$(basename "$d")")
done
any=
for pkg in "${packages[@]}"; do
	if changed "$pkg"; then
		release "$pkg"
		any=1
	fi
done
# the modpack carries everything, so it follows whenever one of its mods changed
if [ -n "$any" ] || changed sagas_pack; then release sagas_pack; fi
[ -n "$any" ] || echo "nothing changed since the last releases"
