package setup

import (
	"archive/tar"
	"archive/zip"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"runtime"
	"strings"
)

// A pinned download: the published release file and its sha256, checked before anything is used.
type pinned struct {
	url    string
	sha256 string
}

// uv 0.11.8 (astral-sh/uv), checksums from the release's .sha256 files.
const uvVersion = "0.11.8"

var uvFiles = map[string]pinned{
	"darwin/arm64":  {"uv-aarch64-apple-darwin.tar.gz", "c729adb365114e844dd7f9316313a7ed6443b89bb5681d409eebac78b0bd06c8"},
	"darwin/amd64":  {"uv-x86_64-apple-darwin.tar.gz", "c59d73bf34b58bc8e33a11629f7a255c11789fd00f03cd3e68ab2d1603645de9"},
	"linux/amd64":   {"uv-x86_64-unknown-linux-gnu.tar.gz", "56dd1b66701ecb62fe896abb919444e4b83c5e8645cca953e6ddd496ff8a0feb"},
	"linux/arm64":   {"uv-aarch64-unknown-linux-gnu.tar.gz", "eee8dd658d20e5ac85fec9c2326b6cbc9d83a1eef09ef07433e58698ac849591"},
	"windows/amd64": {"uv-x86_64-pc-windows-msvc.zip", "c84629a56e0706b69a47ea35862208af827cb6fbfa1d0ca763c52c67594637e8"},
	"windows/arm64": {"uv-aarch64-pc-windows-msvc.zip", "bb48716e74e4998993f15bc57a55e4d0d73ccbd27a66d7cbed37605f7c67d747"},
}

// jq 1.8.1 (jqlang/jq), checksums from the release's sha256sum.txt. Windows on ARM runs the amd64
// build.
const jqVersion = "1.8.1"

var jqFiles = map[string]pinned{
	"darwin/arm64":  {"jq-macos-arm64", "a9fe3ea2f86dfc72f6728417521ec9067b343277152b114f4e98d8cb0e263603"},
	"darwin/amd64":  {"jq-macos-amd64", "e80dbe0d2a2597e3c11c404f03337b981d74b4a8504b70586c354b7697a7c27f"},
	"linux/amd64":   {"jq-linux-amd64", "020468de7539ce70ef1bceaf7cde2e8c4f2ca6c3afb84642aabc5c97d9fc2a0d"},
	"linux/arm64":   {"jq-linux-arm64", "6bc62f25981328edd3cfcfe6fe51b073f2d7e7710d7ef7fcdac28d4e384fc3d4"},
	"windows/amd64": {"jq-windows-amd64.exe", "23cb60a1354eed6bcc8d9b9735e8c7b388cd1fdcb75726b93bc299ef22dd9334"},
	"windows/arm64": {"jq-windows-amd64.exe", "23cb60a1354eed6bcc8d9b9735e8c7b388cd1fdcb75726b93bc299ef22dd9334"},
}

func platform() string { return runtime.GOOS + "/" + runtime.GOARCH }

func uvDownload() (pinned, error) {
	p, ok := uvFiles[platform()]
	if !ok {
		return pinned{}, fmt.Errorf("no uv build for %s", platform())
	}
	return pinned{"https://github.com/astral-sh/uv/releases/download/" + uvVersion + "/" + p.url, p.sha256}, nil
}

func jqDownload() (pinned, error) {
	p, ok := jqFiles[platform()]
	if !ok {
		return pinned{}, fmt.Errorf("no jq build for %s", platform())
	}
	return pinned{"https://github.com/jqlang/jq/releases/download/jq-" + jqVersion + "/" + p.url, p.sha256}, nil
}

// fetch downloads p into dest (a temp name first) and verifies its sha256.
func fetch(ctx context.Context, client *http.Client, p pinned, dest string) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, p.url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", userAgent)
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("download %s: HTTP %d", p.url, resp.StatusCode)
	}
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(dest), ".download-*")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	h := sha256.New()
	if _, err := io.Copy(io.MultiWriter(tmp, h), io.LimitReader(resp.Body, 512<<20)); err != nil {
		tmp.Close()
		return fmt.Errorf("download %s: %w", p.url, err)
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if got := hex.EncodeToString(h.Sum(nil)); got != p.sha256 {
		return fmt.Errorf("download %s: sha256 %s, expected %s", p.url, got, p.sha256)
	}
	return os.Rename(tmp.Name(), dest)
}

// extract copies the files called one of names out of a .tar.gz or .zip archive into dir.
func extract(archive, dir string, names ...string) error {
	want := map[string]bool{}
	for _, n := range names {
		want[n] = true
	}
	found := 0
	write := func(name string, r io.Reader) error {
		out := filepath.Join(dir, name)
		f, err := os.OpenFile(out+".tmp", os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
		if err != nil {
			return err
		}
		if _, err := io.Copy(f, io.LimitReader(r, 256<<20)); err != nil {
			f.Close()
			return err
		}
		if err := f.Close(); err != nil {
			return err
		}
		found++
		return os.Rename(out+".tmp", out)
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	if strings.HasSuffix(archive, ".zip") {
		z, err := zip.OpenReader(archive)
		if err != nil {
			return err
		}
		defer z.Close()
		for _, f := range z.File {
			base := path.Base(f.Name)
			if !want[base] || f.FileInfo().IsDir() {
				continue
			}
			r, err := f.Open()
			if err != nil {
				return err
			}
			err = write(base, r)
			r.Close()
			if err != nil {
				return err
			}
		}
	} else {
		f, err := os.Open(archive)
		if err != nil {
			return err
		}
		defer f.Close()
		gz, err := gzip.NewReader(f)
		if err != nil {
			return err
		}
		tr := tar.NewReader(gz)
		for {
			hdr, err := tr.Next()
			if err == io.EOF {
				break
			}
			if err != nil {
				return err
			}
			base := path.Base(hdr.Name)
			if hdr.Typeflag != tar.TypeReg || !want[base] {
				continue
			}
			if err := write(base, tr); err != nil {
				return err
			}
		}
	}
	if found != len(names) {
		return fmt.Errorf("%s: expected %s", filepath.Base(archive), strings.Join(names, ", "))
	}
	return nil
}
