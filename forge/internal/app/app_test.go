package app

import "testing"

func TestDraftNames(t *testing.T) {
	cases := map[string]string{
		"vikings/old_watchtower": "vikings-old_watchtower",
		"ruins/mammoth_skeleton": "ruins-mammoth_skeleton",
	}
	for sel, want := range cases {
		if got := EditDraft(sel); got != want {
			t.Errorf("EditDraft(%q) = %q, want %q", sel, got, want)
		}
	}
	if got := slug("Old Watchtower!"); got != "old_watchtower" {
		t.Errorf("slug: %q", got)
	}
	if got := slug("???"); got != "draft" {
		t.Errorf("empty slug: %q", got)
	}
}
