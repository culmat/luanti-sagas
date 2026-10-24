package setup

import (
	"archive/tar"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func TestNewer(t *testing.T) {
	for _, c := range []struct {
		a, b string
		want bool
	}{{"0.2.0", "0.1.9", true}, {"0.1.10", "0.1.9", true}, {"0.1.0", "0.1.0", false}, {"0.1", "0.1.1", false}, {"dev", "0.1.0", false}} {
		if got := Newer(c.a, c.b); got != c.want {
			t.Errorf("Newer(%s, %s) = %v", c.a, c.b, got)
		}
	}
}

func TestManagedBy(t *testing.T) {
	if ManagedBy("/opt/homebrew/Cellar/sagaforge/0.1.0/bin/sagaforge") == "" || ManagedBy(`C:\Users\x\scoop\apps\sagaforge\current\sagaforge.exe`) == "" {
		t.Fatal("brew and scoop installs update through their manager")
	}
	if ManagedBy("/Users/x/Downloads/sagaforge") != "" {
		t.Fatal("a downloaded binary updates itself")
	}
}

func targz(t *testing.T, path, name string, content []byte) {
	t.Helper()
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	gz := gzip.NewWriter(f)
	tw := tar.NewWriter(gz)
	if err := tw.WriteHeader(&tar.Header{Name: "dir/" + name, Mode: 0o755, Size: int64(len(content)), Typeflag: tar.TypeReg}); err != nil {
		t.Fatal(err)
	}
	tw.Write(content)
	tw.Close()
	gz.Close()
}

func TestFetchRefusesAWrongChecksum(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.Write([]byte("payload")) }))
	defer srv.Close()
	dest := filepath.Join(t.TempDir(), "f")
	sum := sha256.Sum256([]byte("payload"))
	if err := fetch(context.Background(), srv.Client(), pinned{srv.URL, hex.EncodeToString(sum[:])}, dest); err != nil {
		t.Fatal(err)
	}
	if err := fetch(context.Background(), srv.Client(), pinned{srv.URL, "00"}, dest+"2"); err == nil {
		t.Fatal("a download with another checksum must fail")
	}
	if _, err := os.Stat(dest + "2"); !os.IsNotExist(err) {
		t.Fatal("nothing is kept of a refused download")
	}
}

func TestUpgrade(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the release archive for Windows is a zip; covered on the other systems")
	}
	dir := t.TempDir()
	name := fmt.Sprintf("sagaforge_0.2.0_%s_%s.tar.gz", runtime.GOOS, runtime.GOARCH)
	archive := filepath.Join(dir, name)
	targz(t, archive, "sagaforge", []byte("new binary"))
	data, _ := os.ReadFile(archive)
	sum := sha256.Sum256(data)
	mux := http.NewServeMux()
	var base string
	mux.HandleFunc("/releases", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprintf(w, `[{"tag_name":"v2026.10.24","assets":[]},{"tag_name":"forge/v0.1.0","assets":[]},
			{"tag_name":"forge/v0.2.0","assets":[{"name":%q,"browser_download_url":"%s/a"},{"name":"SHA256SUMS","browser_download_url":"%s/sums"}]}]`, name, base, base)
	})
	mux.HandleFunc("/a", func(w http.ResponseWriter, r *http.Request) { w.Write(data) })
	mux.HandleFunc("/sums", func(w http.ResponseWriter, r *http.Request) { fmt.Fprintf(w, "%x  %s\n", sum, name) })
	srv := httptest.NewServer(mux)
	defer srv.Close()
	base = srv.URL
	r, err := LatestRelease(context.Background(), srv.Client(), srv.URL+"/releases")
	if err != nil || r.Version != "0.2.0" {
		t.Fatalf("%+v %v", r, err)
	}
	exe := filepath.Join(dir, "bin", "sagaforge")
	os.MkdirAll(filepath.Dir(exe), 0o755)
	os.WriteFile(exe, []byte("old binary"), 0o755)
	if err := Upgrade(context.Background(), srv.Client(), r, exe, func(string, ...any) {}); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(exe); string(b) != "new binary" {
		t.Fatalf("binary: %q", b)
	}
}
