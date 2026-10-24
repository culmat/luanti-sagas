#!/usr/bin/env bash
# Release the modpack when its files changed since the last release: a GitHub release with the zip,
# then ContentDB. Called by .github/workflows/deliver.yml after the packs are built on main, so one
# approved pull request (or a push by a maintainer) is the only human step. There is one ContentDB
# package, culmat/sagas: the modpack in mods/ with the core mod and every saga (docs/releasing.md).
# Versions are dates, tagged v2026.10.24, then v2026.10.24.2 (per-package tags before 2026-10-24 are history).
#
# Environment: GH_TOKEN (gh, and pushing tags), CONTENTDB_TOKEN and AVANTI_CONTENTDB_USER (without a
# token, ContentDB is skipped and the run says what it would release), AVANTI (path to the avanti
# CLI), DRY_RUN=1 to only print the plan.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

dir=mods
pkg=$(sed -n 's/^[[:space:]]*name[[:space:]]*=[[:space:]]*\([^[:space:]]*\).*/\1/p' "$dir/modpack.conf" | head -n 1)
today=$(date -u +%Y.%m.%d)
sagas() { uv run --project tools sagas "$@"; }

# Tags go out with the workflow token: its pushes start no workflow, so release.yml (for manual
# tags) doesn't release the same version again.
push_tag() {
	if [ -n "${GITHUB_REPOSITORY:-}" ]; then
		git push -q "https://x-access-token:${GH_TOKEN}@github.com/$GITHUB_REPOSITORY.git" "refs/tags/$1"
	else
		git push -q origin "refs/tags/$1"
	fi
}

last_tag() { git tag -l "v[0-9]*" --sort=-creatordate | head -n 1; }

next_version() {
	local v=$today n=2
	while git rev-parse -q --verify "refs/tags/v$v" >/dev/null; do
		v="$today.$n"
		n=$((n + 1))
	done
	echo "$v"
}

# Exported files only: what .gitattributes export-ignores never reaches players.
changed() {
	local tag
	tag=$(last_tag)
	[ -z "$tag" ] && return 0
	! git diff --quiet "$tag" HEAD -- "$dir" ':!mods/tools' ':!mods/screenshots' ':!mods/sagas/test'
}

# New and updated landmarks per saga, changes to the core mod, and who contributed (commit authors
# and Co-authored-by trailers).
notes() {
	local tag range saga list
	tag=$(last_tag)
	range=${tag:+$tag..}HEAD
	for d in mods/sagas_*/; do
		saga=$(basename "$d")
		saga=${saga#sagas_}
		if [ -n "$tag" ]; then
			list=$(git diff --name-status "$tag" HEAD -- "content/$saga" |
				awk '$2 ~ /landmark.toml$/ { split($2, p, "/"); print ($1 == "A" ? "- New: " : "- Updated: ") p[3] }')
		else
			list=$(git ls-files "content/$saga" | awk -F/ '/landmark.toml$/ { print "- New: " $3 }')
		fi
		[ -n "$list" ] && printf '### %s\n\n%s\n\n' "$saga" "$list"
	done
	list=$(git log --format='- %s' "$range" -- mods/sagas ':!mods/sagas/test' | grep -v -e '^- Build packs and previews' | head -n 20 || true)
	[ -n "$list" ] && printf '### The sagas mod\n\n%s\n\n' "$list"
	echo "Thanks to: $(
		git log --format='%an%n%(trailers:key=Co-authored-by,valueonly)' "$range" -- content mods/sagas |
			sed 's/ <.*//' | grep -v -e '^$' -e 'github-actions' | sort -u | paste -sd ',' - | sed 's/,/, /g'
	)"
}

contentdb() {
	local version=$1 commit ref
	if [ -z "${CONTENTDB_TOKEN:-}" ]; then
		echo "  ContentDB: no token here; would release $pkg $version from $dir"
		return 0
	fi
	# ContentDB imports a git ref of the whole repository: tag the modpack folder's tree on its own.
	commit=$(git commit-tree "$(git rev-parse "HEAD:$dir")" -p HEAD -m "$pkg $version: package tree of $(git rev-parse HEAD)")
	ref="cdb/$pkg/$version"
	git tag -a "$ref" "$commit" -m "$pkg $version for ContentDB"
	push_tag "$ref"
	"$AVANTI" cdb release "$ref" "$dir" --title "$version" --notes-file "dist/$pkg-notes.md"
}

if ! changed; then
	echo "nothing changed since $(last_tag)"
	exit 0
fi
version=$(next_version)
tag="v$version"
echo "== $tag"
mkdir -p dist
notes >"dist/$pkg-notes.md" # before tagging: "since the last release" must not see this one
if [ -n "${DRY_RUN:-}" ]; then
	sed 's/^/   /' "dist/$pkg-notes.md"
	exit 0
fi
sagas package pack --version "$version" --out dist
git tag -a "$tag" -m "$pkg $version"
push_tag "$tag"
gh release create "$tag" "dist/$pkg-$version.zip" --title "$pkg $version" --notes-file "dist/$pkg-notes.md"
contentdb "$version"
