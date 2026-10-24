package app

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/zalando/go-keyring"
)

// Settings are the user's choices, kept in state/settings.json.
type Settings struct {
	Game      string `json:"game"`       // avanti game id for tours
	Lite      bool   `json:"lite"`       // lighter graphics
	LuantiBin string `json:"luanti_bin"` // a Luanti the user picked ("" = found automatically)
}

// Sent records where a draft went.
type Sent struct {
	Draft  string    `json:"draft"`
	Direct bool      `json:"direct"`
	Commit string    `json:"commit"`
	Pull   int       `json:"pull,omitempty"`
	URL    string    `json:"url,omitempty"`
	At     time.Time `json:"at"`
}

type stateFile struct {
	Settings Settings        `json:"settings"`
	Sent     map[string]Sent `json:"sent"`
	Login    string          `json:"login"` // the signed-in GitHub account (the token is in the keychain)
}

// store keeps stateFile on disk.
type store struct {
	path string
	mu   sync.Mutex
	s    stateFile
}

func openStore(dir string) (*store, error) {
	st := &store{path: filepath.Join(dir, "state.json")}
	st.s.Settings.Game = "minetest"
	b, err := os.ReadFile(st.path)
	if err == nil {
		err = json.Unmarshal(b, &st.s)
	} else if errors.Is(err, os.ErrNotExist) {
		err = nil
	}
	if st.s.Sent == nil {
		st.s.Sent = map[string]Sent{}
	}
	return st, err
}

func (st *store) read() stateFile {
	st.mu.Lock()
	defer st.mu.Unlock()
	out := st.s
	out.Sent = map[string]Sent{}
	for k, v := range st.s.Sent {
		out.Sent[k] = v
	}
	return out
}

func (st *store) update(f func(*stateFile)) error {
	st.mu.Lock()
	defer st.mu.Unlock()
	f(&st.s)
	b, err := json.MarshalIndent(st.s, "", "  ")
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(st.path), 0o755); err != nil {
		return err
	}
	tmp := st.path + ".tmp"
	if err := os.WriteFile(tmp, b, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, st.path)
}

// Tokens keep the GitHub token: the system keychain, or a file only the user can read when there
// is no keychain (a Linux without Secret Service).
type Tokens struct {
	File string
}

const keyringService = "Saga Forge"

// Get returns the token for login ("" when none).
func (t Tokens) Get(login string) string {
	if login == "" {
		return ""
	}
	if tok, err := keyring.Get(keyringService, login); err == nil {
		return tok
	}
	b, err := os.ReadFile(t.File)
	if err != nil {
		return ""
	}
	var m map[string]string
	_ = json.Unmarshal(b, &m)
	return m[login]
}

// Set stores the token of login.
func (t Tokens) Set(login, token string) error {
	if err := keyring.Set(keyringService, login, token); err == nil {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(t.File), 0o700); err != nil {
		return err
	}
	b, _ := json.Marshal(map[string]string{login: token})
	return os.WriteFile(t.File, b, 0o600)
}

// Delete forgets the token of login.
func (t Tokens) Delete(login string) {
	_ = keyring.Delete(keyringService, login)
	_ = os.Remove(t.File)
}
