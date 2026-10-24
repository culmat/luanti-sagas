package tools

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"

	"github.com/culmat/luanti-sagas/forge/internal/proc"
)

// Saga is a theme with its landmarks (sagas --json catalog).
type Saga struct {
	ID             string `json:"id"`
	Title          string `json:"title"`
	Description    string `json:"description"`
	SupportedGames string `json:"supported_games"`
}

// Landmark is one gallery card (sagas --json catalog).
type Landmark struct {
	Selector   string   `json:"selector"`
	ID         string   `json:"id"`
	Title      string   `json:"title"`
	Saga       string   `json:"saga"`
	Size       [3]int   `json:"size"`
	Nodes      int      `json:"nodes"`
	Site       []string `json:"site"`
	Exposure   string   `json:"exposure"`
	Biomes     []string `json:"biomes"`
	Rarity     int      `json:"rarity"`
	Author     string   `json:"author"`
	License    string   `json:"license"`
	SourceURL  string   `json:"source_url"`
	Lore       string   `json:"lore"`
	Preview    string   `json:"preview"`
	TargetSize int      `json:"target_size"`
	RealSize   float64  `json:"real_size"`
	Edited     string   `json:"edited"`
	Manual     bool     `json:"manual"`
}

// Catalog is what the gallery shows.
type Catalog struct {
	Sagas     []Saga     `json:"sagas"`
	Landmarks []Landmark `json:"landmarks"`
	Unbuilt   []string   `json:"unbuilt"`
}

// Catalog lists sagas and landmarks of the workspace.
func (r Runner) Catalog(ctx context.Context) (Catalog, error) {
	var c Catalog
	err := r.Sagas(ctx, nil, &c, "catalog")
	return c, err
}

// Request is a new landmark (sagas.intake.Request).
type Request struct {
	Title   string `json:"title"`
	URL     string `json:"url,omitempty"`
	File    string `json:"file,omitempty"`
	License string `json:"license"`
	Author  string `json:"author,omitempty"`
	Saga    string `json:"saga,omitempty"`
	NewSaga string `json:"new_saga,omitempty"`
	Size    int    `json:"size,omitempty"`
	Hints   string `json:"hints,omitempty"`
	Lore    string `json:"lore,omitempty"`
	AI      bool   `json:"ai,omitempty"`
	Notes   string `json:"notes,omitempty"`
	ID      string `json:"id,omitempty"`
}

// Summary is what `sagas add` created.
type Summary struct {
	Saga      string         `json:"saga"`
	ID        string         `json:"id"`
	Title     string         `json:"title"`
	Path      string         `json:"path"`
	Dims      [3]int         `json:"dims"`
	Nodes     int            `json:"nodes"`
	Placement map[string]any `json:"placement"`
	Matched   []string       `json:"matched"`
	Notes     []string       `json:"notes"`
	NewSaga   bool           `json:"new_saga"`
	Files     []string       `json:"files"`
}

// Selector is <saga>/<id>.
func (s Summary) Selector() string { return s.Saga + "/" + s.ID }

// Add creates a landmark from req.
func (r Runner) Add(ctx context.Context, logf Logf, req Request) (Summary, error) {
	f, err := os.CreateTemp("", "sagaforge-request-*.json")
	if err != nil {
		return Summary{}, err
	}
	defer os.Remove(f.Name())
	if err := json.NewEncoder(f).Encode(req); err != nil {
		f.Close()
		return Summary{}, err
	}
	if err := f.Close(); err != nil {
		return Summary{}, err
	}
	var s Summary
	err = r.Sagas(ctx, logf, &s, "add", f.Name())
	return s, err
}

// Set changes landmark.toml fields ("transform.target_size" -> 24); values are JSON-encoded so
// strings and lists keep their type (sagas parses them as TOML values, which JSON scalars and
// arrays of strings are).
func (r Runner) Set(ctx context.Context, logf Logf, selector string, values map[string]any) error {
	args := []string{"set", selector}
	for k, v := range values {
		b, err := json.Marshal(v)
		if err != nil {
			return err
		}
		args = append(args, k+"="+string(b))
	}
	return r.Sagas(ctx, logf, nil, args...)
}

