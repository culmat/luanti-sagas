// Package proc starts the tools Forge drives: with Forge's environment and, on Windows, without a
// console window flashing up.
package proc

import (
	"context"
	"os/exec"
)

// Command is exec.CommandContext with env and no console window.
func Command(ctx context.Context, env []string, name string, args ...string) *exec.Cmd {
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Env = env
	HideWindow(cmd)
	return cmd
}
