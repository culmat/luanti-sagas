// Package github signs a contributor in with GitHub's device flow and submits a draft without git
// credentials: through the REST API it forks culmat/luanti-sagas, writes the changed files as blobs,
// a tree and a commit on top of the newest main, points a branch of the fork at it and opens a pull
// request. Someone with write access gets the same commit on main directly.
package github

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
)

// ClientID of the "Saga Forge" OAuth app (device flow, no secret). SAGAFORGE_GITHUB_CLIENT_ID
// overrides it.
const ClientID = ""

// Upstream is the repository contributions go to.
const Upstream = "culmat/luanti-sagas"

const userAgent = "sagaforge (+https://github.com/culmat/luanti-sagas)"

// Client talks to GitHub as one user (Token may be empty for device-flow calls).
type Client struct {
	API   string // https://api.github.com
	Web   string // https://github.com
	Token string
	HTTP  *http.Client
	// Wait pauses between polls (tests make it instant).
	Wait func(ctx context.Context, d time.Duration) error
}

// New returns a client for github.com.
func New(token string) *Client {
	return &Client{API: "https://api.github.com", Web: "https://github.com", Token: token,
		HTTP: &http.Client{Timeout: 60 * time.Second}, Wait: sleep}
}

func sleep(ctx context.Context, d time.Duration) error {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-t.C:
		return nil
	}
}

// ClientIDFor returns the OAuth app's client id, or an error while none is registered.
func ClientIDFor() (string, error) {
	if id := os.Getenv("SAGAFORGE_GITHUB_CLIENT_ID"); id != "" {
		return id, nil
	}
	if ClientID == "" {
		return "", errors.New("this Saga Forge build has no GitHub sign-in yet (no OAuth app registered)")
	}
	return ClientID, nil
}

// APIError is a GitHub response that was not 2xx.
type APIError struct {
	Status  int
	Message string
	Path    string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("GitHub %s: %d %s", e.Path, e.Status, e.Message)
}

// IsStatus reports whether err is an APIError with that status.
func IsStatus(err error, status int) bool {
	var e *APIError
	return errors.As(err, &e) && e.Status == status
}

func (c *Client) do(ctx context.Context, method, path string, body, out any) error {
	var rd io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.API+path, rd)
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("X-GitHub-Api-Version", "2022-11-28")
	req.Header.Set("User-Agent", userAgent)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.Token != "" {
		req.Header.Set("Authorization", "Bearer "+c.Token)
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	data, err := io.ReadAll(io.LimitReader(resp.Body, 32<<20))
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		var e struct {
			Message string `json:"message"`
		}
		_ = json.Unmarshal(data, &e)
		if e.Message == "" {
			e.Message = http.StatusText(resp.StatusCode)
		}
		return &APIError{Status: resp.StatusCode, Message: e.Message, Path: path}
	}
	if out != nil && len(data) > 0 {
		return json.Unmarshal(data, out)
	}
	return nil
}

// ---------------------------------------------------------------- device flow

// DeviceCode is what the user types at VerificationURI.
type DeviceCode struct {
	DeviceCode      string `json:"device_code"`
	UserCode        string `json:"user_code"`
	VerificationURI string `json:"verification_uri"`
	ExpiresIn       int    `json:"expires_in"`
	Interval        int    `json:"interval"`
}

func (c *Client) form(ctx context.Context, path string, values url.Values, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.Web+path, strings.NewReader(values.Encode()))
	if err != nil {
		return err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("User-Agent", userAgent)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return &APIError{Status: resp.StatusCode, Message: http.StatusText(resp.StatusCode), Path: path}
	}
	return json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(out)
}

// StartDeviceFlow asks GitHub for a code the user confirms in the browser.
func (c *Client) StartDeviceFlow(ctx context.Context, clientID string) (DeviceCode, error) {
	var d DeviceCode
	err := c.form(ctx, "/login/device/code", url.Values{"client_id": {clientID}, "scope": {"public_repo"}}, &d)
	if err == nil && d.DeviceCode == "" {
		err = errors.New("GitHub sent no device code (is device flow enabled for the OAuth app?)")
	}
	return d, err
}

// ErrDenied means the user declined the sign-in, or the code expired.
var ErrDenied = errors.New("sign-in was declined or the code expired")

// WaitForToken polls until the user confirmed the code and returns the access token.
func (c *Client) WaitForToken(ctx context.Context, clientID string, d DeviceCode) (string, error) {
	interval := time.Duration(max(d.Interval, 5)) * time.Second
	deadline := time.Now().Add(time.Duration(max(d.ExpiresIn, 60)) * time.Second)
	for time.Now().Before(deadline) {
		if err := c.Wait(ctx, interval); err != nil {
			return "", err
		}
		var r struct {
			AccessToken string `json:"access_token"`
			Error       string `json:"error"`
			Interval    int    `json:"interval"`
		}
		err := c.form(ctx, "/login/oauth/access_token", url.Values{
			"client_id":   {clientID},
			"device_code": {d.DeviceCode},
			"grant_type":  {"urn:ietf:params:oauth:grant-type:device_code"},
		}, &r)
		if err != nil {
			return "", err
		}
		switch r.Error {
		case "":
			if r.AccessToken != "" {
				return r.AccessToken, nil
			}
		case "authorization_pending":
		case "slow_down":
			interval = time.Duration(max(r.Interval, int(interval/time.Second)+5)) * time.Second
		case "expired_token", "access_denied":
			return "", ErrDenied
		default:
			return "", fmt.Errorf("GitHub sign-in: %s", r.Error)
		}
	}
	return "", ErrDenied
}

