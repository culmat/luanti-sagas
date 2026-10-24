// Package app is what Saga Forge does, for the web UI: set up the tools, keep drafts, add and
// change landmarks through the sagas tools, show them in the live viewer, start tours in Luanti,
// sign in to GitHub and submit. Long work runs as jobs whose progress the UI follows.
package app

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/culmat/luanthetti/pkg/installs"
	"github.com/culmat/luanthetti/pkg/jobs"

	"github.com/culmat/luanti-sagas/forge/internal/github"
	"github.com/culmat/luanti-sagas/forge/internal/home"
	"github.com/culmat/luanti-sagas/forge/internal/luanti"
	"github.com/culmat/luanti-sagas/forge/internal/setup"
	"github.com/culmat/luanti-sagas/forge/internal/tools"
	"github.com/culmat/luanti-sagas/forge/internal/workspace"
)

// Version is set by main.
var Version = "dev"

// App holds Forge's parts.
type App struct {
	Home   home.Home
	Setup  *setup.Setup
	Tools  tools.Runner
	WS     workspace.Workspace
	Player *luanti.Player
	Jobs   *jobs.Manager
	Tokens Tokens
	// GitHub returns a client for a token (tests point it at a fake).
	GitHub func(token string) *github.Client

	store   *store
	mu      sync.Mutex
	view    *view
	ready   bool
	catalog *tools.Catalog // until the workspace changes
}

// changed forgets what was read from the workspace.
func (a *App) changed() {
	a.mu.Lock()
	a.catalog = nil
	a.mu.Unlock()
}

type view struct {
	selector string
	v        *tools.Viewer
}

// New prepares the app for h; jobs run until ctx ends.
func New(ctx context.Context, h home.Home) (*App, error) {
	st, err := openStore(h.State())
	if err != nil {
		return nil, err
	}
	r := tools.Runner{Home: h}
	return &App{
		Home:   h,
		Setup:  setup.New(h),
		Tools:  r,
		WS:     workspace.Workspace{Dir: h.Workspace(), Env: h.Env(), Managed: !h.CloneMode()},
		Player: &luanti.Player{Tools: r},
		Jobs:   jobs.New(ctx),
		Tokens: Tokens{File: filepath.Join(h.State(), "token.json")},
		GitHub: github.New,
		store:  st,
	}, nil
}

// Close stops the viewer.
func (a *App) Close() {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.view != nil {
		a.view.v.Stop()
		a.view = nil
	}
}

// ---------------------------------------------------------------- status and setup

// Status is what the UI shows first.
type Status struct {
	Version   string          `json:"version"`
	Ready     bool            `json:"ready"`
	Missing   []string        `json:"missing"`
	CloneMode bool            `json:"clone_mode"`
	Workspace string          `json:"workspace"`
	Draft     string          `json:"draft"`
	Login     string          `json:"login"`
	Running   *luanti.Launch  `json:"running"`
	Settings  Settings        `json:"settings"`
	Sent      map[string]Sent `json:"sent"`
}

// Status reports where Forge stands.
func (a *App) Status(ctx context.Context) Status {
	st := a.store.read()
	s := Status{Version: Version, CloneMode: a.Home.CloneMode(), Workspace: a.Home.Workspace(),
		Login: st.Login, Running: a.Player.Running(), Settings: st.Settings, Sent: st.Sent}
	a.mu.Lock()
	ready := a.ready
	a.mu.Unlock()
	if !ready {
		s.Missing = a.Setup.Missing(ctx)
		ready = len(s.Missing) == 0
		a.mu.Lock()
		a.ready = ready
		a.mu.Unlock()
	}
	s.Ready = ready
	if ready {
		if b, err := a.WS.Branch(ctx); err == nil && strings.HasPrefix(b, workspace.Prefix) {
			s.Draft = strings.TrimPrefix(b, workspace.Prefix)
		}
	}
	return s
}

// RunSetup installs what is missing; update also refreshes the clones and ldg.
func (a *App) RunSetup(update bool) (*jobs.Job, error) {
	title := "Setting up Saga Forge"
	if update {
		title = "Updating the tools"
	}
	return a.Jobs.Submit("setup", title, func(ctx context.Context, logf func(string, ...any)) (any, error) {
		a.Setup.Update = update
		defer func() { a.Setup.Update = false }()
		defer a.changed()
		err := a.Setup.Run(ctx, setup.Logf(logf))
		a.mu.Lock()
		a.ready = err == nil
		a.mu.Unlock()
		return nil, err
	})
}

