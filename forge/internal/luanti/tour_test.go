package luanti

import (
	"context"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/culmat/luanti-sagas/forge/internal/home"
	"github.com/culmat/luanti-sagas/forge/internal/tools"
)

func script(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("#!/bin/sh\n"+body+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
}

// A tour builds the packs, asks avanti for the launch and starts it; the stand-in "Luanti" here
// writes its arguments to a file and exits.
func TestPlay(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("stand-in tools are shell scripts")
	}
	h := home.New(t.TempDir(), "")
	if err := os.MkdirAll(h.Workspace(), 0o755); err != nil {
		t.Fatal(err)
	}
	calls := filepath.Join(h.Root, "calls")
	script(t, h.SagasCLI(), `echo "sagas $*" >> "`+calls+`"; echo '{"results": []}'`)
	luanti := filepath.Join(h.Root, "luanti")
	script(t, luanti, `echo "luanti $*" >> "`+calls+`"`)
	script(t, h.AvantiCLI(), `echo "avanti $*" >> "`+calls+`"
printf '{"bin": "%s", "args": ["--go", "--world", "/w"], "env": {"LUANTI_GAME_PATH": "/g"}, "world": "%s", "log": "/w/debug.txt", "game": "minetest"}\n' "`+luanti+`" "`+h.Root+`"`)
	p := &Player{Tools: tools.Runner{Home: h}}
	done := make(chan error, 1)
	l, err := p.Play(context.Background(), nil, "ruins/tower", Tour{Game: "minetest", Start: "find tower", Lite: true}, func(err error) { done <- err })
	if err != nil {
		t.Fatal(err)
	}
	if l.Game != "minetest" {
		t.Fatalf("launch %+v", l)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("the game never ended")
	}
	if p.Running() != nil {
		t.Fatal("a closed game is not running")
	}
	b, _ := os.ReadFile(calls)
	log := string(b)
	for _, want := range []string{
		"sagas --json build ruins/tower",
		"avanti play " + filepath.Join(h.Workspace(), "mods") + " --game minetest --world " + filepath.Join(h.Worlds(), "minetest") + " --print-command --set sagas_start=find tower --lite",
		"luanti --go --world /w",
	} {
		if !strings.Contains(log, want) {
			t.Errorf("missing %q in\n%s", want, log)
		}
	}
}