// ---------------------------------------------------------------- REST

// User is the signed-in account.
type User struct {
	Login string `json:"login"`
	ID    int64  `json:"id"`
	Name  string `json:"name"`
}

// User returns the signed-in account.
func (c *Client) User(ctx context.Context) (User, error) {
	var u User
	err := c.do(ctx, http.MethodGet, "/user", nil, &u)
	return u, err
}

// Repo is the part of a repository Forge needs.
type Repo struct {
	FullName      string `json:"full_name"`
	DefaultBranch string `json:"default_branch"`
	Fork          bool   `json:"fork"`
	Permissions   struct {
		Push bool `json:"push"`
	} `json:"permissions"`
}

// Repo reads owner/name.
func (c *Client) Repo(ctx context.Context, full string) (Repo, error) {
	var r Repo
	err := c.do(ctx, http.MethodGet, "/repos/"+full, nil, &r)
	return r, err
}

// Fork returns the user's fork of full, creating it and waiting until it can be used.
func (c *Client) Fork(ctx context.Context, full string) (Repo, error) {
	var r Repo
	if err := c.do(ctx, http.MethodPost, "/repos/"+full+"/forks", map[string]any{"default_branch_only": true}, &r); err != nil {
		return r, err
	}
	for i := 0; i < 30; i++ {
		if _, err := c.Ref(ctx, r.FullName, "heads/"+r.DefaultBranch); err == nil {
			return r, nil
		}
		if err := c.Wait(ctx, 2*time.Second); err != nil {
			return r, err
		}
	}
	return r, fmt.Errorf("the fork %s is not ready yet; try again in a minute", r.FullName)
}

// MergeUpstream brings the fork's branch up to the upstream one (a fork whose main has diverged
// keeps it; the contribution is based on upstream main anyway).
func (c *Client) MergeUpstream(ctx context.Context, fork, branch string) error {
	err := c.do(ctx, http.MethodPost, "/repos/"+fork+"/merge-upstream", map[string]string{"branch": branch}, nil)
	if IsStatus(err, http.StatusConflict) {
		return nil
	}
	return err
}

// Ref returns the commit a ref ("heads/main") points to.
func (c *Client) Ref(ctx context.Context, full, ref string) (string, error) {
	var r struct {
		Object struct {
			SHA string `json:"sha"`
		} `json:"object"`
	}
	err := c.do(ctx, http.MethodGet, "/repos/"+full+"/git/ref/"+ref, nil, &r)
	return r.Object.SHA, err
}

// CommitTree returns the tree of a commit.
func (c *Client) CommitTree(ctx context.Context, full, sha string) (string, error) {
	var r struct {
		Tree struct {
			SHA string `json:"sha"`
		} `json:"tree"`
	}
	err := c.do(ctx, http.MethodGet, "/repos/"+full+"/git/commits/"+sha, nil, &r)
	return r.Tree.SHA, err
}

// Blob stores content and returns its sha.
func (c *Client) Blob(ctx context.Context, full string, content []byte) (string, error) {
	var r struct {
		SHA string `json:"sha"`
	}
	err := c.do(ctx, http.MethodPost, "/repos/"+full+"/git/blobs",
		map[string]string{"content": base64.StdEncoding.EncodeToString(content), "encoding": "base64"}, &r)
	return r.SHA, err
}

// TreeEntry is one changed path; a nil SHA deletes it.
type TreeEntry struct {
	Path string  `json:"path"`
	Mode string  `json:"mode"`
	Type string  `json:"type"`
	SHA  *string `json:"sha"`
}

// Tree creates a tree from base with entries changed.
func (c *Client) Tree(ctx context.Context, full, base string, entries []TreeEntry) (string, error) {
	var r struct {
		SHA string `json:"sha"`
	}
	err := c.do(ctx, http.MethodPost, "/repos/"+full+"/git/trees", map[string]any{"base_tree": base, "tree": entries}, &r)
	return r.SHA, err
}

// Commit creates a commit.
func (c *Client) Commit(ctx context.Context, full, message, tree string, parents []string) (string, error) {
	var r struct {
		SHA string `json:"sha"`
	}
	err := c.do(ctx, http.MethodPost, "/repos/"+full+"/git/commits",
		map[string]any{"message": message, "tree": tree, "parents": parents}, &r)
	return r.SHA, err
}

