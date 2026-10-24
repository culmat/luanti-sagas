//go:build windows

package proc

import (
	"os/exec"
	"syscall"
)

// HideWindow keeps console tools from flashing a window when Forge runs them.
func HideWindow(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: 0x08000000} // CREATE_NO_WINDOW
}
