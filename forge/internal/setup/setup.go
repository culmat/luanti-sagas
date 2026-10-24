// Package setup installs and updates what Saga Forge drives: git (through the system's package
// manager), uv and jq (pinned, checksum-verified downloads), the avanti-luanti and luanti-sagas
// clones, ldg with its dependency snapshot, and the sagas tools' Python environment. Every step
// checks first and does nothing when it is already done.
package setup

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"time"

	"github.com/culmat/luanti-sagas/forge/internal/home"
	"github.com/culmat/luanti-sagas/forge/internal/proc"
)

// ForgeAPI is the `sagas --json version` forge_api this Forge speaks.
const ForgeAPI = 1

const userAgent = "sagaforge (+https://github.com/culmat/luanti-sagas)"

// Repositories Forge clones.
const (
	AvantiURL = "https://github.com/culmat/avanti-luanti.git"
	SagasURL  = "https://github.com/culmat/luanti-sagas.git"
	LdgSource = "git+https://github.com/culmat/luanti-depgraph"
)

// ErrNeedsUser means a step started something the user has to finish (an installer window), after
// which setup runs again.
var ErrNeedsUser = errors.New("waiting for you")

// Logf receives progress lines.
type Logf func(format string, args ...any)

// Step is one part of the setup.
type Step struct {
	Name string
	Done func(ctx context.Context) bool
	Run  func(ctx context.Context, logf Logf) error
}

// Setup holds what the steps need.
type Setup struct {
	Home   home.Home
	Client *http.Client
	// Update pulls the clones and refreshes ldg's snapshot even when they exist.
	Update bool
}

// New returns a Setup for h.
func New(h home.Home) *Setup {
	return &Setup{Home: h, Client: &http.Client{Timeout: 10 * time.Minute}}
}

// Steps lists the steps in order.
func (s *Setup) Steps() []Step {
	h := s.Home
	return []Step{
		{"git", s.hasGit, s.installGit},
		{"uv " + uvVersion, func(ctx context.Context) bool {
			return versionIs(ctx, h, filepath.Join(h.Bin(), home.Exe("uv")), uvVersion)
		}, s.installUV},
		{"jq " + jqVersion, func(ctx context.Context) bool {
			return versionIs(ctx, h, filepath.Join(h.Bin(), home.Exe("jq")), jqVersion)
		}, s.installJQ},
		{"avanti-luanti", func(context.Context) bool { return !s.Update && isRepo(h.Avanti()) }, func(ctx context.Context, logf Logf) error {
			return s.cloneOrPull(ctx, logf, AvantiURL, h.Avanti())
		}},
		{"luanti-sagas", func(context.Context) bool { return h.CloneMode() || (!s.Update && isRepo(h.Workspace())) }, func(ctx context.Context, logf Logf) error {
			return s.cloneOrFetch(ctx, logf, SagasURL, h.Workspace())
		}},
		{"ldg", s.hasLdg, s.installLdg},
		{"sagas tools", s.toolsReady, s.syncTools},
	}
}

// Run runs every step that is not done yet, in order, and stops at the first failure.
func (s *Setup) Run(ctx context.Context, logf Logf) error {
	for _, st := range s.Steps() {
		if st.Done(ctx) {
			logf("ok   %s", st.Name)
			continue
		}
		logf("...  %s", st.Name)
		if err := st.Run(ctx, logf); err != nil {
			return fmt.Errorf("%s: %w", st.Name, err)
		}
		logf("ok   %s", st.Name)
	}
	return s.checkAPI(ctx)
}

// Missing lists the steps that are not done.
func (s *Setup) Missing(ctx context.Context) []string {
	var out []string
	for _, st := range s.Steps() {
		if !st.Done(ctx) {
			out = append(out, st.Name)
		}
	}
	return out
}

func (s *Setup) command(ctx context.Context, name string, args ...string) *exec.Cmd {
	return proc.Command(ctx, s.Home.Env(), name, args...)
}

