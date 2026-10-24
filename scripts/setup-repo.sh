#!/usr/bin/env bash
# One-time GitHub settings for self-service contributions (run by a maintainer, needs gh with admin
# rights on the repository). Safe to run again.
#   - labels from .github/labels.yml
#   - squash merges with auto-merge, branches deleted after merge
#   - a deploy key "sagas-bot" (write access, this repository only) whose private half is the
#     SAGAS_DEPLOY_KEY secret: the workflows push with it (generated packs to main, bot branches)
#   - a ruleset on main: one approving review by a code owner and green CI; deploy keys may push,
#     admins may merge their own pull requests (personal repositories can't let the Actions bot
#     bypass a ruleset, only organizations can)
#   - the contentdb environment without required reviewers, so releases go out after the merge
set -euo pipefail
repo=${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}
cd "$(git rev-parse --show-toplevel)"

echo "labels"
sed -n 's/^- { name: "\([^"]*\)", color: "\([^"]*\)", description: "\([^"]*\)" }$/\1|\2|\3/p' .github/labels.yml |
	while IFS='|' read -r name color description; do
		gh label create "$name" --color "$color" --description "$description" --force -R "$repo" >/dev/null
	done

echo "merging"
gh repo edit "$repo" --enable-squash-merge --enable-auto-merge --delete-branch-on-merge >/dev/null

echo "deploy key for the workflows"
if gh secret list -R "$repo" | grep -q '^SAGAS_DEPLOY_KEY'; then
	echo "  SAGAS_DEPLOY_KEY exists (delete the secret and the deploy key to rotate)"
else
	tmp=$(mktemp -d)
	ssh-keygen -q -t ed25519 -N "" -C "sagas-bot@$repo" -f "$tmp/key"
	gh repo deploy-key add "$tmp/key.pub" --allow-write --title sagas-bot -R "$repo" >/dev/null
	gh secret set SAGAS_DEPLOY_KEY -R "$repo" <"$tmp/key"
	rm -rf "$tmp"
fi

echo "ruleset on main"
ruleset=$(
	cat <<'JSON'
{
  "name": "main: one approval, green CI",
  "target": "branch",
  "enforcement": "active",
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "bypass_actors": [
    { "actor_id": null, "actor_type": "DeployKey", "bypass_mode": "always" },
    { "actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request" }
  ],
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "pull_request", "parameters": {
        "required_approving_review_count": 1,
        "require_code_owner_review": true,
        "dismiss_stale_reviews_on_push": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false } },
    { "type": "required_status_checks", "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [
          { "context": "tools (ruff, pytest)" },
          { "context": "content (lint, build, pictures)" } ] } }
  ]
}
JSON
)
existing=$(gh api "repos/$repo/rulesets" --jq '.[] | select(.name == "main: one approval, green CI") | .id')
if [ -n "$existing" ]; then
	gh api -X PUT "repos/$repo/rulesets/$existing" --input - <<<"$ruleset" --jq .name
else
	gh api -X POST "repos/$repo/rulesets" --input - <<<"$ruleset" --jq .name
fi

echo "contentdb environment without reviewers"
gh api -X PUT "repos/$repo/environments/contentdb" --input - <<<'{"reviewers": [], "wait_timer": 0}' --jq .name

echo "done: $repo"
