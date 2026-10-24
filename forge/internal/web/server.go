// Package web serves Saga Forge's browser UI on this machine: the embedded page, a JSON API over
// the app, job progress as server-sent events, the live viewer (a `sagas view --serve` process)
// through a reverse proxy at /view/<saga>/<id>/, and landmark previews at /files/.
//
// Security comes from luanthetti's pkg/localweb: 127.0.0.1 only, a per-run token on every /api/
// request (header X-Saga-Forge-Token, or ?t= for the event stream), loopback Host only, no
// cross-site requests. /view/ and /files/ only serve pictures and model data and refuse
// cross-site requests too.
package web

import (
	"context"
	"embed"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io/fs"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/culmat/luanthetti/pkg/jobs"
	"github.com/culmat/luanthetti/pkg/localweb"

	"github.com/culmat/luanti-sagas/forge/internal/app"
	"github.com/culmat/luanti-sagas/forge/internal/tools"
	"github.com/culmat/luanti-sagas/forge/internal/workspace"
)

//go:embed static
var static embed.FS

// TokenHeader carries the per-run token.
const TokenHeader = "X-Saga-Forge-Token"

// viewerCSP lets the viewer page (one inline script, inline styles, WebGL) run inside Forge's
// page, and nowhere else.
const viewerCSP = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'self'"

// Server is the UI server.
type Server struct {
	*localweb.Server
	App *app.App
}

// New prepares a server for a.
func New(a *app.App) *Server {
	s := &Server{Server: localweb.New(TokenHeader), App: a}
	s.QueryToken = []string{"/api/events"}
	s.Hint = "open the address Saga Forge opened, or start Saga Forge again"
	return s
}

// Serve runs until ctx ends.
func (s *Server) Serve(ctx context.Context, ln net.Listener) error {
	return s.Server.Serve(ctx, ln, s.Handler())
}

// Handler is the whole site.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	sub, _ := fs.Sub(static, "static")
	files := http.FileServerFS(sub)
	mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		files.ServeHTTP(w, r)
	}))
	mux.HandleFunc("/ping", func(w http.ResponseWriter, r *http.Request) {
		localweb.WriteJSON(w, http.StatusOK, map[string]string{"app": "sagaforge", "version": app.Version})
	})
	mux.Handle("/view/", sameSite(http.HandlerFunc(s.viewer)))
	mux.Handle("/files/", sameSite(http.HandlerFunc(s.preview)))
	api := http.NewServeMux()
	s.routes(api)
	mux.Handle("/api/", s.Guard(api))
	return s.Headers(mux)
}

