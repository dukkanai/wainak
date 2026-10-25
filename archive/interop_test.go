package historyarchive

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"filippo.io/age"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"
)

type boundedOutput struct {
	buffer bytes.Buffer
	max    int
}

func (b *boundedOutput) Bytes() []byte { return b.buffer.Bytes() }
func (b *boundedOutput) Write(p []byte) (int, error) {
	if len(p) > b.max-b.buffer.Len() {
		return 0, ErrWrite
	}
	return b.buffer.Write(p)
}
// privateFD3 preserves inherited anonymous FD transport on supported host tests.
// No identity, recipient, plaintext or key is staged in a filesystem path.
func privateFD3(t *testing.T) string {
	t.Helper()
	switch runtime.GOOS {
	case "linux":
		return "/proc/self/fd/3"
	case "darwin":
		return "/dev/fd/3"
	default:
		t.Fatal("private FD test transport is unsupported on this host")
		return ""
	}
}

func cliPath(t *testing.T) string {
	t.Helper()
	if os.Getenv("WAINAK_ARCHIVE_INTEROP") != "1" {
		t.Skip("explicit CLI interop opt-in not set")
	}
	p := os.Getenv("WAINAK_AGE_CLI")
	want := os.Getenv("WAINAK_AGE_CLI_SHA256")
	if !filepath.IsAbs(p) || filepath.Clean(p) != p || len(want) != 64 {
		t.Fatal("CLI provenance missing")
	}
	info, e := os.Lstat(p)
	if e != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0022 != 0 || info.Size() > 64<<20 {
		t.Fatal("CLI file boundary")
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(st.Uid) != os.Geteuid() {
		t.Fatal("CLI ownership")
	}
	file, e := os.Open(p)
	if e != nil {
		t.Fatal("CLI bounded open")
	}
	defer file.Close()
	b, e := io.ReadAll(io.LimitReader(file, (64<<20)+1))
	if e != nil || len(b) > 64<<20 {
		t.Fatal("CLI bounded read")
	}
	sum := sha256.Sum256(b)
	if hex.EncodeToString(sum[:]) != want {
		t.Fatal("CLI changed")
	}
	return p
}
func cliRun(t *testing.T, path string, decrypt bool, input, identity []byte) ([]byte, []byte, error) {
	t.Helper()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	rd, wr, e := os.Pipe()
	if e != nil {
		t.Fatal("pipe setup")
	}
	defer rd.Close()
	defer wr.Close()
	if len(identity) > 4096 {
		t.Fatal("pipe input bound")
	}
	if n, e := wr.Write(identity); e != nil || n != len(identity) {
		t.Fatal("pipe setup")
	}
	wr.Close()
	args := []string{"-e", "-R", privateFD3(t), "-o", "-"}
	if decrypt {
		args = []string{"-d", "-i", privateFD3(t), "-o", "-"}
	}
	cmd := exec.CommandContext(ctx, path, args...)
	cmd.Env = []string{"PATH=/nonexistent", "LC_ALL=C"}
	cmd.ExtraFiles = []*os.File{rd}
	cmd.Stdin = bytes.NewReader(input)
	cmd.WaitDelay = time.Second
	out := &boundedOutput{max: MaxCiphertext + 1}
	errout := &boundedOutput{max: 4096}
	cmd.Stdout = out
	cmd.Stderr = errout
	err := cmd.Run()
	return out.Bytes(), errout.Bytes(), err
}
func TestCLIInteroperabilityAndLeaks(t *testing.T) {
	path := cliPath(t)
	c, s, k := fixture(t)
	random := make([]byte, 20)
	if _, e := rand.Read(random); e != nil {
		t.Fatal("canary setup")
	}
	canary := "event_" + hex.EncodeToString(random)
	s.Records[0].EventID = canary
	plain := encoded(t, s)
	key := []byte(k.String() + "\n")
	recipient := []byte(k.Recipient().String() + "\n")
	cipher := sealed(t, s, c, k)
	recovered, errout, e := cliRun(t, path, true, cipher, key)
	if e != nil || !bytes.Equal(recovered, plain) || len(errout) != 0 {
		t.Fatal("wrapper to CLI interop")
	}
	foreignCipher, errout, e := cliRun(t, path, false, plain, recipient)
	if e != nil || len(errout) != 0 {
		t.Fatal("CLI export")
	}
	if _, e = Open(context.Background(), foreignCipher, k, ownerA, c); e != nil {
		t.Fatal("CLI to wrapper interop")
	}
	if bytes.Equal(cipher, foreignCipher) || bytes.Contains(cipher, []byte(canary)) || bytes.Contains(foreignCipher, []byte(canary)) {
		t.Fatal("ciphertext property")
	}
	_, errout, e = cliRun(t, path, true, []byte("invalid ciphertext"), key)
	if e == nil || bytes.Contains(errout, []byte(canary)) || bytes.Contains(errout, bytes.TrimSpace(key)) {
		t.Fatal("CLI failure leak")
	}
	// Negative keys stay inside inherited FDs; raw diagnostics never leave RAM.
	wrong, e := age.GenerateX25519Identity()
	if e != nil {
		t.Fatal("key setup")
	}
	malformed := append([]byte(nil), key...)
	if malformed[len(malformed)-2] == 'Q' {
		malformed[len(malformed)-2] = 'P'
	} else {
		malformed[len(malformed)-2] = 'Q'
	}
	for _, candidate := range [][]byte{[]byte(wrong.String() + "\n"), malformed} {
		out, diagnostic, err := cliRun(t, path, true, cipher, candidate)
		if err == nil || len(out) != 0 || bytes.Contains(diagnostic, bytes.TrimSpace(candidate)) || bytes.Contains(diagnostic, bytes.TrimSpace(key)) || bytes.Contains(diagnostic, []byte(canary)) {
			t.Fatal("negative key boundary")
		}
	}
	// The tests and CLI create no plaintext/key staging files. Runtime-generated
	// canaries are not source literals. This directory is test-owned and empty.
	tmp := os.Getenv("WAINAK_ARCHIVE_SCAN_ROOT")
	if !filepath.IsAbs(tmp) || filepath.Clean(tmp) != tmp {
		t.Fatal("owned scan root missing")
	}
	info, e := os.Lstat(tmp)
	if e != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		t.Fatal("scan root boundary")
	}
	if st, ok := info.Sys().(*syscall.Stat_t); !ok || int(st.Uid) != os.Geteuid() {
		t.Fatal("scan root ownership")
	}
	var scanned int64
	e = filepath.WalkDir(tmp, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return ErrInvalid
		}
		if d.IsDir() {
			return nil
		}
		if d.Type()&os.ModeSymlink != 0 {
			return ErrInvalid
		}
		info, err := d.Info()
		if err != nil || !info.Mode().IsRegular() {
			return ErrInvalid
		}
		scanned += info.Size()
		if scanned > 512<<20 {
			return ErrInvalid
		}
		file, err := os.Open(p)
		if err != nil {
			return ErrInvalid
		}
		defer file.Close()
		tail := []byte{}
		buf := make([]byte, 64<<10)
		for {
			n, err := file.Read(buf)
			if n > 0 {
				window := append(tail, buf[:n]...)
				if bytes.Contains(window, []byte(canary)) || bytes.Contains(window, bytes.TrimSpace(key)) {
					return ErrInvalid
				}
				keep := len(key) + len(canary)
				if len(window) > keep {
					window = window[len(window)-keep:]
				}
				tail = append([]byte(nil), window...)
			}
			if err == io.EOF {
				break
			}
			if err != nil {
				return ErrInvalid
			}
		}
		return nil
	})
	if e != nil {
		t.Fatal("owned temporary filesystem leak check")
	}
	for _, arg := range []string{"-d", "-i", privateFD3(t), "-o", "-"} {
		if strings.Contains(arg, canary) || strings.Contains(arg, k.String()) {
			t.Fatal("argument leak")
		}
	}
}
func TestCLIChildCancellation(t *testing.T) {
	path := cliPath(t)
	_, _, k := fixture(t)
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	keyR, keyW, e := os.Pipe()
	if e != nil {
		t.Fatal("pipe setup")
	}
	defer keyR.Close()
	defer keyW.Close()
	keyW.Write([]byte(k.String() + "\n"))
	keyW.Close()
	inputR, inputW, e := os.Pipe()
	if e != nil {
		t.Fatal("pipe setup")
	}
	defer inputR.Close()
	defer inputW.Close()
	cmd := exec.CommandContext(ctx, path, "-d", "-i", privateFD3(t), "-o", "-")
	cmd.Env = []string{"PATH=/nonexistent", "LC_ALL=C"}
	cmd.ExtraFiles = []*os.File{keyR}
	cmd.Stdin = inputR
	cmd.WaitDelay = time.Second
	cmd.Stdout = &boundedOutput{max: MaxCiphertext}
	cmd.Stderr = &boundedOutput{max: 4096}
	if e = cmd.Start(); e != nil {
		t.Fatal("child start")
	}
	e = cmd.Wait()
	if e == nil || ctx.Err() == nil || cmd.ProcessState == nil {
		t.Fatal("cancel did not reap owned child")
	}
}

func FuzzArchiveOpen(f *testing.F) {
	c, e := NewCatalog("sample_v1", map[string][]string{"sample_card": {"sample_yes", "sample_defer"}})
	if e != nil {
		f.Fatal("setup")
	}
	// A generated identity remains inside this fuzz process; corpus is ciphertext only.
	key, e := age.GenerateX25519Identity()
	if e != nil {
		f.Fatal("key setup")
	}
	f.Add([]byte("not an age file"))
	f.Add([]byte("age-encryption.org/v1\n"))
	f.Fuzz(func(t *testing.T, data []byte) {
		if len(data) > MaxCiphertext+1 {
			return
		}
		b, e := Open(context.Background(), data, key, ownerA, c)
		if e != nil && b != nil {
			t.Fatal("partial plaintext escaped")
		}
	})
}

func TestBoundedOutputCopyCannotBypass(t *testing.T) {
	type readerOnly struct{ io.Reader }
	out := &boundedOutput{max: 8}
	_, err := io.Copy(out, readerOnly{strings.NewReader(strings.Repeat("x", 65536))})
	if err == nil || len(out.Bytes()) > 8 {
		t.Fatal("output cap bypass")
	}
}