func (a *App) needReady() error {
	a.mu.Lock()
	ready := a.ready
	a.mu.Unlock()
	if ready {
		return nil
	}
	if missing := a.Setup.Missing(context.Background()); len(missing) > 0 {
		return fmt.Errorf("Saga Forge is not set up yet (missing: %s)", strings.Join(missing, ", "))
	}
	a.mu.Lock()
	a.ready = true
	a.mu.Unlock()
	return nil
}

// Settings returns the user's settings.
func (a *App) Settings() Settings { return a.store.read().Settings }

// SaveSettings stores new settings.
func (a *App) SaveSettings(s Settings) error {
	if s.LuantiBin != "" {
		if _, err := os.Stat(s.LuantiBin); err != nil {
			return fmt.Errorf("no Luanti at %s", s.LuantiBin)
		}
	}
	return a.store.update(func(f *stateFile) { f.Settings = s })
}

// Installation is a Luanti program found on this computer.
type Installation struct {
	Path    string `json:"path"`
	Version string `json:"version"`
}

// Installations lists the Luanti programs found on this computer.
func (a *App) Installations(ctx context.Context) []Installation {
	out := []Installation{}
	for _, b := range installs.FindBinaries(ctx) {
		out = append(out, Installation{Path: b.Path, Version: b.Version})
	}
	return out
}

// ---------------------------------------------------------------- catalog and drafts

// Catalog lists sagas and landmarks of the workspace as it is now.
func (a *App) Catalog(ctx context.Context) (tools.Catalog, error) {
	if err := a.needReady(); err != nil {
		return tools.Catalog{}, err
	}
	a.mu.Lock()
	cached := a.catalog
	a.mu.Unlock()
	if cached != nil {
		return *cached, nil
	}
	c, err := a.Tools.Catalog(ctx)
	if err == nil {
		a.mu.Lock()
		a.catalog = &c
		a.mu.Unlock()
	}
	return c, err
}

// Drafts lists the drafts with what Forge sent of them.
func (a *App) Drafts(ctx context.Context) ([]workspace.Draft, error) {
	if err := a.needReady(); err != nil {
		return nil, err
	}
	if !a.WS.Managed {
		return nil, nil
	}
	return a.WS.Drafts(ctx)
}

// OpenDraft switches to a draft (creating it from main).
func (a *App) OpenDraft(ctx context.Context, name string) error {
	if err := a.needReady(); err != nil {
		return err
	}
	a.Close()
	defer a.changed()
	return a.WS.Open(ctx, name)
}

// DiscardDraft deletes a draft.
func (a *App) DiscardDraft(ctx context.Context, name string) error {
	a.Close()
	defer a.changed()
	if err := a.WS.Discard(ctx, name); err != nil {
		return err
	}
	return a.store.update(func(f *stateFile) { delete(f.Sent, name) })
}

// Update brings the current draft onto the newest main (keep: "", "mine", "theirs").
func (a *App) Update(keep string) (*jobs.Job, error) {
	return a.Jobs.Submit("update", "Updating the draft", func(ctx context.Context, logf func(string, ...any)) (any, error) {
		a.Close()
		defer a.changed()
		err := a.WS.Update(ctx, keep)
		var conflict *workspace.ConflictError
		if errors.As(err, &conflict) {
			return map[string]any{"conflict": conflict.Files}, err
		}
		return nil, err
	})
}

// EditDraft is the draft name for changing an existing landmark.
func EditDraft(selector string) string { return slug(strings.ReplaceAll(selector, "/", "-")) }

var slugRE = regexp.MustCompile(`[^a-z0-9-]+`)

func slug(s string) string {
	s = strings.Trim(slugRE.ReplaceAllString(strings.ToLower(s), "_"), "_-")
	if len(s) > 60 {
		s = strings.Trim(s[:60], "_-")
	}
	if s == "" {
		s = "draft"
	}
	return s
}

// ---------------------------------------------------------------- landmarks

