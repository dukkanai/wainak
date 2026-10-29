package historyarchive

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"syscall"
	"testing"

	"filippo.io/age"
)

const ownerA = "owner_aaaaaaaaaaaaaaaa"
const ownerB = "owner_bbbbbbbbbbbbbbbb"

func fixture(t *testing.T) (*Catalog, Snapshot, *age.X25519Identity) {
	t.Helper()
	c, e := NewCatalog("sample_v1", map[string][]string{"sample_card": {"sample_yes", "sample_defer"}})
	if e != nil {
		t.Fatal("catalog setup")
	}
	key, e := age.GenerateX25519Identity()
	if e != nil {
		t.Fatal("key setup")
	}
	s := Snapshot{SchemaVersion: SchemaVersion, OwnerRef: ownerA, CatalogVersion: "sample_v1", Records: []Record{{EventID: "event_one", OccurredAt: "2026-10-24T00:00:00Z", CardID: "sample_card", ResponseID: "sample_defer"}}}
	return c, s, key
}
func encryptRaw(t *testing.T, p []byte, k *age.X25519Identity) []byte {
	t.Helper()
	var b bytes.Buffer
	w, e := age.Encrypt(&b, k.Recipient())
	if e != nil {
		t.Fatal("raw setup")
	}
	if _, e = w.Write(p); e != nil {
		t.Fatal("raw write")
	}
	if w.Close() != nil {
		t.Fatal("raw close")
	}
	return b.Bytes()
}
func encoded(t *testing.T, s Snapshot) []byte {
	t.Helper()
	b, e := json.Marshal(s)
	if e != nil {
		t.Fatal("encode setup")
	}
	return b
}
func sealed(t *testing.T, s Snapshot, c *Catalog, k *age.X25519Identity) []byte {
	t.Helper()
	b, e := Seal(context.Background(), s, c, k.Recipient())
	if e != nil {
		t.Fatal("seal setup")
	}
	return b
}
func opened(t *testing.T, b []byte, k *age.X25519Identity, c *Catalog) *Batch {
	t.Helper()
	v, e := Open(context.Background(), b, k, ownerA, c)
	if e != nil {
		t.Fatal("open setup")
	}
	return v
}
func unchangedReject(t *testing.T, b []byte, k *age.X25519Identity, c *Catalog) {
	t.Helper()
	v, e := Open(context.Background(), b, k, ownerA, c)
	if e == nil || v != nil {
		t.Fatal("hostile input accepted")
	}
}

