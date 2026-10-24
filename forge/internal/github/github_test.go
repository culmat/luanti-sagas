package github

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

// fake is a small in-memory GitHub: refs, commits, trees as path->blob maps, forks and pulls.
type fake struct {
	mu      sync.Mutex
	login   string
	push    bool
	refs    map[string]string            // repo/ref -> commit
	commits map[string][2]string         // commit -> {tree, parent}
	trees   map[string]map[string]string // tree -> path -> blob
	blobs   map[string]string
	pulls   []Pull
	forked  bool
	polls   int
	moved   int // how many times main moves under a direct push
	n       int
}

func newFake(push bool) *fake {
	f := &fake{login: "jane", push: push, refs: map[string]string{}, commits: map[string][2]string{},
		trees: map[string]map[string]string{"t0": {"content/ruins/tower/landmark.toml": "b0"}}, blobs: map[string]string{"b0": "old"}}
	f.commits["c0"] = [2]string{"t0", ""}
	f.refs["culmat/luanti-sagas heads/main"] = "c0"
	return f
}

func (f *fake) id(prefix string) string { f.n++; return fmt.Sprintf("%s%d", prefix, f.n) }

func (f *fake) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	reply := func(code int, v any) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(code)
		_ = json.NewEncoder(w).Encode(v)
	}
	var body map[string]any
	_ = json.NewDecoder(r.Body).Decode(&body)
	p := r.URL.Path
	switch {
	case p == "/login/device/code":
		reply(200, map[string]any{"device_code": "dc", "user_code": "ABCD-1234", "verification_uri": "https://github.com/login/device", "expires_in": 900, "interval": 5})
	case p == "/login/oauth/access_token":
		f.polls++
		if f.polls < 2 {
			reply(200, map[string]string{"error": "authorization_pending"})
		} else {
			reply(200, map[string]string{"access_token": "tok"})
		}
	case p == "/user":
		reply(200, map[string]any{"login": f.login, "id": 7})
	case p == "/repos/culmat/luanti-sagas" && r.Method == http.MethodGet:
		reply(200, map[string]any{"full_name": "culmat/luanti-sagas", "default_branch": "main", "permissions": map[string]bool{"push": f.push}})
	case p == "/repos/culmat/luanti-sagas/forks":
		f.forked = true
		f.refs["jane/luanti-sagas heads/main"] = f.refs["culmat/luanti-sagas heads/main"]
		reply(202, map[string]any{"full_name": "jane/luanti-sagas", "default_branch": "main", "fork": true})
	case p == "/repos/jane/luanti-sagas/merge-upstream":
		reply(200, map[string]string{})
	case strings.Contains(p, "/git/ref/"):
		repo, ref, _ := strings.Cut(strings.TrimPrefix(p, "/repos/"), "/git/ref/")
		if sha, ok := f.refs[repo+" "+ref]; ok {
			reply(200, map[string]any{"object": map[string]string{"sha": sha}})
		} else {
			reply(404, map[string]string{"message": "Not Found"})
		}
	case strings.Contains(p, "/git/commits/"):
		sha := p[strings.LastIndex(p, "/")+1:]
		reply(200, map[string]any{"tree": map[string]string{"sha": f.commits[sha][0]}})
	case strings.HasSuffix(p, "/git/blobs"):
		sha := f.id("b")
		f.blobs[sha] = body["content"].(string)
		reply(201, map[string]string{"sha": sha})
	case strings.HasSuffix(p, "/git/trees"):
		t := map[string]string{}
		for k, v := range f.trees[body["base_tree"].(string)] {
			t[k] = v
		}
		for _, e := range body["tree"].([]any) {
			e := e.(map[string]any)
			if e["sha"] == nil {
				delete(t, e["path"].(string))
			} else {
				t[e["path"].(string)] = e["sha"].(string)
			}
		}
		sha := f.id("t")
		f.trees[sha] = t
		reply(201, map[string]string{"sha": sha})
	case strings.HasSuffix(p, "/git/commits"):
		sha := f.id("c")
		f.commits[sha] = [2]string{body["tree"].(string), body["parents"].([]any)[0].(string)}
		reply(201, map[string]string{"sha": sha})
	case strings.Contains(p, "/git/refs/") && r.Method == http.MethodPatch:
		repo, ref, _ := strings.Cut(strings.TrimPrefix(p, "/repos/"), "/git/refs/")
		cur, ok := f.refs[repo+" "+ref]
		if !ok {
			reply(422, map[string]string{"message": "Reference does not exist"})
			return
		}
		sha := body["sha"].(string)
		if f.moved > 0 && repo == "culmat/luanti-sagas" {
			f.moved--
			moved := f.id("c")
			f.commits[moved] = [2]string{"t0", cur}
			f.refs[repo+" "+ref] = moved
			reply(422, map[string]string{"message": "Update is not a fast forward"})
			return
		}
		if body["force"] != true && f.commits[sha][1] != cur {
			reply(422, map[string]string{"message": "Update is not a fast forward"})
			return
		}
		f.refs[repo+" "+ref] = sha
		reply(200, map[string]any{})
	case strings.HasSuffix(p, "/git/refs") && r.Method == http.MethodPost:
		repo := strings.TrimSuffix(strings.TrimPrefix(p, "/repos/"), "/git/refs")
		f.refs[repo+" "+strings.TrimPrefix(body["ref"].(string), "refs/")] = body["sha"].(string)
		reply(201, map[string]any{})
	case p == "/repos/culmat/luanti-sagas/pulls" && r.Method == http.MethodGet:
		var open []Pull
		for _, pl := range f.pulls {
			if "jane:"+pl.Head.Ref == r.URL.Query().Get("head") {
				open = append(open, pl)
			}
		}
		reply(200, open)
	case p == "/repos/culmat/luanti-sagas/pulls" && r.Method == http.MethodPost:
		pl := Pull{Number: 10 + len(f.pulls), Title: body["title"].(string), State: "open", HTMLURL: "https://github.com/culmat/luanti-sagas/pull/10"}
		pl.Head.Ref = strings.TrimPrefix(body["head"].(string), "jane:")
		f.pulls = append(f.pulls, pl)
		reply(201, pl)
	default:
		reply(404, map[string]string{"message": "Not Found " + r.Method + " " + p})
	}
}