// Upload keeps a model file the user dropped into the browser and returns its path for Add.
func (a *App) Upload(name string, data []byte) (string, error) {
	name = filepath.Base(strings.ReplaceAll(name, "\\", "/"))
	if name == "." || name == "/" || name == "" {
		return "", errors.New("the file needs a name")
	}
	dir, err := os.MkdirTemp(filepath.Join(a.Home.Cache()), "upload-")
	if err != nil {
		if err := os.MkdirAll(a.Home.Cache(), 0o755); err != nil {
			return "", err
		}
		if dir, err = os.MkdirTemp(a.Home.Cache(), "upload-"); err != nil {
			return "", err
		}
	}
	path := filepath.Join(dir, name)
	return path, os.WriteFile(path, data, 0o644)
}

// Add creates a landmark in a new draft.
func (a *App) Add(req tools.Request) (*jobs.Job, error) {
	if err := a.needReady(); err != nil {
		return nil, err
	}
	return a.Jobs.Submit("add", "Adding "+req.Title, func(ctx context.Context, logf func(string, ...any)) (any, error) {
		a.Close()
		defer a.changed()
		temp := "new-" + slug(req.Title)
		if err := a.WS.Open(ctx, temp); err != nil {
			return nil, err
		}
		sum, err := a.Tools.Add(ctx, tools.Logf(logf), req)
		if err != nil {
			return nil, err
		}
		if req.File != "" {
			_ = os.RemoveAll(filepath.Dir(req.File))
		}
		if err := a.WS.Save(ctx, "Add "+sum.Selector()); err != nil {
			return nil, err
		}
		name := EditDraft(sum.Selector())
		if !a.WS.Exists(ctx, name) {
			if err := a.WS.Rename(ctx, temp, name); err != nil {
				return nil, err
			}
		}
		return sum, nil
	})
}

// Edit opens the draft for changing selector.
func (a *App) Edit(ctx context.Context, selector string) error {
	return a.OpenDraft(ctx, EditDraft(selector))
}