// CommandResult is what `sagas command` did.
type CommandResult struct {
	Landmark string   `json:"landmark"`
	Done     []string `json:"done"`
	Size     [3]int   `json:"size"`
	Nodes    int      `json:"nodes"`
	Sealed   bool     `json:"sealed"`
}

// Command applies bot commands ("/size 24") and rebuilds.
func (r Runner) Command(ctx context.Context, logf Logf, selector string, lines ...string) (CommandResult, error) {
	var out CommandResult
	err := r.Sagas(ctx, logf, &out, append([]string{"command", selector}, lines...)...)
	return out, err
}

// Hints are placement fields for a description.
type Hints struct {
	Fields  map[string]any `json:"fields"`
	Matched []string       `json:"matched"`
}

// Hints suggests placement fields for text.
func (r Runner) Hints(ctx context.Context, text string) (Hints, error) {
	var h Hints
	err := r.Sagas(ctx, nil, &h, "hints", text)
	return h, err
}

// Finding is one lint finding.
type Finding struct {
	Code     string `json:"code"`
	Level    string `json:"level"`
	Landmark string `json:"landmark"`
	Message  string `json:"message"`
}

// Lint checks a selector. Errors are findings, not a failure.
func (r Runner) Lint(ctx context.Context, selector string) ([]Finding, error) {
	var out []Finding
	err := r.Sagas(ctx, nil, &out, "lint", selector)
	if e, ok := err.(*Error); ok && e.ExitCode == 3 { // errors found
		err = nil
	}
	return out, err
}

// Build builds the packs of the selected landmarks' sagas (for a tour).
func (r Runner) Build(ctx context.Context, logf Logf, selector string) error {
	return r.Sagas(ctx, logf, nil, "build", selector)
}

// Viewer is a running `sagas view --serve`: stopped by closing its stdin.
type Viewer struct {
	URL   string
	Page  string
	Sizes []int
	stdin io.WriteCloser
	cmd   *exec.Cmd
}

// Stop ends the viewer.
func (v *Viewer) Stop() {
	v.stdin.Close()
	if v.cmd != nil {
		_ = v.cmd.Wait()
	}
}

// View starts the live viewer for one landmark and returns once it serves.
func (r Runner) View(ctx context.Context, selector string) (*Viewer, error) {
	cmd := proc.Command(context.WithoutCancel(ctx), r.Home.Env(), r.Home.SagasCLI(),
		"--json", "view", selector, "--serve", "--stdin-lifetime", "--no-open")
	cmd.Dir = r.Home.Workspace()
	stdin, err := cmd.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, err
	}
	errw := &lines{}
	cmd.Stderr = errw
	if err := cmd.Start(); err != nil {
		return nil, err
	}
	first, err := bufio.NewReader(stdout).ReadString('\n')
	var info struct {
		URL   string `json:"url"`
		Page  string `json:"page"`
		Sizes []int  `json:"sizes"`
		Error string `json:"error"`
	}
	if err == nil {
		err = json.Unmarshal([]byte(first), &info)
	}
	if err != nil || info.URL == "" {
		stdin.Close()
		_ = cmd.Wait()
		msg := info.Error
		if msg == "" {
			msg = strings.TrimSpace(errw.last + " " + first)
		}
		return nil, &Error{Tool: "sagas view", Message: fmt.Sprint(msg)}
	}
	go func() { _, _ = io.Copy(io.Discard, stdout) }()
	return &Viewer{URL: info.URL, Page: info.Page, Sizes: info.Sizes, stdin: stdin, cmd: cmd}, nil
}

// FakeViewer is a Viewer that is not a process (tests).
func FakeViewer(url string) *Viewer {
	return &Viewer{URL: url, stdin: nopCloser{}}
}

type nopCloser struct{}

func (nopCloser) Write(p []byte) (int, error) { return len(p), nil }
func (nopCloser) Close() error                { return nil }
