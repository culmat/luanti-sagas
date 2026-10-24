// Package tools runs the command line tools Forge drives, never their code: `sagas --json …` from
// the workspace's tools, and `avanti …` (Bash; Git Bash on Windows). Results are decoded from
// their JSON output.
package tools

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"

	"github.com/culmat/luanti-sagas/forge/internal/home"
	"github.com/culmat/luanti-sagas/forge/internal/proc"
)

// Logf receives the tools' progress lines (their stderr).
type Logf func(format string, args ...any)

// Error is a tool's failure: its message and exit code.
type Error struct {
	Tool     string
	Message  string
	ExitCode int
}

func (e *Error) Error() string { return e.Tool + ": " + e.Message }

// Runner runs the tools for one Forge home.
type Runner struct {
	Home home.Home
}

// Sagas runs `sagas --json args…` in the workspace and decodes its JSON into out (nil: ignore).
func (r Runner) Sagas(ctx context.Context, logf Logf, out any, args ...string) error {
	cmd := proc.Command(ctx, r.Home.Env(), r.Home.SagasCLI(), append([]string{"--json"}, args...)...)
	cmd.Dir = r.Home.Workspace()
	return run(cmd, "sagas", logf, out)
}

// Avanti runs `avanti args…` and decodes its JSON output into out (nil: ignore).
func (r Runner) Avanti(ctx context.Context, logf Logf, out any, args ...string) error {
	return r.AvantiEnv(ctx, logf, out, nil, args...)
}

// AvantiEnv is Avanti with extra environment variables (e.g. LUANTI_BIN).
func (r Runner) AvantiEnv(ctx context.Context, logf Logf, out any, env map[string]string, args ...string) error {
	cmd, err := r.avantiCommand(ctx, args...)
	if err != nil {
		return err
	}
	for k, v := range env {
		cmd.Env = append(cmd.Env, k+"="+v)
	}
	return run(cmd, "avanti", logf, out)
}

func (r Runner) avantiCommand(ctx context.Context, args ...string) (*exec.Cmd, error) {
	script := r.Home.AvantiCLI()
	if runtime.GOOS != "windows" {
		return proc.Command(ctx, r.Home.Env(), script, args...), nil
	}
	bash, err := GitBash()
	if err != nil {
		return nil, err
	}
	return proc.Command(ctx, r.Home.Env(), bash, append([]string{script}, args...)...), nil
}

// GitBash finds bash.exe of Git for Windows: next to git.exe (Git\cmd\git.exe -> Git\bin\bash.exe),
// or in the usual install folders.
func GitBash() (string, error) {
	var tries []string
	if git, err := exec.LookPath("git"); err == nil {
		root := filepath.Dir(filepath.Dir(git))
		tries = append(tries, filepath.Join(root, "bin", "bash.exe"), filepath.Join(root, "usr", "bin", "bash.exe"))
	}
	for _, env := range []string{"ProgramFiles", "ProgramW6432", "LOCALAPPDATA"} {
		if dir := os.Getenv(env); dir != "" {
			tries = append(tries, filepath.Join(dir, "Git", "bin", "bash.exe"), filepath.Join(dir, "Programs", "Git", "bin", "bash.exe"))
		}
	}
	for _, p := range tries {
		if st, err := os.Stat(p); err == nil && !st.IsDir() {
			return p, nil
		}
	}
	return "", errors.New("Git Bash not found: install Git for Windows (https://git-scm.com/download/win)")
}

// run runs cmd, streams stderr lines to logf, and decodes stdout as JSON into out. A tool that
// fails with a JSON error object ({"error", "exit_code"}) becomes an *Error with that message;
// other output of a failing tool is still decoded into out.
func run(cmd *exec.Cmd, tool string, logf Logf, out any) error {
	var stdout bytes.Buffer
	cmd.Stdout = &stdout
	errw := &lines{logf: logf}
	cmd.Stderr = errw
	err := cmd.Run()
	errw.flush()
	if err != nil {
		var fail struct {
			Error    string `json:"error"`
			ExitCode int    `json:"exit_code"`
		}
		code := -1
		var exit *exec.ExitError
		if errors.As(err, &exit) {
			code = exit.ExitCode()
		}
		if json.Unmarshal(stdout.Bytes(), &fail) == nil && fail.Error != "" {
			return &Error{Tool: tool, Message: fail.Error, ExitCode: code}
		}
		if out != nil { // a result that is also a failure, e.g. lint findings with errors (exit 3)
			_ = json.Unmarshal(stdout.Bytes(), out)
		}
		msg := strings.TrimSpace(errw.last)
		if msg == "" {
			msg = err.Error()
		}
		return &Error{Tool: tool, Message: strings.TrimPrefix(msg, "error: "), ExitCode: code}
	}
	if out == nil {
		return nil
	}
	if err := json.Unmarshal(stdout.Bytes(), out); err != nil {
		return fmt.Errorf("%s: unexpected output (%v): %.200s", tool, err, stdout.String())
	}
	return nil
}

// lines sends a stream to logf line by line and remembers the last line (the error message).
type lines struct {
	logf Logf
	buf  []byte
	last string
}

func (w *lines) Write(p []byte) (int, error) {
	w.buf = append(w.buf, p...)
	for {
		i := bytes.IndexAny(w.buf, "\r\n")
		if i < 0 {
			return len(p), nil
		}
		w.line(string(w.buf[:i]))
		w.buf = w.buf[i+1:]
	}
}

func (w *lines) line(s string) {
	s = strings.TrimSpace(s)
	if s == "" {
		return
	}
	w.last = s
	if w.logf != nil {
		w.logf("%s", s)
	}
}

func (w *lines) flush() {
	w.line(string(w.buf))
	w.buf = nil
}

var _ io.Writer = (*lines)(nil)
