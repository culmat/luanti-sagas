package setup

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
)

// Releases of Saga Forge are tagged forge/v<version> in luanti-sagas (.github/workflows/forge.yml).
const releasesAPI = "https://api.github.com/repos/culmat/luanti-sagas/releases?per_page=50"

// Release is a Saga Forge release.
type Release struct {
	Version string
	Assets  map[string]string // file name -> download URL
}

// LatestRelease finds the newest forge/v* release.
func LatestRelease(ctx context.Context, client *http.Client, api string) (*Release, error) {
	if api == "" {
		api = releasesAPI
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, api, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", userAgent)
	resp, err := client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("GitHub releases: HTTP %d", resp.StatusCode)
	}
	var list []struct {
		Tag        string `json:"tag_name"`
		Draft      bool   `json:"draft"`
		Prerelease bool   `json:"prerelease"`
		Assets     []struct {
			Name string `json:"name"`
			URL  string `json:"browser_download_url"`
		} `json:"assets"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&list); err != nil {
		return nil, err
	}
	var best *Release
	for _, r := range list {
		v, ok := strings.CutPrefix(r.Tag, "forge/v")
		if !ok || r.Draft || r.Prerelease {
			continue
		}
		if best == nil || Newer(v, best.Version) {
			best = &Release{Version: v, Assets: map[string]string{}}
			for _, a := range r.Assets {
				best.Assets[a.Name] = a.URL
			}
		}
	}
	if best == nil {
		return nil, errors.New("no Saga Forge release yet")
	}
	return best, nil
}

// Newer reports whether version a is newer than b (dotted numbers; "dev" is never newer).
func Newer(a, b string) bool {
	pa, pb := strings.Split(a, "."), strings.Split(b, ".")
	for i := 0; i < max(len(pa), len(pb)); i++ {
		var x, y int
		if i < len(pa) {
			x, _ = strconv.Atoi(pa[i])
		}
		if i < len(pb) {
			y, _ = strconv.Atoi(pb[i])
		}
		if x != y {
			return x > y
		}
	}
	return false
}

// ManagedBy names the package manager that installed exe ("" when none): such installs update
// through it.
func ManagedBy(exe string) string {
	p := strings.ReplaceAll(exe, `\`, "/") // Windows paths, on any system
	switch {
	case strings.Contains(p, "/Cellar/") || strings.Contains(p, "/homebrew/") || strings.Contains(p, "/linuxbrew/"):
		return "brew upgrade sagaforge"
	case strings.Contains(strings.ToLower(p), "/scoop/apps/"):
		return "scoop update sagaforge"
	case strings.Contains(strings.ToLower(p), "/winget/"):
		return "winget upgrade sagaforge"
	}
	return ""
}

// Upgrade replaces the running binary exe with release r's build for this system, after checking
// it against the release's SHA256SUMS.
func Upgrade(ctx context.Context, client *http.Client, r *Release, exe string, logf Logf) error {
	ext := ".tar.gz"
	if runtime.GOOS == "windows" {
		ext = ".zip"
	}
	name := fmt.Sprintf("sagaforge_%s_%s_%s%s", r.Version, runtime.GOOS, runtime.GOARCH, ext)
	url, ok := r.Assets[name]
	if !ok {
		return fmt.Errorf("release %s has no %s", r.Version, name)
	}
	sums, ok := r.Assets["SHA256SUMS"]
	if !ok {
		return fmt.Errorf("release %s has no SHA256SUMS", r.Version)
	}
	sum, err := checksumFor(ctx, client, sums, name)
	if err != nil {
		return err
	}
	dir, err := os.MkdirTemp(filepath.Dir(exe), ".sagaforge-upgrade-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(dir)
	archive := filepath.Join(dir, name)
	logf("downloading %s", url)
	if err := fetch(ctx, client, pinned{url, sum}, archive); err != nil {
		return err
	}
	bin := filepath.Base(exe)
	if err := extract(archive, dir, bin); err != nil {
		return err
	}
	// Windows can't replace a running .exe, but it can rename it.
	old := exe + ".old"
	_ = os.Remove(old)
	if err := os.Rename(exe, old); err != nil {
		return err
	}
	if err := os.Rename(filepath.Join(dir, bin), exe); err != nil {
		_ = os.Rename(old, exe)
		return err
	}
	if runtime.GOOS != "windows" {
		_ = os.Remove(old)
	}
	return nil
}

func checksumFor(ctx context.Context, client *http.Client, url, name string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", userAgent)
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("SHA256SUMS: HTTP %d", resp.StatusCode)
	}
	sc := bufio.NewScanner(resp.Body)
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) == 2 && strings.TrimPrefix(f[1], "*") == name {
			return f[0], nil
		}
	}
	return "", fmt.Errorf("SHA256SUMS lists no %s", name)
}
