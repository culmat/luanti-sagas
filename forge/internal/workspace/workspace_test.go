package workspace

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"testing"
)

// setup makes an "origin" repository with main and a managed clone of it.
func setup(t *testing.T) (origin string, w Workspace) {
	t.Helper()
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("git not installed")
	}
	dir := t.TempDir()
	origin = filepath.Join(dir, "origin")
	env := append(os.Environ(), "GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@x", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@x")
	run := func(dir string, args ...string) {
		t.Helper()
		cmd := exec.Command("git", args...)
		cmd.Dir, cmd.Env = dir, env
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	if err := os.MkdirAll(filepath.Join(origin, "content", "ruins", "tower"), 0o755); err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(origin, "content", "ruins", "tower", "landmark.toml"), "size = 1\n")
	write(t, filepath.Join(origin, "mods", "sagas", "init.lua"), "-- core\n")
	run(origin, "init", "--quiet", "--initial-branch=main")
	run(origin, "add", ".")
	run(origin, "commit", "--quiet", "-m", "start")
	clone := filepath.Join(dir, "clone")
	run(dir, "clone", "--quiet", origin, clone)
	return origin, Workspace{Dir: clone, Env: env, Managed: true}
}

func write(t *testing.T, path, text string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestDraftsKeepContributionsApart(t *testing.T) {
	ctx := context.Background()
	_, w := setup(t)
	if err := w.Open(ctx, "ruins-tower"); err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(w.Dir, "content", "ruins", "tower", "landmark.toml"), "size = 2\n")
	write(t, filepath.Join(w.Dir, "mods", "sagas_ruins", "schematics", "tower.mts"), "built\n")
	if err := w.Open(ctx, "vikings-ship"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(w.Dir, "mods", "sagas_ruins")); !os.IsNotExist(err) {
		t.Fatal("packs built for a tour must not survive a draft switch")
	}
	write(t, filepath.Join(w.Dir, "content", "vikings", "ship", "landmark.toml"), "size = 9\n")
	drafts, err := w.Drafts(ctx)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string][]string{}
	for _, d := range drafts {
		got[d.Name] = d.Landmarks
	}
	if !slices.Equal(got["ruins-tower"], []string{"ruins/tower"}) || !slices.Equal(got["vikings-ship"], []string{"vikings/ship"}) {
		t.Fatalf("drafts: %+v", drafts)
	}
	subject, _, err := w.Commit(ctx, "forge/ruins-tower")
	if err != nil || subject != "Work in progress" {
		t.Fatalf("commit %q %v", subject, err)
	}
	if err := w.Discard(ctx, "vikings-ship"); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(w.Dir, "content", "vikings")); !os.IsNotExist(err) {
		t.Fatal("a discarded draft leaves nothing behind")
	}
}

func TestUpdateReportsConflicts(t *testing.T) {
	ctx := context.Background()
	origin, w := setup(t)
	if err := w.Open(ctx, "tower"); err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(w.Dir, "content", "ruins", "tower", "landmark.toml"), "size = 2\n")
	write(t, filepath.Join(origin, "content", "ruins", "tower", "landmark.toml"), "size = 3\n")
	cmd := exec.Command("git", "commit", "-qam", "upstream")
	cmd.Dir, cmd.Env = origin, w.Env
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("%v %s", err, out)
	}
	var conflict *ConflictError
	if err := w.Update(ctx, ""); !errors.As(err, &conflict) || !slices.Equal(conflict.Files, []string{"content/ruins/tower/landmark.toml"}) {
		t.Fatalf("want a conflict, got %v", err)
	}
	if err := w.Update(ctx, "mine"); err != nil {
		t.Fatal(err)
	}
	b, _, _ := w.FileAt(ctx, "HEAD", "content/ruins/tower/landmark.toml")
	if string(b) != "size = 2\n" {
		t.Fatalf("kept mine: %q", b)
	}
}

func TestCloneModeTouchesNothing(t *testing.T) {
	ctx := context.Background()
	_, w := setup(t)
	w.Managed = false
	write(t, filepath.Join(w.Dir, "mods", "sagas", "init.lua"), "-- my edit\n")
	if err := w.Open(ctx, "x"); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(filepath.Join(w.Dir, "mods", "sagas", "init.lua"))
	if string(b) != "-- my edit\n" {
		t.Fatal("clone mode must not touch the user's files")
	}
}