func TestRoundTripAndRandomizedEncryption(t *testing.T) {
	c, s, k := fixture(t)
	one := sealed(t, s, c, k)
	two := sealed(t, s, c, k)
	if bytes.Equal(one, two) {
		t.Fatal("encryption not randomized")
	}
	batch := opened(t, one, k, c)
	h, _ := NewMemoryHistory(ownerA, c)
	if h.Import(context.Background(), batch) != nil {
		t.Fatal("import rejected")
	}
	view := h.View()
	if len(view) != 1 || view[0].Record != s.Records[0] || !view[0].Imported || view[0].AuthenticatedAuthor {
		t.Fatal("history projection mismatch")
	}
	view[0].Record.ResponseID = "changed"
	if h.View()[0].Record != s.Records[0] {
		t.Fatal("mutable view leaked")
	}
}
func TestCatalogAndInputValidity(t *testing.T) {
	choices := map[string][]string{"sample_card": {"sample_yes", "sample_defer"}}
	c, e := NewCatalog("sample_v1", choices)
	if e != nil {
		t.Fatal("setup")
	}
	choices["sample_card"][0] = "changed"
	delete(choices, "sample_card")
	_, s, k := fixture(t)
	if _, e = Seal(context.Background(), s, c, k.Recipient()); e != nil {
		t.Fatal("catalog not copied")
	}
	for _, invalid := range []map[string][]string{nil, {}, {"sample_card": {"same", "same"}}, {"bad id": {"yes", "no"}}, {"card": {"one"}}} {
		if _, e := NewCatalog("sample_v1", invalid); e == nil {
			t.Fatal("invalid catalog")
		}
	}
	if _, e = NewMemoryHistory(ownerA, &Catalog{}); e == nil {
		t.Fatal("zero catalog accepted")
	}
	if _, e = NewMemoryHistory("wrong", c); e == nil {
		t.Fatal("invalid owner")
	}
	if _, e = Seal(nil, s, c, k.Recipient()); e != ErrCancelled {
		t.Fatal("nil context")
	}
	if _, e = Seal(context.Background(), s, c, nil); e == nil {
		t.Fatal("nil recipient")
	}
	if _, e = Open(context.Background(), []byte("bad"), nil, ownerA, c); e == nil {
		t.Fatal("nil identity")
	}
	if _, e = age.ParseX25519Identity("invalid"); e == nil {
		t.Fatal("invalid encoding")
	}
}
func TestWrongKeyOwnerAndProfile(t *testing.T) {
	c, s, k := fixture(t)
	cipher := sealed(t, s, c, k)
	other, e := age.GenerateX25519Identity()
	if e != nil {
		t.Fatal("setup")
	}
	unchangedReject(t, cipher, other, c)
	if b, e := Open(context.Background(), cipher, k, ownerB, c); e == nil || b != nil {
		t.Fatal("wrong owner")
	}
	var multi bytes.Buffer
	w, e := age.Encrypt(&multi, k.Recipient(), other.Recipient())
	if e != nil {
		t.Fatal("setup")
	}
	w.Write(encoded(t, s))
	w.Close()
	unchangedReject(t, multi.Bytes(), k, c)
	unchangedReject(t, []byte("-----BEGIN AGE ENCRYPTED FILE-----\n"), k, c)
}
func TestCorruptionAndTruncationBoundaries(t *testing.T) {
	c, s, k := fixture(t)
	for i := 0; i < 1000; i++ {
		r := s.Records[0]
		r.EventID = fmt.Sprintf("event_%04d", i)
		s.Records = append(s.Records, r)
	}
	cipher := sealed(t, s, c, k)
	for _, cut := range []int{0, 1, 19, 100, 65535, 65536, 65537, 131071, 131072, len(cipher) - 17, len(cipher) - 1} {
		if cut < len(cipher) {
			unchangedReject(t, cipher[:cut], k, c)
		}
	}
	for _, pos := range []int{0, 30, 100, 65535, len(cipher) - 1} {
		if pos < len(cipher) {
			b := append([]byte(nil), cipher...)
			b[pos] ^= 1
			unchangedReject(t, b, k, c)
		}
	}
	unchangedReject(t, append(append([]byte(nil), cipher...), 0), k, c)
	unchangedReject(t, append(append([]byte(nil), cipher...), cipher...), k, c)
}
func TestStrictJSON(t *testing.T) {
	c, s, k := fixture(t)
	good := string(encoded(t, s))
	cases := []string{
		good + "{}", strings.Replace(good, `"owner_ref":`, `"owner_ref":"`+ownerA+`","owner_ref":`, 1),
		strings.Replace(good, `"owner_ref":`, `"owner\u005fref":"`+ownerA+`","owner_ref":`, 1),
		strings.Replace(good, `"owner_ref"`, `"Owner_ref"`, 1),
		strings.Replace(good, `"event_id":`, `"event_id":"different","event_id":`, 1),
		strings.Replace(good, `"records":[`, `"outbox":[],"records":[`, 1),
		strings.Replace(good, `"records":[`, `"session_token":"forbidden","records":[`, 1),
		strings.Replace(good, `"records":[`, `"trust_verified":true,"records":[`, 1),
		strings.Replace(good, `"records":[`, `"records":null,"extra":[`, 1),
		strings.Replace(good, `"event_one"`, `"\ud800"`, 1),
		strings.Replace(good, `"sample_defer"`, `null`, 1),
		strings.Repeat("[", 9) + `"x"` + strings.Repeat("]", 9),
		strings.Replace(good, "wainak-history-v1", "wainek-history-v99", 1),
		strings.Replace(good, "sample_v1", "unknown_v1", 1),
		strings.Replace(good, "sample_defer", "not_allowed", 1),
		strings.Replace(good, "2026-10-24T00:00:00Z", "2026-10-24T00:00:00+00:00", 1),
		strings.Replace(good, "2026-10-24T00:00:00Z", "2026-10-24T00:00:00.123Z", 1),
		strings.Replace(good, "2026-10-24T00:00:00Z", "1900-10-24T00:00:00Z", 1),
	}
	for i, v := range cases {
		t.Run(fmt.Sprintf("invalid_%02d", i), func(t *testing.T) { unchangedReject(t, encryptRaw(t, []byte(v), k), k, c) })
	}
	bad := append([]byte(nil), []byte(good)...)
	bad[3] = 0xff
	unchangedReject(t, encryptRaw(t, bad, k), k, c)
	s.Records = append(s.Records, s.Records[0])
	unchangedReject(t, encryptRaw(t, encoded(t, s), k), k, c)
}
func TestSizeAndNoPartialPlaintext(t *testing.T) {
	c, s, k := fixture(t)
	unchangedReject(t, make([]byte, MaxCiphertext+1), k, c)
	// Valid JSON plus bounded whitespace is valid plaintext. Decryption must read
	// past the valid prefix and authenticate the final chunk before returning it.
	valid := encoded(t, s)
	p := append(append([]byte(nil), valid...), bytes.Repeat([]byte(" "), MaxPlaintext-len(valid))...)
	exact := encryptRaw(t, p, k)
	if _, e := Open(context.Background(), exact, k, ownerA, c); e != nil {
		t.Fatal("exact plaintext limit")
	}
	oversized := encryptRaw(t, append(p, ' '), k)
	unchangedReject(t, oversized, k, c)
	exact[len(exact)-1] ^= 1
	unchangedReject(t, exact, k, c)
	for i := 1; i < MaxRecords; i++ {
		r := s.Records[0]
		r.EventID = fmt.Sprintf("event_%04d", i)
		s.Records = append(s.Records, r)
	}
	if _, e := Seal(context.Background(), s, c, k.Recipient()); e != nil {
		t.Fatal("record limit boundary")
	}
	s.Records = append(s.Records, s.Records[0])
	if _, e := Seal(context.Background(), s, c, k.Recipient()); e == nil {
		t.Fatal("record limit exceeded")
	}
}
func TestAtomicReplayDivergentCatalogAndConcurrentImport(t *testing.T) {
	c, s, k := fixture(t)
	h, _ := NewMemoryHistory(ownerA, c)
	batch := opened(t, sealed(t, s, c, k), k, c)
	var wg sync.WaitGroup
	success := 0
	var mu sync.Mutex
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if h.Import(context.Background(), batch) == nil {
				mu.Lock()
				success++
				mu.Unlock()
			}
		}()
	}
	wg.Wait()
	if success != 1 || len(h.View()) != 1 {
		t.Fatal("import not atomic")
	}
	if h.Import(context.Background(), batch) != ErrConflict {
		t.Fatal("replay accepted")
	}
	s.Records = append([]Record{{EventID: "event_new", OccurredAt: "2026-10-24T00:00:00Z", CardID: "sample_card", ResponseID: "sample_yes"}}, s.Records...)
	mixed := opened(t, sealed(t, s, c, k), k, c)
	if h.Import(context.Background(), mixed) != ErrConflict || len(h.View()) != 1 {
		t.Fatal("partial conflict import")
	}
	altered, _ := NewCatalog("sample_v1", map[string][]string{"sample_card": {"other_one", "other_two"}})
	other, _ := NewMemoryHistory(ownerA, altered)
	if other.Import(context.Background(), batch) == nil || len(other.View()) != 0 {
		t.Fatal("divergent catalog")
	}
	foreign, _ := NewMemoryHistory(ownerB, c)
	if foreign.Import(context.Background(), batch) == nil {
		t.Fatal("foreign store")
	}
	if h.Import(context.Background(), &Batch{}) == nil || h.Import(context.Background(), nil) == nil {
		t.Fatal("forged batch")
	}
}
func TestPublicRecipientDoesNotProveAuthorship(t *testing.T) {
	c, s, k := fixture(t)
	// A second party can encrypt arbitrary allowlisted history using only the
	// public recipient. It must never gain authenticated-author status.
	public, e := age.ParseX25519Recipient(k.Recipient().String())
	if e != nil {
		t.Fatal("setup")
	}
	s.Records[0].EventID = "synthetic_by_other"
	cipher, e := Seal(context.Background(), s, c, public)
	if e != nil {
		t.Fatal("seal")
	}
	h, _ := NewMemoryHistory(ownerA, c)
	if h.Import(context.Background(), opened(t, cipher, k, c)) != nil {
		t.Fatal("import")
	}
	if h.View()[0].AuthenticatedAuthor || !h.View()[0].Imported {
		t.Fatal("false trust")
	}
}