// run runs a command, sending its output lines to logf.
func (s *Setup) run(ctx context.Context, logf Logf, dir, name string, args ...string) error {
	cmd := s.command(ctx, name, args...)
	cmd.Dir = dir
	w := &lineWriter{logf: logf}
	cmd.Stdout, cmd.Stderr = w, w
	err := cmd.Run()
	w.flush()
	if err != nil {
		return fmt.Errorf("%s %s: %w", filepath.Base(name), strings.Join(args, " "), err)
	}
	return nil
}

func versionIs(ctx context.Context, h home.Home, bin, want string) bool {
	out, err := proc.Command(ctx, h.Env(), bin, "--version").Output()
	return err == nil && strings.Contains(string(out), want)
}

func isRepo(dir string) bool {
	_, err := os.Stat(filepath.Join(dir, ".git"))
	return err == nil
}

// ---------------------------------------------------------------- git

func (s *Setup) hasGit(ctx context.Context) bool {
	return s.command(ctx, "git", "--version").Run() == nil
}

func (s *Setup) installGit(ctx context.Context, logf Logf) error {
	switch runtime.GOOS {
	case "windows":
		logf("installing Git for Windows with winget (a window may ask for permission)")
		err := s.run(ctx, logf, "", "winget", "install", "--id", "Git.Git", "-e", "--source", "winget",
			"--accept-package-agreements", "--accept-source-agreements", "--silent")
		if err != nil {
			return fmt.Errorf("%w; install Git from https://git-scm.com/download/win and start Saga Forge again", err)
		}
		if !s.hasGit(ctx) {
			return fmt.Errorf("%w: Git is installed; close and start Saga Forge again so it is found", ErrNeedsUser)
		}
		return nil
	case "darwin":
		_ = s.command(ctx, "xcode-select", "--install").Run()
		return fmt.Errorf("%w: a window offers Apple's command line tools (they include git); install them, then press Retry", ErrNeedsUser)
	default:
		return fmt.Errorf("%w: install git with your package manager (e.g. sudo apt install git), then press Retry", ErrNeedsUser)
	}
}

// ---------------------------------------------------------------- uv, jq

func (s *Setup) installUV(ctx context.Context, logf Logf) error {
	p, err := uvDownload()
	if err != nil {
		return err
	}
	archive := filepath.Join(s.Home.Cache(), filepath.Base(p.url))
	logf("downloading %s", p.url)
	if err := fetch(ctx, s.Client, p, archive); err != nil {
		return err
	}
	defer os.Remove(archive)
	return extract(archive, s.Home.Bin(), home.Exe("uv"), home.Exe("uvx"))
}

func (s *Setup) installJQ(ctx context.Context, logf Logf) error {
	p, err := jqDownload()
	if err != nil {
		return err
	}
	logf("downloading %s", p.url)
	dest := filepath.Join(s.Home.Bin(), home.Exe("jq"))
	if err := fetch(ctx, s.Client, p, dest); err != nil {
		return err
	}
	return os.Chmod(dest, 0o755)
}

// ---------------------------------------------------------------- clones

func (s *Setup) cloneOrPull(ctx context.Context, logf Logf, url, dir string) error {
	if isRepo(dir) {
		logf("updating %s", filepath.Base(dir))
		return s.run(ctx, logf, dir, "git", "pull", "--ff-only", "--quiet")
	}
	return s.clone(ctx, logf, url, dir)
}

// cloneOrFetch leaves the checked-out branch alone: drafts live on branches, and updating them is
// the workspace's job.
func (s *Setup) cloneOrFetch(ctx context.Context, logf Logf, url, dir string) error {
	if isRepo(dir) {
		logf("fetching %s", filepath.Base(dir))
		return s.run(ctx, logf, dir, "git", "fetch", "--quiet", "origin")
	}
	return s.clone(ctx, logf, url, dir)
}

func (s *Setup) clone(ctx context.Context, logf Logf, url, dir string) error {
	logf("cloning %s", url)
	if err := os.MkdirAll(filepath.Dir(dir), 0o755); err != nil {
		return err
	}
	return s.run(ctx, logf, "", "git", "clone", "--quiet", "--filter=blob:none", url, dir)
}

// ---------------------------------------------------------------- ldg

func (s *Setup) ldg() string { return filepath.Join(s.Home.ToolsBin(), home.Exe("ldg")) }

