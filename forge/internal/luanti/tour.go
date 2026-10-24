// Package luanti starts Luanti for a tour: `avanti play --print-command` prepares a dev world (the
// workspace's mods/ linked in, creative, flying, admin) and Forge starts the printed command itself,
// so it can tell when the game is closed.
package luanti

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"github.com/culmat/luanti-sagas/forge/internal/proc"
	"github.com/culmat/luanti-sagas/forge/internal/tools"
)

// Launch is what `avanti play --print-command` prints.
type Launch struct {
	Bin   string            `json:"bin"`
	Args  []string          `json:"args"`
	Env   map[string]string `json:"env"`
	World string            `json:"world"`
	Log   string            `json:"log"`
	Game  string            `json:"game"`
}

// Game is a reference game avanti knows (`avanti games list --json`).
type Game struct {
	ID     string `json:"id"`
	Folder string `json:"folder"`
	Synced bool   `json:"synced"`
	Dir    string `json:"dir"`
	Source string `json:"source"`
}

// Tour is one request to play.
type Tour struct {
	Game  string // avanti game id: minetest, mineclonia, mineclone2
	Start string // a /saga command run after joining, e.g. "find mammoth_skeleton"
	Lite  bool
	Fresh bool
	Bin   string // a Luanti binary the user picked (LUANTI_BIN); "" lets avanti look
}

// Player runs at most one Luanti at a time.
type Player struct {
	Tools tools.Runner

	mu      sync.Mutex
	running *Launch
}

// Games lists avanti's reference games.
func (p *Player) Games(ctx context.Context) ([]Game, error) {
	var games []Game
	err := p.Tools.Avanti(ctx, nil, &games, "games", "list", "--json")
	return games, err
}

// Sync downloads a reference game.
func (p *Player) Sync(ctx context.Context, logf tools.Logf, game string) error {
	return p.Tools.Avanti(ctx, logf, nil, "games", "sync", game)
}

// Running is the current game, or nil.
func (p *Player) Running() *Launch {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.running
}

// ErrRunning means Luanti is already open.
var ErrRunning = errors.New("Luanti is already running: close it first")

// Play builds the packs of selector's saga, prepares the world and starts Luanti. done is called
// when the game is closed, with its error.
func (p *Player) Play(ctx context.Context, logf tools.Logf, selector string, t Tour, done func(error)) (*Launch, error) {
	if p.Running() != nil {
		return nil, ErrRunning
	}
	h := p.Tools.Home
	if err := p.Tools.Build(ctx, logf, selector); err != nil {
		return nil, err
	}
	args := []string{"play", filepath.Join(h.Workspace(), "mods"), "--game", t.Game,
		"--world", filepath.Join(h.Worlds(), t.Game), "--print-command"}
	if t.Start != "" {
		args = append(args, "--set", "sagas_start="+t.Start)
	}
	if t.Lite {
		args = append(args, "--lite")
	}
	if t.Fresh {
		args = append(args, "--fresh")
	}
	extra := map[string]string{}
	if t.Bin != "" {
		if _, err := os.Stat(t.Bin); err != nil {
			return nil, fmt.Errorf("Luanti at %s: %w", t.Bin, err)
		}
		extra["LUANTI_BIN"] = t.Bin
	}
	var l Launch
	if err := p.Tools.AvantiEnv(ctx, logf, &l, extra, args...); err != nil {
		return nil, err
	}
	env := h.Env()
	for k, v := range l.Env {
		env = append(env, k+"="+v)
	}
	cmd := proc.Command(context.WithoutCancel(ctx), env, l.Bin, l.Args...)
	cmd.Dir = l.World
	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start Luanti: %w", err)
	}
	p.mu.Lock()
	p.running = &l
	p.mu.Unlock()
	go func() {
		err := cmd.Wait()
		p.mu.Lock()
		p.running = nil
		p.mu.Unlock()
		if done != nil {
			done(err)
		}
	}()
	return &l, nil
}