// Set changes landmark.toml fields (placement, story) and saves them in the draft.
func (a *App) Set(ctx context.Context, selector string, values map[string]any) error {
	if err := a.needReady(); err != nil {
		return err
	}
	defer a.changed()
	if err := a.Tools.Set(ctx, nil, selector, values); err != nil {
		return err
	}
	keys := make([]string, 0, len(values))
	for k := range values {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return a.WS.Save(ctx, fmt.Sprintf("%s: %s", selector, strings.Join(keys, ", ")))
}

// Command applies bot commands ("/size 24"), which rebuild the voxels, and saves the draft.
func (a *App) Command(selector string, lines []string) (*jobs.Job, error) {
	if err := a.needReady(); err != nil {
		return nil, err
	}
	return a.Jobs.Submit("command", selector+": "+strings.Join(lines, " "), func(ctx context.Context, logf func(string, ...any)) (any, error) {
		defer a.changed()
		res, err := a.Tools.Command(ctx, tools.Logf(logf), selector, lines...)
		if err != nil {
			return nil, err
		}
		a.restartView(ctx, selector)
		return res, a.WS.Save(ctx, fmt.Sprintf("%s: %s", selector, strings.Join(lines, ", ")))
	})
}

// Vocabulary is the mod's placement words (sites, exposure, biome tags, rarity), from the workspace.
func (a *App) Vocabulary() (json.RawMessage, error) {
	if err := a.needReady(); err != nil {
		return nil, err
	}
	b, err := os.ReadFile(filepath.Join(a.Home.Workspace(), "mods", "sagas", "vocabulary.json"))
	if err != nil {
		return nil, err
	}
	var v struct {
		Sites     map[string][]string `json:"sites"`
		Exposure  []string            `json:"exposure"`
		BiomeTags []string            `json:"biome_tags"`
		Rarity    map[string]int      `json:"rarity"`
	}
	if err := json.Unmarshal(b, &v); err != nil {
		return nil, err
	}
	return JSON(v), nil
}

// Hints suggests placement for a description.
func (a *App) Hints(ctx context.Context, text string) (tools.Hints, error) {
	if err := a.needReady(); err != nil {
		return tools.Hints{}, err
	}
	return a.Tools.Hints(ctx, text)
}

// Lint checks a landmark.
func (a *App) Lint(ctx context.Context, selector string) ([]tools.Finding, error) {
	if err := a.needReady(); err != nil {
		return nil, err
	}
	return a.Tools.Lint(ctx, selector)
}

// ---------------------------------------------------------------- viewer

// View starts the live viewer of selector (one at a time) and returns its local URL.
func (a *App) View(ctx context.Context, selector string) (string, error) {
	if err := a.needReady(); err != nil {
		return "", err
	}
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.view != nil && a.view.selector == selector {
		return a.view.v.URL, nil
	}
	if a.view != nil {
		a.view.v.Stop()
		a.view = nil
	}
	v, err := a.Tools.View(ctx, selector)
	if err != nil {
		return "", err
	}
	a.view = &view{selector: selector, v: v}
	return v.URL, nil
}

// ViewerURL is the running viewer of selector ("" when none).
func (a *App) ViewerURL(selector string) string {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.view == nil || a.view.selector != selector {
		return ""
	}
	return a.view.v.URL
}

// restartView reloads the viewer after the landmark changed.
func (a *App) restartView(ctx context.Context, selector string) {
	a.mu.Lock()
	running := a.view != nil && a.view.selector == selector
	if running {
		a.view.v.Stop()
		a.view = nil
	}
	a.mu.Unlock()
	if running {
		_, _ = a.View(ctx, selector)
	}
}

// ---------------------------------------------------------------- Luanti

// Games lists the reference games and whether they are downloaded.
func (a *App) Games(ctx context.Context) ([]luanti.Game, error) {
	if err := a.needReady(); err != nil {
		return nil, err
	}
	return a.Player.Games(ctx)
}

// SyncGame downloads a reference game.
func (a *App) SyncGame(game string) (*jobs.Job, error) {
	return a.Jobs.Submit("game", "Downloading "+game, func(ctx context.Context, logf func(string, ...any)) (any, error) {
		return nil, a.Player.Sync(ctx, tools.Logf(logf), game)
	})
}

// TourRequest asks for a tour.
type TourRequest struct {
	Selector string `json:"selector"`
	Game     string `json:"game"`
	Fresh    bool   `json:"fresh"`
	Start    string `json:"start"` // default: find the landmark
}

// Tour builds the packs and starts Luanti.
func (a *App) Tour(req TourRequest) (*jobs.Job, error) {
	if err := a.needReady(); err != nil {
		return nil, err
	}
	set := a.Settings()
	if req.Game == "" {
		req.Game = set.Game
	}
	if req.Start == "" && req.Selector != "" {
		req.Start = "find " + req.Selector[strings.Index(req.Selector, "/")+1:]
	}
	return a.Jobs.Submit("tour", "Starting Luanti", func(ctx context.Context, logf func(string, ...any)) (any, error) {
		t := luanti.Tour{Game: req.Game, Start: req.Start, Lite: set.Lite, Fresh: req.Fresh, Bin: set.LuantiBin}
		l, err := a.Player.Play(ctx, tools.Logf(logf), req.Selector, t, func(err error) {
			a.Jobs.Publish("luanti", map[string]any{"running": false, "error": errString(err)})
			_ = a.WS.Tidy(context.Background())
		})
		if err != nil {
			return nil, err
		}
		a.Jobs.Publish("luanti", map[string]any{"running": true, "game": l.Game})
		return l, nil
	})
}

func errString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

// ---------------------------------------------------------------- GitHub

// SignIn starts GitHub's device flow; a job waits for the user to confirm the code.
func (a *App) SignIn(ctx context.Context) (github.DeviceCode, *jobs.Job, error) {
	id, err := github.ClientIDFor()
	if err != nil {
		return github.DeviceCode{}, nil, err
	}
	gh := a.GitHub("")
	d, err := gh.StartDeviceFlow(ctx, id)
	if err != nil {
		return d, nil, err
	}
	j, err := a.Jobs.Submit("signin", "Signing in to GitHub", func(ctx context.Context, logf func(string, ...any)) (any, error) {
		logf("enter %s at %s", d.UserCode, d.VerificationURI)
		tok, err := gh.WaitForToken(ctx, id, d)
		if err != nil {
			return nil, err
		}
		u, err := a.GitHub(tok).User(ctx)
		if err != nil {
			return nil, err
		}
		if err := a.Tokens.Set(u.Login, tok); err != nil {
			return nil, err
		}
		if err := a.store.update(func(f *stateFile) { f.Login = u.Login }); err != nil {
			return nil, err
		}
		a.Jobs.Publish("signed_in", map[string]string{"login": u.Login})
		return u, nil
	})
	return d, j, err
}

// SignOut forgets the token.
func (a *App) SignOut() error {
	login := a.store.read().Login
	a.Tokens.Delete(login)
	return a.store.update(func(f *stateFile) { f.Login = "" })
}

func (a *App) client() (*github.Client, error) {
	login := a.store.read().Login
	tok := a.Tokens.Get(login)
	if tok == "" {
		return nil, errors.New("sign in to GitHub first")
	}
	return a.GitHub(tok), nil
}

// Submit sends a draft: a pull request, or for someone with write access a commit on main.
func (a *App) Submit(draft string) (*jobs.Job, error) {
	if err := a.needReady(); err != nil {
		return nil, err
	}
	if !a.WS.Managed {
		return nil, errors.New("this is your own clone: commit and push with git")
	}
	gh, err := a.client()
	if err != nil {
		return nil, err
	}
	return a.Jobs.Submit("submit", "Submitting "+draft, func(ctx context.Context, logf func(string, ...any)) (any, error) {
		con, err := a.contribution(ctx, draft)
		if err != nil {
			return nil, err
		}
		logf("%s: %d file(s)", con.Title, len(con.Changes))
		res, err := gh.Submit(ctx, github.Upstream, con)
		if err != nil {
			return nil, err
		}
		sent := Sent{Draft: draft, Direct: res.Direct, Commit: res.Commit, At: time.Now().UTC()}
		if res.Pull != nil {
			sent.Pull, sent.URL = res.Pull.Number, res.Pull.HTMLURL
			logf("pull request #%d: %s", res.Pull.Number, res.Pull.HTMLURL)
		} else {
			sent.URL = "https://github.com/" + github.Upstream + "/commit/" + res.Commit
			logf("committed on main: %s", sent.URL)
		}
		return sent, a.store.update(func(f *stateFile) { f.Sent[draft] = sent })
	})
}

// contribution is the draft as files, a title and a description.
func (a *App) contribution(ctx context.Context, draft string) (github.Contribution, error) {
	if cur, _ := a.WS.Branch(ctx); cur == workspace.Prefix+draft {
		if err := a.WS.Save(ctx, "Work in progress"); err != nil {
			return github.Contribution{}, err
		}
	}
	rev := workspace.Prefix + draft
	changes, err := a.WS.Changes(ctx, rev)
	if err != nil {
		return github.Contribution{}, err
	}
	if len(changes) == 0 {
		return github.Contribution{}, errors.New("this draft changes nothing yet")
	}
	con := github.Contribution{Branch: rev}
	var added, changed []string
	paths := make([]string, 0, len(changes))
	for _, ch := range changes {
		c := github.Change{Path: ch.Path}
		if !ch.Deleted {
			b, ok, err := a.WS.FileAt(ctx, rev, ch.Path)
			if err != nil {
				return con, err
			}
			if !ok {
				return con, fmt.Errorf("%s is missing in the draft", ch.Path)
			}
			c.Content = b
		}
		con.Changes = append(con.Changes, c)
		paths = append(paths, ch.Path)
		if strings.HasSuffix(ch.Path, "/landmark.toml") {
			sel := workspace.Landmarks([]string{ch.Path})[0]
			if ch.Status == "A" {
				added = append(added, sel)
			} else {
				changed = append(changed, sel)
			}
		}
	}
	if len(added) == 0 && len(changed) == 0 {
		changed = workspace.Landmarks(paths)
	}
	var parts []string
	if len(added) > 0 {
		parts = append(parts, "Add "+strings.Join(added, ", "))
	}
	if len(changed) > 0 {
		verb := "Update "
		if len(parts) > 0 {
			verb = "update "
		}
		parts = append(parts, verb+strings.Join(changed, ", "))
	}
	con.Title = strings.Join(parts, "; ")
	con.Body = "Contributed with Saga Forge " + Version + ".\n\nFiles:\n"
	for _, p := range paths {
		con.Body += "- `" + p + "`\n"
	}
	return con, nil
}

// Submissions lists the user's pull requests.
func (a *App) Submissions(ctx context.Context) ([]github.Submission, error) {
	gh, err := a.client()
	if err != nil {
		return nil, err
	}
	return gh.Submissions(ctx, github.Upstream, a.store.read().Login)
}

// JSON is a helper for handlers that return a job's result.
func JSON(v any) json.RawMessage {
	b, _ := json.Marshal(v)
	return b
}

// TestViewer pretends a viewer for selector runs at url (for tests of the proxy).
func (a *App) TestViewer(selector, url string) {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.view = &view{selector: selector, v: tools.FakeViewer(url)}
}