func client(f *fake) (*Client, func()) {
	srv := httptest.NewServer(f)
	c := &Client{API: srv.URL, Web: srv.URL, Token: "tok", HTTP: srv.Client(),
		Wait: func(context.Context, time.Duration) error { return nil }}
	return c, srv.Close
}

func contribution() Contribution {
	return Contribution{Branch: "forge/ruins-old_tower", Title: "Add ruins/old_tower", Body: "From Saga Forge.", Changes: []Change{
		{Path: "content/ruins/old_tower/landmark.toml", Content: []byte("id = \"old_tower\"\n")},
		{Path: "content/ruins/tower/landmark.toml"}, // deleted
	}}
}

func TestDeviceFlow(t *testing.T) {
	f := newFake(false)
	c, done := client(f)
	defer done()
	d, err := c.StartDeviceFlow(context.Background(), "cid")
	if err != nil || d.UserCode != "ABCD-1234" {
		t.Fatalf("%+v %v", d, err)
	}
	tok, err := c.WaitForToken(context.Background(), "cid", d)
	if err != nil || tok != "tok" || f.polls != 2 {
		t.Fatalf("token %q after %d polls: %v", tok, f.polls, err)
	}
}

func TestSubmitFromAFork(t *testing.T) {
	f := newFake(false)
	c, done := client(f)
	defer done()
	res, err := c.Submit(context.Background(), Upstream, contribution())
	if err != nil {
		t.Fatal(err)
	}
	if res.Direct || res.Pull == nil || res.Repo != "jane/luanti-sagas" || !f.forked {
		t.Fatalf("%+v", res)
	}
	head := f.refs["jane/luanti-sagas heads/forge/ruins-old_tower"]
	tree := f.trees[f.commits[head][0]]
	if f.commits[head][1] != "c0" || tree["content/ruins/old_tower/landmark.toml"] == "" || tree["content/ruins/tower/landmark.toml"] != "" {
		t.Fatalf("commit %s tree %v", head, tree)
	}
	if f.refs["culmat/luanti-sagas heads/main"] != "c0" {
		t.Fatal("a fork submission must not touch upstream main")
	}
	again, err := c.Submit(context.Background(), Upstream, contribution())
	if err != nil || len(f.pulls) != 1 || again.Pull.Number != res.Pull.Number {
		t.Fatalf("a second submission updates the same pull request: %+v %v", again, err)
	}
}

func TestSubmitWithWriteAccessRetriesWhenMainMoves(t *testing.T) {
	f := newFake(true)
	f.moved = 1
	c, done := client(f)
	defer done()
	res, err := c.Submit(context.Background(), Upstream, contribution())
	if err != nil {
		t.Fatal(err)
	}
	main := f.refs["culmat/luanti-sagas heads/main"]
	if !res.Direct || res.Commit != main || f.forked || len(f.pulls) != 0 {
		t.Fatalf("%+v main=%s", res, main)
	}
	if parent := f.commits[main][1]; parent == "c0" {
		t.Fatal("the retry must build on the main that moved")
	}
}