// sameSite refuses requests other sites' pages make (their <img> or fetch to 127.0.0.1).
func sameSite(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if site := r.Header.Get("Sec-Fetch-Site"); site != "" && site != "same-origin" && site != "none" {
			http.Error(w, "cross-site request refused", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}

var selectorRE = regexp.MustCompile(`^[a-z][a-z0-9_]{2,31}/[a-z][a-z0-9_]{2,31}$`)

// viewer proxies /view/<saga>/<id>/… to that landmark's running `sagas view --serve`.
func (s *Server) viewer(w http.ResponseWriter, r *http.Request) {
	parts := strings.SplitN(strings.TrimPrefix(r.URL.Path, "/view/"), "/", 3)
	if len(parts) < 3 || !selectorRE.MatchString(parts[0]+"/"+parts[1]) {
		http.NotFound(w, r)
		return
	}
	target := s.App.ViewerURL(parts[0] + "/" + parts[1])
	if target == "" {
		http.Error(w, "the viewer of this landmark is not running; open it in Saga Forge", http.StatusNotFound)
		return
	}
	u, err := url.Parse(target)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	rest := "/" + parts[2]
	w.Header().Del("Content-Security-Policy")
	w.Header().Del("X-Frame-Options")
	proxy := &httputil.ReverseProxy{
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.Out.URL.Scheme, pr.Out.URL.Host = u.Scheme, u.Host
			pr.Out.URL.Path, pr.Out.URL.RawPath = rest, ""
			pr.Out.Host = u.Host
		},
		ModifyResponse: func(resp *http.Response) error {
			resp.Header.Set("Content-Security-Policy", viewerCSP)
			resp.Header.Set("X-Frame-Options", "SAMEORIGIN")
			return nil
		},
	}
	proxy.ServeHTTP(w, r)
}

var previewRE = regexp.MustCompile(`^content/[a-z][a-z0-9_]{2,31}/[a-z][a-z0-9_]{2,31}/preview\.png$`)

// preview serves content/<saga>/<id>/preview.png of the workspace.
func (s *Server) preview(w http.ResponseWriter, r *http.Request) {
	rel := strings.TrimPrefix(r.URL.Path, "/files/")
	if !previewRE.MatchString(rel) {
		http.NotFound(w, r)
		return
	}
	w.Header().Set("Content-Type", "image/png")
	http.ServeFile(w, r, filepath.Join(s.App.Home.Workspace(), filepath.FromSlash(rel)))
}

// ---------------------------------------------------------------- API

func (s *Server) routes(mux *http.ServeMux) {
	a := s.App
	mux.HandleFunc("GET /api/status", func(w http.ResponseWriter, r *http.Request) {
		ok(w, a.Status(r.Context()))
	})
	mux.HandleFunc("POST /api/setup", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Update bool `json:"update"`
		}
		if decode(w, r, &body) {
			job(w)(a.RunSetup(body.Update))
		}
	})
	mux.HandleFunc("GET /api/catalog", func(w http.ResponseWriter, r *http.Request) {
		c, err := a.Catalog(r.Context())
		reply(w, c, err)
	})
	mux.HandleFunc("GET /api/drafts", func(w http.ResponseWriter, r *http.Request) {
		d, err := a.Drafts(r.Context())
		if d == nil {
			d = []workspace.Draft{}
		}
		reply(w, d, err)
	})
	mux.HandleFunc("POST /api/drafts/open", func(w http.ResponseWriter, r *http.Request) {
		var body struct{ Name string }
		if decode(w, r, &body) {
			reply(w, nil, a.OpenDraft(r.Context(), body.Name))
		}
	})
	mux.HandleFunc("POST /api/drafts/discard", func(w http.ResponseWriter, r *http.Request) {
		var body struct{ Name string }
		if decode(w, r, &body) {
			reply(w, nil, a.DiscardDraft(r.Context(), body.Name))
		}
	})
	mux.HandleFunc("POST /api/drafts/update", func(w http.ResponseWriter, r *http.Request) {
		var body struct{ Keep string }
		if decode(w, r, &body) {
			job(w)(a.Update(body.Keep))
		}
	})
	mux.HandleFunc("POST /api/upload", func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, 80<<20) // 50 MB as base64, and some room
		var body struct {
			Name string `json:"name"`
			Data string `json:"data"`
		}
		if !decode(w, r, &body) {
			return
		}
		data, err := base64.StdEncoding.DecodeString(body.Data)
		if err != nil {
			fail(w, http.StatusBadRequest, err)
			return
		}
		path, err := a.Upload(body.Name, data)
		reply(w, map[string]string{"path": path}, err)
	})
	mux.HandleFunc("POST /api/landmarks", func(w http.ResponseWriter, r *http.Request) {
		var req tools.Request
		if decode(w, r, &req) {
			job(w)(a.Add(req))
		}
	})
	mux.HandleFunc("POST /api/landmarks/edit", func(w http.ResponseWriter, r *http.Request) {
		var body struct{ Selector string }
		if decode(w, r, &body) && selector(w, body.Selector) {
			reply(w, map[string]string{"draft": app.EditDraft(body.Selector)}, a.Edit(r.Context(), body.Selector))
		}
	})
	mux.HandleFunc("POST /api/landmarks/set", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Selector string         `json:"selector"`
			Values   map[string]any `json:"values"`
		}
		if decode(w, r, &body) && selector(w, body.Selector) {
			reply(w, nil, a.Set(r.Context(), body.Selector, body.Values))
		}
	})
	mux.HandleFunc("POST /api/landmarks/command", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Selector string   `json:"selector"`
			Lines    []string `json:"lines"`
		}
		if decode(w, r, &body) && selector(w, body.Selector) {
			job(w)(a.Command(body.Selector, body.Lines))
		}
	})
	mux.HandleFunc("GET /api/landmarks/lint", func(w http.ResponseWriter, r *http.Request) {
		sel := r.URL.Query().Get("selector")
		if selector(w, sel) {
			f, err := a.Lint(r.Context(), sel)
			if f == nil {
				f = []tools.Finding{}
			}
			reply(w, f, err)
		}
	})
	mux.HandleFunc("GET /api/vocabulary", func(w http.ResponseWriter, r *http.Request) {
		v, err := a.Vocabulary()
		reply(w, v, err)
	})
	mux.HandleFunc("GET /api/hints", func(w http.ResponseWriter, r *http.Request) {
		h, err := a.Hints(r.Context(), r.URL.Query().Get("text"))
		reply(w, h, err)
	})
	mux.HandleFunc("POST /api/view", func(w http.ResponseWriter, r *http.Request) {
		var body struct{ Selector string }
		if decode(w, r, &body) && selector(w, body.Selector) {
			_, err := a.View(r.Context(), body.Selector)
			reply(w, map[string]string{"path": "/view/" + body.Selector + "/"}, err)
		}
	})
	mux.HandleFunc("GET /api/games", func(w http.ResponseWriter, r *http.Request) {
		g, err := a.Games(r.Context())
		reply(w, g, err)
	})
	mux.HandleFunc("POST /api/games/sync", func(w http.ResponseWriter, r *http.Request) {
		var body struct{ ID string }
		if decode(w, r, &body) {
			job(w)(a.SyncGame(body.ID))
		}
	})
	mux.HandleFunc("GET /api/installations", func(w http.ResponseWriter, r *http.Request) {
		ok(w, a.Installations(r.Context()))
	})
	mux.HandleFunc("GET /api/settings", func(w http.ResponseWriter, r *http.Request) { ok(w, a.Settings()) })
	mux.HandleFunc("POST /api/settings", func(w http.ResponseWriter, r *http.Request) {
		var set app.Settings
		if decode(w, r, &set) {
			reply(w, set, a.SaveSettings(set))
		}
	})
	mux.HandleFunc("POST /api/tour", func(w http.ResponseWriter, r *http.Request) {
		var req app.TourRequest
		if decode(w, r, &req) && selector(w, req.Selector) {
			job(w)(a.Tour(req))
		}
	})
	mux.HandleFunc("POST /api/signin", func(w http.ResponseWriter, r *http.Request) {
		d, j, err := a.SignIn(r.Context())
		if err != nil {
			fail(w, http.StatusBadGateway, err)
			return
		}
		ok(w, map[string]any{"user_code": d.UserCode, "verification_uri": d.VerificationURI, "job": j})
	})
	mux.HandleFunc("POST /api/signout", func(w http.ResponseWriter, r *http.Request) { reply(w, nil, a.SignOut()) })
	mux.HandleFunc("POST /api/submit", func(w http.ResponseWriter, r *http.Request) {
		var body struct{ Draft string }
		if decode(w, r, &body) {
			job(w)(a.Submit(body.Draft))
		}
	})
	mux.HandleFunc("GET /api/submissions", func(w http.ResponseWriter, r *http.Request) {
		subs, err := a.Submissions(r.Context())
		reply(w, subs, err)
	})
	mux.HandleFunc("GET /api/jobs/{id}", func(w http.ResponseWriter, r *http.Request) {
		j, found := a.Jobs.Get(r.PathValue("id"))
		if !found {
			fail(w, http.StatusNotFound, errors.New("no such job"))
			return
		}
		ok(w, j)
	})
	mux.HandleFunc("POST /api/jobs/{id}/cancel", func(w http.ResponseWriter, r *http.Request) {
		ok(w, map[string]bool{"cancelled": a.Jobs.Cancel(r.PathValue("id"))})
	})
	mux.HandleFunc("GET /api/events", localweb.Events(a.Jobs))
}

func ok(w http.ResponseWriter, v any) { localweb.WriteJSON(w, http.StatusOK, v) }

func fail(w http.ResponseWriter, status int, err error) {
	localweb.WriteErr(w, status, "failed", err.Error())
}

func reply(w http.ResponseWriter, v any, err error) {
	if err != nil {
		fail(w, http.StatusUnprocessableEntity, err)
		return
	}
	if v == nil {
		v = map[string]bool{"ok": true}
	}
	ok(w, v)
}

func job(w http.ResponseWriter) func(*jobs.Job, error) {
	return func(j *jobs.Job, err error) { reply(w, j, err) }
}

func decode(w http.ResponseWriter, r *http.Request, v any) bool {
	if err := json.NewDecoder(r.Body).Decode(v); err != nil {
		fail(w, http.StatusBadRequest, err)
		return false
	}
	return true
}

func selector(w http.ResponseWriter, sel string) bool {
	if !selectorRE.MatchString(sel) {
		fail(w, http.StatusBadRequest, errors.New("a landmark is named <saga>/<id>"))
		return false
	}
	return true
}
