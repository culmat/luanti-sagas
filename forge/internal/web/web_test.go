package web

import (
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/culmat/luanti-sagas/forge/internal/app"
	"github.com/culmat/luanti-sagas/forge/internal/home"
)

func server(t *testing.T) (*Server, home.Home) {
	t.Helper()
	h := home.New(t.TempDir(), "")
	a, err := app.New(context.Background(), h)
	if err != nil {
		t.Fatal(err)
	}
	return New(a), h
}

func get(t *testing.T, h http.Handler, path string, set func(*http.Request)) *httptest.ResponseRecorder {
	t.Helper()
	r := httptest.NewRequest(http.MethodGet, path, nil)
	if set != nil {
		set(r)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	return w
}

func TestRoutes(t *testing.T) {
	s, h := server(t)
	hd := s.Handler() // registering the routes must not panic
	if w := get(t, hd, "/", nil); w.Code != 200 || !strings.Contains(w.Body.String(), "Saga Forge") {
		t.Fatalf("page: %d", w.Code)
	}
	if w := get(t, hd, "/ping", nil); w.Code != 200 {
		t.Fatalf("ping: %d", w.Code)
	}
	if w := get(t, hd, "/api/status", nil); w.Code != 401 {
		t.Fatalf("api without token: %d", w.Code)
	}
	token := func(r *http.Request) { r.Header.Set(TokenHeader, s.Token) }
	if w := get(t, hd, "/api/status", token); w.Code != 200 || !strings.Contains(w.Body.String(), `"ready":false`) {
		t.Fatalf("status: %d %s", w.Code, w.Body)
	}
	if w := get(t, hd, "/api/catalog", token); w.Code != 422 || !strings.Contains(w.Body.String(), "not set up") {
		t.Fatalf("catalog before setup: %d %s", w.Code, w.Body)
	}
	// previews: only content/<saga>/<id>/preview.png, and not for other sites' pages
	png := filepath.Join(h.Workspace(), "content", "ruins", "tower", "preview.png")
	if err := os.MkdirAll(filepath.Dir(png), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(png, []byte("\x89PNG"), 0o644); err != nil {
		t.Fatal(err)
	}
	if w := get(t, hd, "/files/content/ruins/tower/preview.png", nil); w.Code != 200 {
		t.Fatalf("preview: %d", w.Code)
	}
	for _, bad := range []string{"/files/content/ruins/tower/landmark.toml", "/files/../state/state.json", "/files/content/ruins/../../x/preview.png"} {
		if w := get(t, hd, bad, nil); w.Code == 200 {
			t.Fatalf("%s must not be served", bad)
		}
	}
	cross := func(r *http.Request) { r.Header.Set("Sec-Fetch-Site", "cross-site") }
	if w := get(t, hd, "/files/content/ruins/tower/preview.png", cross); w.Code != 403 {
		t.Fatalf("cross-site preview: %d", w.Code)
	}
	if w := get(t, hd, "/view/ruins/tower/", nil); w.Code != 404 {
		t.Fatalf("viewer that is not running: %d", w.Code)
	}
}

func TestViewerProxy(t *testing.T) {
	s, _ := server(t)
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("viewer " + r.URL.Path + "?" + r.URL.RawQuery))
	}))
	defer backend.Close()
	s.App.TestViewer("ruins/tower", backend.URL+"/")
	w := get(t, s.Handler(), "/view/ruins/tower/size?target=12", nil)
	if w.Code != 200 || w.Body.String() != "viewer /size?target=12" {
		t.Fatalf("%d %q", w.Code, w.Body)
	}
	if csp := w.Header().Values("Content-Security-Policy"); len(csp) != 1 || csp[0] != viewerCSP {
		t.Fatalf("viewer CSP %v", csp)
	}
	if w.Header().Get("X-Frame-Options") != "SAMEORIGIN" {
		t.Fatal("the viewer must be allowed in Forge's own frame")
	}
}
