// Package workspace keeps contributions apart as drafts in Forge's own luanti-sagas clone, with git
// through its command line: a draft is a branch forge/<name> started from origin/main, saved by
// committing what changed under content/. Packs that a tour builds into mods/ are never kept: CI
// builds them. In clone mode (a clone of the user's) Forge only reads git; the user commits.
package workspace

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os/exec"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/culmat/luanti-sagas/forge/internal/proc"
)

// Prefix of draft branches.
const Prefix = "forge/"

// Base is the branch drafts start from and are compared with.
const Base = "origin/main"

var nameRE = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]{0,62}$`)

// Workspace is one luanti-sagas checkout.
type Workspace struct {
	Dir string
	Env []string
	// Managed is false for a clone of the user's: no branch switching, no cleaning, no commits.
	Managed bool
}

// ErrConflict means an update touched the same files as the draft.
var ErrConflict = errors.New("the draft and main changed the same files")

// ConflictError lists the files of an ErrConflict.
type ConflictError struct{ Files []string }

func (e *ConflictError) Error() string {
	return fmt.Sprintf("%v: %s", ErrConflict, strings.Join(e.Files, ", "))
}

func (e *ConflictError) Unwrap() error { return ErrConflict }

func (w Workspace) git(ctx context.Context, args ...string) (string, error) {
	cmd := proc.Command(ctx, w.Env, "git", append([]string{"-C", w.Dir}, args...)...)
	var out, errb bytes.Buffer
	cmd.Stdout, cmd.Stderr = &out, &errb
	if err := cmd.Run(); err != nil {
		msg := strings.TrimSpace(errb.String())
		if msg == "" {
			msg = err.Error()
		}
		return out.String(), fmt.Errorf("git %s: %s", args[0], msg)
	}
	return strings.TrimRight(out.String(), "\n"), nil
}

// Branch is the checked-out branch ("" when detached).
func (w Workspace) Branch(ctx context.Context) (string, error) {
	out, err := w.git(ctx, "rev-parse", "--abbrev-ref", "HEAD")
	if out == "HEAD" {
		out = ""
	}
	return out, err
}

// Draft is a branch with work in it.
type Draft struct {
	Name      string    `json:"name"`
	Branch    string    `json:"branch"`
	Current   bool      `json:"current"`
	Landmarks []string  `json:"landmarks"` // <saga>/<id> touched, compared with main
	Files     []string  `json:"files"`
	Updated   time.Time `json:"updated"`
}

// Drafts lists the forge/* branches, newest first.
func (w Workspace) Drafts(ctx context.Context) ([]Draft, error) {
	out, err := w.git(ctx, "for-each-ref", "--format=%(refname:short)\t%(committerdate:iso-strict)", "refs/heads/"+Prefix)
	if err != nil {
		return nil, err
	}
	cur, _ := w.Branch(ctx)
	var drafts []Draft
	for _, line := range strings.Split(out, "\n") {
		branch, date, ok := strings.Cut(line, "\t")
		if !ok {
			continue
		}
		files, err := w.ChangedFiles(ctx, branch)
		if err != nil {
			return nil, err
		}
		if branch == cur {
			dirty, err := w.Uncommitted(ctx)
			if err != nil {
				return nil, err
			}
			files = union(files, dirty)
		}
		t, _ := time.Parse(time.RFC3339, date)
		drafts = append(drafts, Draft{
			Name: strings.TrimPrefix(branch, Prefix), Branch: branch, Current: branch == cur,
			Landmarks: Landmarks(files), Files: files, Updated: t,
		})
	}
	sort.Slice(drafts, func(i, j int) bool { return drafts[i].Updated.After(drafts[j].Updated) })
	return drafts, nil
}

// ChangedFiles lists what rev changed under content/ since it left main.
func (w Workspace) ChangedFiles(ctx context.Context, rev string) ([]string, error) {
	out, err := w.git(ctx, "diff", "--name-only", Base+"..."+rev, "--", "content")
	if err != nil {
		return nil, err
	}
	return splitLines(out), nil
}

// Uncommitted lists changed and new files under content/ that are not committed yet.
func (w Workspace) Uncommitted(ctx context.Context) ([]string, error) {
	out, err := w.git(ctx, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--", "content")
	if err != nil {
		return nil, err
	}
	var files []string
	entries := strings.Split(out, "\x00")
	for i := 0; i < len(entries); i++ {
		e := entries[i]
		if len(e) < 4 {
			continue
		}
		files = append(files, e[3:])
		if e[0] == 'R' || e[0] == 'C' { // the next entry is the old name
			i++
		}
	}
	sort.Strings(files)
	return files, nil
}

// Landmarks are the <saga>/<id> of content/<saga>/<id>/… files.
func Landmarks(files []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, f := range files {
		parts := strings.Split(f, "/")
		if len(parts) >= 4 && parts[0] == "content" {
			sel := parts[1] + "/" + parts[2]
			if !seen[sel] {
				seen[sel] = true
				out = append(out, sel)
			}
		}
	}
	sort.Strings(out)
	return out
}

// Open switches to the draft `name`, creating it from main. Work on the current draft is saved
// first and packs built for tours are dropped.
func (w Workspace) Open(ctx context.Context, name string) error {
	if !w.Managed {
		return nil
	}
	if !nameRE.MatchString(name) {
		return fmt.Errorf("draft name %q: lowercase letters, digits, - and _", name)
	}
	if err := w.Save(ctx, "Work in progress"); err != nil {
		return err
	}
	if err := w.Tidy(ctx); err != nil {
		return err
	}
	branch := Prefix + name
	if _, err := w.git(ctx, "rev-parse", "--verify", "--quiet", "refs/heads/"+branch); err == nil {
		_, err = w.git(ctx, "checkout", "--quiet", branch)
		return err
	}
	if _, err := w.git(ctx, "fetch", "--quiet", "origin"); err != nil {
		return err
	}
	_, err := w.git(ctx, "checkout", "--quiet", "--no-track", "-b", branch, Base)
	return err
}

// Save commits what changed under content/ on the current draft (nothing to do: no commit).
func (w Workspace) Save(ctx context.Context, message string) error {
	if !w.Managed {
		return nil
	}
	branch, err := w.Branch(ctx)
	if err != nil {
		return err
	}
	dirty, err := w.Uncommitted(ctx)
	if err != nil || len(dirty) == 0 {
		return err
	}
	if !strings.HasPrefix(branch, Prefix) {
		return fmt.Errorf("changes under content/ on %q, which is not a draft", branch)
	}
	if _, err := w.git(ctx, "add", "--all", "--", "content"); err != nil {
		return err
	}
	_, err = w.git(ctx, "-c", "user.name=Saga Forge", "-c", "user.email=sagaforge@users.noreply.github.com",
		"commit", "--quiet", "--no-verify", "-m", message)
	return err
}

// Tidy drops what tours and builds wrote outside content/ (mods/, docs/gallery), so a draft only
// holds contributions.
func (w Workspace) Tidy(ctx context.Context) error {
	if !w.Managed {
		return nil
	}
	for _, dir := range []string{"mods", "docs"} {
		if tracked, _ := w.git(ctx, "ls-tree", "--name-only", "HEAD", dir); tracked != "" {
			if _, err := w.git(ctx, "checkout", "--quiet", "HEAD", "--", dir); err != nil {
				return err
			}
		}
		if _, err := w.git(ctx, "clean", "--quiet", "-fd", "--", dir); err != nil {
			return err
		}
	}
	return nil
}

// Update brings the current draft onto the newest main. keep decides conflicts: "" stops and
// reports them, "mine" keeps the draft's version, "theirs" takes main's.
func (w Workspace) Update(ctx context.Context, keep string) error {
	if !w.Managed {
		return nil
	}
	if err := w.Save(ctx, "Work in progress"); err != nil {
		return err
	}
	if err := w.Tidy(ctx); err != nil {
		return err
	}
	if _, err := w.git(ctx, "fetch", "--quiet", "origin"); err != nil {
		return err
	}
	branch, err := w.Branch(ctx)
	if err != nil {
		return err
	}
	if !strings.HasPrefix(branch, Prefix) {
		_, err := w.git(ctx, "checkout", "--quiet", "--detach", Base)
		return err
	}
	args := []string{"-c", "user.name=Saga Forge", "-c", "user.email=sagaforge@users.noreply.github.com", "rebase", "--quiet"}
	switch keep {
	case "mine":
		args = append(args, "-X", "theirs") // in a rebase, "theirs" is the draft being replayed
	case "theirs":
		args = append(args, "-X", "ours")
	case "":
	default:
		return fmt.Errorf("keep: mine or theirs, not %q", keep)
	}
	if _, err := w.git(ctx, append(args, Base)...); err != nil {
		files, _ := w.git(ctx, "diff", "--name-only", "--diff-filter=U")
		_, _ = w.git(ctx, "rebase", "--abort")
		if f := splitLines(files); len(f) > 0 {
			return &ConflictError{Files: f}
		}
		return err
	}
	return nil
}

// Discard deletes a draft (switching to main first when it is the current one).
func (w Workspace) Discard(ctx context.Context, name string) error {
	if !w.Managed {
		return errors.New("drafts live in Forge's own copy, not in an opened folder")
	}
	branch := Prefix + name
	if cur, _ := w.Branch(ctx); cur == branch {
		if _, err := w.git(ctx, "checkout", "--quiet", "--force", "--detach", Base); err != nil {
			return err
		}
		if _, err := w.git(ctx, "clean", "--quiet", "-fd", "--", "content"); err != nil {
			return err
		}
	}
	_, err := w.git(ctx, "branch", "--quiet", "-D", branch)
	return err
}

// Commit is the latest commit of rev: the message Forge reuses when it submits.
func (w Workspace) Commit(ctx context.Context, rev string) (subject, body string, err error) {
	out, err := w.git(ctx, "log", "-1", "--format=%s%x00%b", rev)
	if err != nil {
		return "", "", err
	}
	subject, body, _ = strings.Cut(out, "\x00")
	return subject, strings.TrimSpace(body), nil
}

// FileAt reads a file as committed in rev ("" when it does not exist there).
func (w Workspace) FileAt(ctx context.Context, rev, path string) ([]byte, bool, error) {
	cmd := proc.Command(ctx, w.Env, "git", "-C", w.Dir, "show", rev+":"+path)
	var out bytes.Buffer
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		var exit *exec.ExitError
		if errors.As(err, &exit) {
			return nil, false, nil
		}
		return nil, false, err
	}
	return out.Bytes(), true, nil
}

// MergeBase is where rev left main.
func (w Workspace) MergeBase(ctx context.Context, rev string) (string, error) {
	return w.git(ctx, "merge-base", Base, rev)
}

// Rev resolves a revision to a commit id.
func (w Workspace) Rev(ctx context.Context, rev string) (string, error) {
	return w.git(ctx, "rev-parse", rev)
}

// Fetch updates origin/main.
func (w Workspace) Fetch(ctx context.Context) error {
	_, err := w.git(ctx, "fetch", "--quiet", "origin")
	return err
}

func splitLines(s string) []string {
	var out []string
	for _, l := range strings.Split(s, "\n") {
		if l = strings.TrimSpace(l); l != "" {
			out = append(out, l)
		}
	}
	return out
}

func union(a, b []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range append(append([]string{}, a...), b...) {
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	sort.Strings(out)
	return out
}

// Change is a file a draft adds, changes or deletes under content/.
type Change struct {
	Path    string `json:"path"`
	Status  string `json:"status"` // A, M or D
	Deleted bool   `json:"deleted"`
}

// Changes lists what rev changed under content/ since it left main.
func (w Workspace) Changes(ctx context.Context, rev string) ([]Change, error) {
	out, err := w.git(ctx, "diff", "--name-status", "--no-renames", Base+"..."+rev, "--", "content")
	if err != nil {
		return nil, err
	}
	var changes []Change
	for _, line := range splitLines(out) {
		status, path, ok := strings.Cut(line, "\t")
		if !ok {
			continue
		}
		changes = append(changes, Change{Path: path, Status: status[:1], Deleted: status[:1] == "D"})
	}
	return changes, nil
}

// Rename renames a draft (the current one stays checked out).
func (w Workspace) Rename(ctx context.Context, from, to string) error {
	if !w.Managed || from == to {
		return nil
	}
	if !nameRE.MatchString(to) {
		return fmt.Errorf("draft name %q: lowercase letters, digits, - and _", to)
	}
	_, err := w.git(ctx, "branch", "-m", Prefix+from, Prefix+to)
	return err
}

// Exists reports whether the draft exists.
func (w Workspace) Exists(ctx context.Context, name string) bool {
	_, err := w.git(ctx, "rev-parse", "--verify", "--quiet", "refs/heads/"+Prefix+name)
	return err == nil
}