func (s *Setup) ldgStamp() string { return filepath.Join(s.Home.State(), "ldg-updated") }

func (s *Setup) hasLdg(ctx context.Context) bool {
	if s.Update {
		return false
	}
	if s.command(ctx, s.ldg(), "--help").Run() != nil {
		return false
	}
	st, err := os.Stat(s.ldgStamp())
	return err == nil && time.Since(st.ModTime()) < 7*24*time.Hour
}

func (s *Setup) installLdg(ctx context.Context, logf Logf) error {
	uv := filepath.Join(s.Home.Bin(), home.Exe("uv"))
	if s.command(ctx, s.ldg(), "--help").Run() != nil || s.Update {
		logf("installing ldg (luanti-depgraph)")
		if err := s.run(ctx, logf, "", uv, "tool", "install", "--quiet", "--force", "--python", "3.12", LdgSource); err != nil {
			return err
		}
	}
	logf("downloading ldg's dependency snapshot")
	if err := s.run(ctx, logf, "", s.ldg(), "update"); err != nil {
		return err
	}
	if err := os.MkdirAll(s.Home.State(), 0o755); err != nil {
		return err
	}
	return os.WriteFile(s.ldgStamp(), []byte(time.Now().UTC().Format(time.RFC3339)+"\n"), 0o644)
}

// ---------------------------------------------------------------- sagas tools

func (s *Setup) lockFile() string { return filepath.Join(s.Home.Workspace(), "tools", "uv.lock") }

func (s *Setup) toolsStamp() string { return filepath.Join(s.Home.Venv(), ".sagaforge-lock") }

func (s *Setup) toolsReady(context.Context) bool {
	lock, err := os.ReadFile(s.lockFile())
	if err != nil {
		return false
	}
	stamp, err := os.ReadFile(s.toolsStamp())
	_, cli := os.Stat(s.Home.SagasCLI())
	return err == nil && cli == nil && bytes.Equal(lock, stamp)
}

func (s *Setup) syncTools(ctx context.Context, logf Logf) error {
	uv := filepath.Join(s.Home.Bin(), home.Exe("uv"))
	logf("installing the sagas tools (Python and its libraries, about 150 MB the first time)")
	tools := filepath.Join(s.Home.Workspace(), "tools")
	if err := s.run(ctx, logf, tools, uv, "sync", "--locked", "--no-dev", "--quiet", "--python", "3.12", "--project", tools); err != nil {
		return err
	}
	lock, err := os.ReadFile(s.lockFile())
	if err != nil {
		return err
	}
	return os.WriteFile(s.toolsStamp(), lock, 0o644)
}

// checkAPI makes sure the workspace's tools speak this Forge's language.
func (s *Setup) checkAPI(ctx context.Context) error {
	out, err := s.command(ctx, s.Home.SagasCLI(), "--json", "version").Output()
	if err != nil {
		return fmt.Errorf("sagas version: %w", err)
	}
	var v struct {
		Version  string `json:"version"`
		ForgeAPI int    `json:"forge_api"`
	}
	if err := json.Unmarshal(out, &v); err != nil {
		return fmt.Errorf("sagas version: %w", err)
	}
	if v.ForgeAPI != ForgeAPI {
		return fmt.Errorf("the sagas tools (%s) speak Forge API %d, this Saga Forge speaks %d: update Saga Forge or the workspace", v.Version, v.ForgeAPI, ForgeAPI)
	}
	return nil
}

// lineWriter turns command output into log lines.
type lineWriter struct {
	logf Logf
	buf  []byte
}

func (w *lineWriter) Write(p []byte) (int, error) {
	w.buf = append(w.buf, p...)
	for {
		i := bytes.IndexAny(w.buf, "\r\n")
		if i < 0 {
			break
		}
		if line := strings.TrimSpace(string(w.buf[:i])); line != "" {
			w.logf("     %s", line)
		}
		w.buf = w.buf[i+1:]
	}
	return len(p), nil
}

func (w *lineWriter) flush() {
	if line := strings.TrimSpace(string(w.buf)); line != "" {
		w.logf("     %s", line)
	}
	w.buf = nil
}
