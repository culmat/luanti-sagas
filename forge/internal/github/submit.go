package github

import (
	"context"
	"errors"
	"fmt"
	"net/http"
)

// Change is one changed file of a draft; Content nil deletes it.
type Change struct {
	Path    string
	Content []byte
}

// Contribution is what a draft submits.
type Contribution struct {
	Branch  string // e.g. forge/ruins-old_tower: the fork's branch
	Title   string // commit subject and pull request title
	Body    string // commit body and pull request description
	Changes []Change
}

// Result says where a contribution went.
type Result struct {
	Direct bool   `json:"direct"` // committed on main (write access)
	Commit string `json:"commit"`
	Pull   *Pull  `json:"pull,omitempty"`
	Repo   string `json:"repo"`
}

// Submit writes the contribution as one commit on top of the newest upstream main: on main itself
// for someone with write access, else on a branch of the user's fork with a pull request.
func (c *Client) Submit(ctx context.Context, upstream string, con Contribution) (Result, error) {
	if len(con.Changes) == 0 {
		return Result{}, errors.New("nothing to submit")
	}
	user, err := c.User(ctx)
	if err != nil {
		return Result{}, err
	}
	up, err := c.Repo(ctx, upstream)
	if err != nil {
		return Result{}, err
	}
	message := con.Title
	if con.Body != "" {
		message += "\n\n" + con.Body
	}
	if up.Permissions.Push {
		for attempt := 0; attempt < 3; attempt++ {
			sha, err := c.commitOnTop(ctx, upstream, upstream, up.DefaultBranch, message, con.Changes)
			if err != nil {
				return Result{}, err
			}
			err = c.SetRef(ctx, upstream, "heads/"+up.DefaultBranch, sha, false)
			if err == nil {
				return Result{Direct: true, Commit: sha, Repo: upstream}, nil
			}
			if !IsStatus(err, http.StatusUnprocessableEntity) { // 422: main moved meanwhile
				return Result{}, err
			}
		}
		return Result{}, errors.New("main kept moving; try again")
	}
	fork, err := c.Fork(ctx, upstream)
	if err != nil {
		return Result{}, err
	}
	if err := c.MergeUpstream(ctx, fork.FullName, fork.DefaultBranch); err != nil {
		return Result{}, err
	}
	sha, err := c.commitOnTop(ctx, fork.FullName, upstream, up.DefaultBranch, message, con.Changes)
	if err != nil {
		return Result{}, err
	}
	// The branch is the contributor's own: each submission replaces it with a fresh commit on main.
	if err := c.SetRef(ctx, fork.FullName, "heads/"+con.Branch, sha, true); err != nil {
		return Result{}, err
	}
	head := user.Login + ":" + con.Branch
	pull, err := c.OpenPull(ctx, upstream, head)
	if err != nil {
		return Result{}, err
	}
	if pull == nil {
		p, err := c.CreatePull(ctx, upstream, con.Title, head, up.DefaultBranch, con.Body)
		if err != nil {
			return Result{}, err
		}
		pull = &p
	}
	return Result{Commit: sha, Pull: pull, Repo: fork.FullName}, nil
}

// commitOnTop writes the changes as a commit in repo whose parent is the newest main of upstream
// (a fork shares the upstream's objects).
func (c *Client) commitOnTop(ctx context.Context, repo, upstream, branch, message string, changes []Change) (string, error) {
	base, err := c.Ref(ctx, upstream, "heads/"+branch)
	if err != nil {
		return "", err
	}
	tree, err := c.CommitTree(ctx, repo, base)
	if err != nil {
		return "", fmt.Errorf("base commit: %w", err)
	}
	entries := make([]TreeEntry, 0, len(changes))
	for _, ch := range changes {
		e := TreeEntry{Path: ch.Path, Mode: "100644", Type: "blob"}
		if ch.Content != nil {
			sha, err := c.Blob(ctx, repo, ch.Content)
			if err != nil {
				return "", fmt.Errorf("%s: %w", ch.Path, err)
			}
			e.SHA = &sha
		}
		entries = append(entries, e)
	}
	newTree, err := c.Tree(ctx, repo, tree, entries)
	if err != nil {
		return "", err
	}
	return c.Commit(ctx, repo, message, newTree, []string{base})
}