// SetRef points refs/<ref> at sha, creating it when it does not exist.
func (c *Client) SetRef(ctx context.Context, full, ref, sha string, force bool) error {
	err := c.do(ctx, http.MethodPatch, "/repos/"+full+"/git/refs/"+ref, map[string]any{"sha": sha, "force": force}, nil)
	if IsStatus(err, http.StatusUnprocessableEntity) || IsStatus(err, http.StatusNotFound) {
		if _, gerr := c.Ref(ctx, full, ref); IsStatus(gerr, http.StatusNotFound) {
			return c.do(ctx, http.MethodPost, "/repos/"+full+"/git/refs", map[string]string{"ref": "refs/" + ref, "sha": sha}, nil)
		}
	}
	return err
}

// Pull is a pull request.
type Pull struct {
	Number  int    `json:"number"`
	Title   string `json:"title"`
	HTMLURL string `json:"html_url"`
	State   string `json:"state"`
	Merged  bool   `json:"merged"`
	Draft   bool   `json:"draft"`
	Head    struct {
		Ref string `json:"ref"`
		SHA string `json:"sha"`
	} `json:"head"`
	UpdatedAt time.Time `json:"updated_at"`
}

// OpenPull finds the open pull request from head ("user:branch"), if any.
func (c *Client) OpenPull(ctx context.Context, full, head string) (*Pull, error) {
	var pulls []Pull
	err := c.do(ctx, http.MethodGet, "/repos/"+full+"/pulls?state=open&head="+url.QueryEscape(head), nil, &pulls)
	if err != nil || len(pulls) == 0 {
		return nil, err
	}
	return &pulls[0], nil
}

// CreatePull opens a pull request from head ("user:branch") into base.
func (c *Client) CreatePull(ctx context.Context, full, title, head, base, body string) (Pull, error) {
	var p Pull
	err := c.do(ctx, http.MethodPost, "/repos/"+full+"/pulls", map[string]any{
		"title": title, "head": head, "base": base, "body": body, "maintainer_can_modify": true,
	}, &p)
	return p, err
}

// Submission is a pull request of the user's, with what Forge shows about it.
type Submission struct {
	Pull
	Checks   string    `json:"checks"` // success, failure, pending, or ""
	Pictures string    `json:"pictures"`
	Comments []Comment `json:"comments"`
}

// Comment is a pull request comment.
type Comment struct {
	User struct {
		Login string `json:"login"`
	} `json:"user"`
	Body      string    `json:"body"`
	CreatedAt time.Time `json:"created_at"`
}

// PicturesMarker marks the CI comment with the landmark pictures (scripts/post-pictures.sh).
const PicturesMarker = "<!-- sagas-pictures -->"

// Submissions lists the user's pull requests on full, newest first, with checks and comments.
func (c *Client) Submissions(ctx context.Context, full, login string) ([]Submission, error) {
	var found struct {
		Items []struct {
			Number int `json:"number"`
		} `json:"items"`
	}
	q := url.QueryEscape(fmt.Sprintf("repo:%s is:pr author:%s", full, login))
	if err := c.do(ctx, http.MethodGet, "/search/issues?sort=updated&per_page=30&q="+q, nil, &found); err != nil {
		return nil, err
	}
	var out []Submission
	for _, it := range found.Items {
		var s Submission
		if err := c.do(ctx, http.MethodGet, fmt.Sprintf("/repos/%s/pulls/%d", full, it.Number), nil, &s.Pull); err != nil {
			return nil, err
		}
		var comments []Comment
		if err := c.do(ctx, http.MethodGet, fmt.Sprintf("/repos/%s/issues/%d/comments?per_page=100", full, it.Number), nil, &comments); err != nil {
			return nil, err
		}
		for _, cm := range comments {
			if strings.Contains(cm.Body, PicturesMarker) {
				s.Pictures = cm.Body
			} else {
				s.Comments = append(s.Comments, cm)
			}
		}
		var checks struct {
			State string `json:"state"`
		}
		if err := c.do(ctx, http.MethodGet, fmt.Sprintf("/repos/%s/commits/%s/status", full, s.Head.SHA), nil, &checks); err == nil {
			s.Checks = checks.State
		}
		var runs struct {
			CheckRuns []struct {
				Status     string `json:"status"`
				Conclusion string `json:"conclusion"`
			} `json:"check_runs"`
		}
		if err := c.do(ctx, http.MethodGet, fmt.Sprintf("/repos/%s/commits/%s/check-runs?per_page=100", full, s.Head.SHA), nil, &runs); err == nil && len(runs.CheckRuns) > 0 {
			s.Checks = "success"
			for _, r := range runs.CheckRuns {
				switch {
				case r.Status != "completed":
					if s.Checks == "success" {
						s.Checks = "pending"
					}
				case r.Conclusion != "success" && r.Conclusion != "skipped" && r.Conclusion != "neutral":
					s.Checks = "failure"
				}
			}
		}
		out = append(out, s)
	}
	return out, nil
}
