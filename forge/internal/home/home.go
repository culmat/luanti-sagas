// Package home is the layout of Saga Forge's own folder: the tools it installs, the repositories it
// clones, downloaded models and dev worlds. Nothing of the user's (their Python, their Luanti
// worlds) is touched; the reference games are shared with avanti in ~/.avanti.
package home

import (
	"os"
	"path/filepath"
	"runtime"
)

// Home is the Forge folder. Folder, when set, is a git clone the user opened ("clone mode"): the
// tools run in it and nothing is submitted for them.
type Home struct {
	Root   string
	Folder string
}

// New returns the layout under root; folder is a clone to work in, or "".
func New(root, folder string) Home { return Home{Root: root, Folder: folder} }

func (h Home) Bin() string      { return filepath.Join(h.Root, "bin") }
func (h Home) Repos() string    { return filepath.Join(h.Root, "repos") }
func (h Home) Worlds() string   { return filepath.Join(h.Root, "worlds") }
func (h Home) State() string    { return filepath.Join(h.Root, "state") }
func (h Home) Cache() string    { return filepath.Join(h.Root, "cache") }
func (h Home) Python() string   { return filepath.Join(h.Root, "python") }
func (h Home) UVTools() string  { return filepath.Join(h.Root, "uv-tools") }
func (h Home) ToolsBin() string { return filepath.Join(h.Root, "uv-tools", "bin") }

// Venv is the Python environment of the sagas tools: Forge's own, never the clone's tools/.venv.
func (h Home) Venv() string { return filepath.Join(h.Root, "venv") }

// Avanti is the avanti-luanti clone.
func (h Home) Avanti() string { return filepath.Join(h.Repos(), "avanti-luanti") }

// AvantiCLI is the avanti command (a Bash script).
func (h Home) AvantiCLI() string {
	return filepath.Join(h.Avanti(), "plugins", "avanti", "bin", "avanti")
}

// Workspace is the luanti-sagas checkout Forge works in: the opened clone, or its own.
func (h Home) Workspace() string {
	if h.Folder != "" {
		return h.Folder
	}
	return filepath.Join(h.Repos(), "luanti-sagas")
}

// CloneMode reports whether Forge works in a clone of the user's.
func (h Home) CloneMode() bool { return h.Folder != "" }

// Sources is where downloaded models go: the clone's own sources/ in clone mode.
func (h Home) Sources() string {
	if h.Folder != "" {
		return filepath.Join(h.Folder, "sources")
	}
	return filepath.Join(h.Root, "sources")
}

// Exe adds ".exe" on Windows.
func Exe(name string) string {
	if runtime.GOOS == "windows" {
		return name + ".exe"
	}
	return name
}

// SagasCLI is the sagas command in Forge's environment.
func (h Home) SagasCLI() string {
	if runtime.GOOS == "windows" {
		return filepath.Join(h.Venv(), "Scripts", "sagas.exe")
	}
	return filepath.Join(h.Venv(), "bin", "sagas")
}

// Env is the environment for every tool Forge runs: its bin folders first on PATH, uv kept inside
// the Forge folder, the sagas root and sources set.
func (h Home) Env() []string {
	path := []string{h.Bin(), h.ToolsBin(), filepath.Dir(h.AvantiCLI()), filepath.Dir(h.SagasCLI())}
	env := os.Environ()
	set := map[string]string{
		"PATH":                   joinList(append(path, os.Getenv("PATH"))),
		"UV_CACHE_DIR":           filepath.Join(h.Cache(), "uv"),
		"UV_PYTHON_INSTALL_DIR":  h.Python(),
		"UV_TOOL_DIR":            h.UVTools(),
		"UV_TOOL_BIN_DIR":        h.ToolsBin(),
		"UV_PROJECT_ENVIRONMENT": h.Venv(),
		"UV_PYTHON_PREFERENCE":   "only-managed",
		"SAGAS_ROOT":             h.Workspace(),
		"SAGAS_SOURCES":          h.Sources(),
		"PYTHONIOENCODING":       "utf-8",
		"GIT_TERMINAL_PROMPT":    "0",
		"NO_COLOR":               "1",
	}
	out := make([]string, 0, len(env)+len(set))
	for _, kv := range env {
		k := kv
		for i := 0; i < len(kv); i++ {
			if kv[i] == '=' {
				k = kv[:i]
				break
			}
		}
		if _, ok := set[envKey(k)]; ok {
			continue
		}
		out = append(out, kv)
	}
	for k, v := range set {
		out = append(out, k+"="+v)
	}
	return out
}

// envKey folds case on Windows, where Path and PATH are the same variable.
func envKey(k string) string {
	if runtime.GOOS != "windows" {
		return k
	}
	up := []byte(k)
	for i, c := range up {
		if 'a' <= c && c <= 'z' {
			up[i] = c - 32
		}
	}
	return string(up)
}

func joinList(parts []string) string {
	out := ""
	for _, p := range parts {
		if p == "" {
			continue
		}
		if out != "" {
			out += string(os.PathListSeparator)
		}
		out += p
	}
	return out
}
