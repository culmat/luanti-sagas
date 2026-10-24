// Command sagaforge is Saga Forge: a guided app for contributing landmarks to luanti-sagas. It
// serves its UI in the browser on 127.0.0.1 and drives the sagas and avanti tools.
//
//	sagaforge [--port N] [--no-open] [--folder CLONE] [--home DIR]   open the UI
//	sagaforge setup [--update]                                        install or update the tools here
//	sagaforge doctor                                                  what is installed, what is missing
//	sagaforge version
package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"time"

	"github.com/culmat/luanthetti/pkg/localweb"
	"github.com/culmat/luanthetti/pkg/paths"

	"github.com/culmat/luanti-sagas/forge/internal/app"
	"github.com/culmat/luanti-sagas/forge/internal/home"
	"github.com/culmat/luanti-sagas/forge/internal/web"
)

// Set by the release build (-ldflags "-X main.version=...").
var version = "dev"

func main() {
	app.Version = version
	if err := run(os.Args[1:], os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "sagaforge:", err)
		os.Exit(1)
	}
}

func run(args []string, out io.Writer) error {
	cmd := ""
	if len(args) > 0 && !strings.HasPrefix(args[0], "-") {
		cmd, args = args[0], args[1:]
	}
	fs := flag.NewFlagSet("sagaforge "+cmd, flag.ContinueOnError)
	port := fs.Int("port", 7337, "port on 127.0.0.1 (0 picks a free one)")
	noOpen := fs.Bool("no-open", false, "don't open the browser")
	folder := fs.String("folder", "", "work in this luanti-sagas clone of yours instead of Forge's own copy")
	homeFlag := fs.String("home", "", "Forge's folder (default: the system's app data folder; SAGAFORGE_HOME)")
	update := fs.Bool("update", false, "setup: also update the clones and ldg")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if cmd == "version" {
		fmt.Fprintln(out, "sagaforge", version)
		return nil
	}
	dirs, err := paths.Resolve("sagaforge", "SAGAFORGE_HOME", *homeFlag)
	if err != nil {
		return err
	}
	clone := ""
	if *folder != "" {
		if clone, err = filepath.Abs(*folder); err != nil {
			return err
		}
		if _, err := os.Stat(filepath.Join(clone, "tools", "pyproject.toml")); err != nil {
			return fmt.Errorf("%s is not a luanti-sagas clone (no tools/pyproject.toml)", clone)
		}
	}
	h := home.New(dirs.Data, clone)
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	a, err := app.New(ctx, h)
	if err != nil {
		return err
	}
	defer a.Close()
	logf := func(format string, args ...any) { fmt.Fprintf(out, format+"\n", args...) }
	switch cmd {
	case "setup":
		a.Setup.Update = *update
		return a.Setup.Run(ctx, logf)
	case "doctor":
		fmt.Fprintf(out, "Forge folder: %s\nworkspace:    %s\n", h.Root, h.Workspace())
		missing := a.Setup.Missing(ctx)
		if len(missing) == 0 {
			fmt.Fprintln(out, "everything is installed")
			return nil
		}
		fmt.Fprintf(out, "missing: %s (run: sagaforge setup)\n", strings.Join(missing, ", "))
		return nil
	case "":
		return serve(ctx, a, h, *port, !*noOpen, out)
	default:
		return fmt.Errorf("unknown command %q (setup, doctor, version)", cmd)
	}
}

// uiFile remembers the running UI's address, so a second start opens it instead of a new one.
func uiFile(h home.Home) string { return filepath.Join(h.State(), "ui.json") }

func running(h home.Home) string {
	b, err := os.ReadFile(uiFile(h))
	if err != nil {
		return ""
	}
	var ui struct{ URL string }
	if json.Unmarshal(b, &ui) != nil || ui.URL == "" {
		return ""
	}
	base, _, _ := strings.Cut(ui.URL, "#")
	client := &http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get(strings.TrimSuffix(base, "/") + "/ping")
	if err != nil {
		return ""
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return ""
	}
	return ui.URL
}

func serve(ctx context.Context, a *app.App, h home.Home, port int, open bool, out io.Writer) error {
	if url := running(h); url != "" && h.Folder == "" {
		fmt.Fprintf(out, "Saga Forge is already running: %s\n", url)
		if open {
			return localweb.OpenBrowser(url)
		}
		return nil
	}
	s := web.New(a)
	ln, url, err := s.Listen(port)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(h.State(), 0o755); err != nil {
		return err
	}
	b, _ := json.Marshal(map[string]string{"url": url})
	if err := os.WriteFile(uiFile(h), b, 0o600); err != nil {
		return err
	}
	defer os.Remove(uiFile(h))
	fmt.Fprintf(out, "Saga Forge: %s\nKeep this window open while you use it; close it (or press Ctrl+C) to quit.\n", url)
	if open {
		if err := localweb.OpenBrowser(url); err != nil {
			fmt.Fprintf(out, "could not open a browser (%v); open the address yourself\n", err)
		}
	}
	err = s.Serve(ctx, ln)
	if errors.Is(err, context.Canceled) {
		return nil
	}
	return err
}