type faultWriter struct {
	calls, failAt int
	mode          string
	cancel        context.CancelFunc
	buffer        bytes.Buffer
}

func (f *faultWriter) Write(p []byte) (int, error) {
	f.calls++
	if f.calls == f.failAt {
		switch f.mode {
		case "short":
			return len(p) / 2, nil
		case "partial_error":
			return len(p) / 2, io.ErrClosedPipe
		case "full":
			return 0, syscall.ENOSPC
		case "cancel":
			f.cancel()
		}
	}
	return f.buffer.Write(p)
}
func TestWriteCloseAndCancellationFaults(t *testing.T) {
	c, s, k := fixture(t)
	probe := &faultWriter{}
	if SealTo(context.Background(), s, c, k.Recipient(), probe) != nil {
		t.Fatal("probe")
	}
	if probe.calls < 2 {
		t.Fatal("missing finalization write")
	}
	for _, mode := range []string{"short", "partial_error", "full", "cancel"} {
		for at := 1; at <= probe.calls; at++ {
			t.Run(fmt.Sprintf("%s_%d", mode, at), func(t *testing.T) {
				ctx, cancel := context.WithCancel(context.Background())
				defer cancel()
				w := &faultWriter{failAt: at, mode: mode, cancel: cancel}
				if SealTo(ctx, s, c, k.Recipient(), w) == nil {
					t.Fatal("fault reported success")
				}
			})
		}
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if b, e := Seal(ctx, s, c, k.Recipient()); e != ErrCancelled || b != nil {
		t.Fatal("cancel seal")
	}
	cipher := sealed(t, s, c, k)
	if b, e := Open(ctx, cipher, k, ownerA, c); e != ErrCancelled || b != nil {
		t.Fatal("cancel open")
	}
	h, _ := NewMemoryHistory(ownerA, c)
	if h.Import(ctx, opened(t, cipher, k, c)) != ErrCancelled || len(h.View()) != 0 {
		t.Fatal("cancel import")
	}
}
func TestFixedDiagnosticsAndRuntimeCanary(t *testing.T) {
	c, s, k := fixture(t)
	random := make([]byte, 20)
	if _, e := rand.Read(random); e != nil {
		t.Fatal("random setup")
	}
	canary := "event_" + hex.EncodeToString(random)
	s.Records[0].EventID = canary
	cipher := sealed(t, s, c, k)
	if bytes.Contains(cipher, []byte(canary)) {
		t.Fatal("plaintext in ciphertext")
	}
	for _, v := range []any{s, s.Records[0], opened(t, cipher, k, c), ErrInvalid, ErrCrypto, ErrCancelled, ErrWrite, ErrConflict} {
		if strings.Contains(fmt.Sprint(v), canary) {
			t.Fatal("canary in diagnostics")
		}
	}
	for _, e := range []error{ErrInvalid, ErrCrypto, ErrCancelled, ErrWrite, ErrConflict} {
		if errors.Is(e, nil) {
			t.Fatal("missing fixed error")
		}
	}
}

func TestStoreCatalogHolderSnapshot(t *testing.T) {
	c, s, k := fixture(t)
	h, _ := NewMemoryHistory(ownerA, c)
	batch := opened(t, sealed(t, s, c, k), k, c)
	divergent, _ := NewCatalog("sample_v1", map[string][]string{"sample_card": {"other_one", "other_two"}})
	*c = *divergent
	if h.Import(context.Background(), batch) != nil {
		t.Fatal("store retained mutable catalog holder")
	}
}

// Synthetic plaintext corpus only: no recovery secrets or user content.
func FuzzStrictHistoryJSON(f *testing.F) {
	f.Add([]byte(`{"schema_version":"wainak-history-v1","owner_ref":"owner_aaaaaaaaaaaaaaaa","catalog_version":"sample_v1","records":[]}`))
	f.Add([]byte(`{"records":[],"records":[]}`))
	f.Add([]byte(`{"records":"\ud800"}`))
	f.Fuzz(func(t *testing.T, data []byte) {
		if len(data) > MaxPlaintext+1 {
			return
		}
		value, err := parse(data)
		if err != nil {
			return
		}
		encoded, err := json.Marshal(value)
		if err != nil {
			t.Fatal("accepted JSON cannot encode")
		}
		if _, err = parse(encoded); err != nil {
			t.Fatal("accepted schema not stable")
		}
	})
}

// Brand changes must not make previously exported v1 history unreadable.
func TestLegacyWainakWireVersionSurvivesBrandRename(t *testing.T) {
	if SchemaVersion != "wainak-history-v1" {
		t.Fatal("legacy wire version changed")
	}
	c, err := NewCatalog("sample_v1", map[string][]string{"sample_card": {"sample_defer", "sample_yes"}})
	if err != nil || c == nil {
		t.Fatal("catalog")
	}
	var legacy Snapshot
	raw := []byte(`{"schema_version":"wainak-history-v1","owner_ref":"owner_aaaaaaaaaaaaaaaa","catalog_version":"sample_v1","records":[]}`)
	if err := json.Unmarshal(raw, &legacy); err != nil {
		t.Fatal(err)
	}
	if err := validate(legacy, c, "owner_aaaaaaaaaaaaaaaa"); err != nil {
		t.Fatal("legacy schema rejected")
	}
	legacy.SchemaVersion = "wainek-history-v1"
	if validate(legacy, c, "owner_aaaaaaaaaaaaaaaa") == nil {
		t.Fatal("unversioned format change accepted")
	}
}
