package historyarchive_test

// Independent external-package QA. Fixtures are synthetic; errors never print
// operands, generated keys, raw records, ciphertext or plaintext.
import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"sync"
	"testing"

	"filippo.io/age"
	a "wainek.local/historyarchive"
)

const qaOwner = "owner_qqqqqqqqqqqqqqqq"
const qaOther = "owner_zzzzzzzzzzzzzzzz"

func qaFixture(t *testing.T) (*a.Catalog, a.Snapshot, *age.X25519Identity) {
	t.Helper()
	c, e := a.NewCatalog("qa_catalog", map[string][]string{"qa_card": {"qa_wait", "qa_answer"}, "other_card": {"other_wait", "other_answer"}})
	if e != nil {
		t.Fatal("catalog fixture")
	}
	k, e := age.GenerateX25519Identity()
	if e != nil {
		t.Fatal("key fixture")
	}
	s := a.Snapshot{SchemaVersion: a.SchemaVersion, OwnerRef: qaOwner, CatalogVersion: "qa_catalog", Records: []a.Record{{EventID: "qa_event", OccurredAt: "2026-10-24T12:00:00Z", CardID: "qa_card", ResponseID: "qa_wait"}}}
	return c, s, k
}
func qaRaw(t *testing.T, p []byte, k *age.X25519Identity) []byte {
	t.Helper()
	var out bytes.Buffer
	w, e := age.Encrypt(&out, k.Recipient())
	if e != nil {
		t.Fatal("raw fixture")
	}
	n, e := w.Write(p)
	if e != nil || n != len(p) || w.Close() != nil {
		t.Fatal("raw fixture completion")
	}
	return out.Bytes()
}
func qaJSON(t *testing.T, s a.Snapshot) []byte {
	t.Helper()
	p, e := json.Marshal(s)
	if e != nil {
		t.Fatal("JSON fixture")
	}
	return p
}
func qaSeal(t *testing.T, s a.Snapshot, c *a.Catalog, k *age.X25519Identity) []byte {
	t.Helper()
	p, e := a.Seal(context.Background(), s, c, k.Recipient())
	if e != nil {
		t.Fatal("seal fixture")
	}
	return p
}
func qaOpen(t *testing.T, p []byte, k *age.X25519Identity, c *a.Catalog) *a.Batch {
	t.Helper()
	b, e := a.Open(context.Background(), p, k, qaOwner, c)
	if e != nil || b == nil {
		t.Fatal("open fixture")
	}
	return b
}
func qaReject(t *testing.T, p []byte, k *age.X25519Identity, c *a.Catalog) {
	t.Helper()
	b, e := a.Open(context.Background(), p, k, qaOwner, c)
	if e == nil || b != nil {
		t.Fatal("invalid archive escaped quarantine")
	}
}
func qaStore(t *testing.T, c *a.Catalog) *a.MemoryHistory {
	t.Helper()
	h, e := a.NewMemoryHistory(qaOwner, c)
	if e != nil {
		t.Fatal("store fixture")
	}
	return h
}
func TestQAEmptySnapshotAndDerivedTrust(t *testing.T) {
	c, s, k := qaFixture(t)
	s.Records = []a.Record{}
	h := qaStore(t, c)
	if h.Import(context.Background(), qaOpen(t, qaSeal(t, s, c, k), k, c)) != nil || len(h.View()) != 0 {
		t.Fatal("empty snapshot contract")
	}
	s.Records = []a.Record{{EventID: "qa_new", OccurredAt: "1970-01-01T00:00:00Z", CardID: "qa_card", ResponseID: "qa_wait"}}
	if h.Import(context.Background(), qaOpen(t, qaSeal(t, s, c, k), k, c)) != nil {
		t.Fatal("valid import")
	}
	v := h.View()
	if len(v) != 1 || !v[0].Imported || v[0].AuthenticatedAuthor {
		t.Fatal("restored trust unexpectedly")
	}
	v[0].Record.EventID = "mutated"
	if h.View()[0].Record.EventID != "qa_new" {
		t.Fatal("view aliases store")
	}
}
func TestQAZeroValuesFailClosed(t *testing.T) {
	c, s, k := qaFixture(t)
	good := qaSeal(t, s, c, k)
	defer func() {
		if recover() != nil {
			t.Fatal("zero value panicked")
		}
	}()
	if b, e := a.Seal(context.Background(), s, c, &age.X25519Recipient{}); e == nil || b != nil {
		t.Fatal("zero recipient accepted")
	}
	if b, e := a.Open(context.Background(), good, &age.X25519Identity{}, qaOwner, c); e == nil || b != nil {
		t.Fatal("zero identity accepted")
	}
	if b, e := a.Open(context.Background(), good, k, qaOwner, &a.Catalog{}); e == nil || b != nil {
		t.Fatal("zero catalog accepted")
	}
	h := qaStore(t, c)
	if h.Import(context.Background(), &a.Batch{}) == nil || h.Import(context.Background(), nil) == nil {
		t.Fatal("unvalidated batch accepted")
	}
	z := &a.MemoryHistory{}
	if z.Import(context.Background(), qaOpen(t, good, k, c)) == nil {
		t.Fatal("zero store accepted")
	}
}
func TestQACatalogDeepCopyAndValidationScope(t *testing.T) {
	_, s, k := qaFixture(t)
	input := map[string][]string{"qa_card": {"qa_wait", "qa_answer"}}
	c, e := a.NewCatalog("qa_catalog", input)
	if e != nil {
		t.Fatal("catalog fixture")
	}
	input["qa_card"][0] = "injected"
	delete(input, "qa_card")
	input["new_card"] = []string{"new_one", "new_two"}
	b := qaOpen(t, qaSeal(t, s, c, k), k, c)
	divergent, e := a.NewCatalog("qa_catalog", map[string][]string{"qa_card": {"injected", "different"}})
	if e != nil {
		t.Fatal("divergent fixture")
	}
	h := qaStore(t, divergent)
	if h.Import(context.Background(), b) == nil || len(h.View()) != 0 {
		t.Fatal("same version bypassed store catalog")
	}
	s.Records[0].ResponseID = "injected"
	if p, e := a.Seal(context.Background(), s, c, k.Recipient()); e == nil || p != nil {
		t.Fatal("catalog input alias")
	}
}
func TestQASchemaRejectsForbiddenStateAtEveryLevel(t *testing.T) {
	c, s, k := qaFixture(t)
	good := string(qaJSON(t, s))
	for _, field := range []string{"session_token", "device_key", "ratchet", "trust", "outbox", "entitlement", "consents", "message", "imported", "authenticated_author", "path", "url", "compressed"} {
		t.Run(field, func(t *testing.T) {
			for _, needle := range []string{`"schema_version":`, `"event_id":`} {
				bad := strings.Replace(good, needle, `"`+field+`":"blocked",`+needle, 1)
				qaReject(t, qaRaw(t, []byte(bad), k), k, c)
			}
		})
	}
}
func TestQADecodedDuplicatesCaseAndTypes(t *testing.T) {
	c, s, k := qaFixture(t)
	good := string(qaJSON(t, s))
	cases := []string{
		strings.Replace(good, `"schema_version":`, `"schema\u005fversion":"wainak-history-v1","schema_version":`, 1),
		strings.Replace(good, `"event_id":`, `"event\u005fid":"qa_event","event_id":`, 1),
		strings.Replace(good, `"response_id":`, `"response_id":"qa_answer","response\u005fid":`, 1),
		strings.Replace(good, `"card_id":`, `"Card_id":`, 1),
		strings.Replace(good, `"records":[`, `"records":null,"forbidden":[`, 1),
		strings.Replace(good, `"qa_wait"`, `null`, 1), strings.Replace(good, `"qa_wait"`, `true`, 1),
		strings.Replace(good, `"qa_wait"`, `1`, 1), strings.Replace(good, `"qa_wait"`, `[]`, 1),
		strings.Replace(good, `"qa_wait"`, `{}`, 1), strings.Replace(good, `"qa_wait"`, `"\ud800"`, 1),
		strings.Replace(good, `"qa_wait"`, `"\udc00"`, 1), strings.Replace(good, `"qa_wait"`, `"\ud800\ud800"`, 1),
		good + ` false`, good + ` {}`, "\xef\xbb\xbf" + good, strings.Repeat("[", 9) + `"v"` + strings.Repeat("]", 9),
	}
	for i, bad := range cases {
		t.Run(fmt.Sprintf("case_%02d", i), func(t *testing.T) { qaReject(t, qaRaw(t, []byte(bad), k), k, c) })
	}
	invalidUTF8 := []byte(good)
	invalidUTF8[len(invalidUTF8)-4] = 0xff
	qaReject(t, qaRaw(t, invalidUTF8, k), k, c)
}
func TestQARecordValidationCannotCrossCardOrOwner(t *testing.T) {
	c, s, k := qaFixture(t)
	for _, change := range []func(*a.Snapshot){
		func(s *a.Snapshot) { s.Records[0].ResponseID = "other_wait" },
		func(s *a.Snapshot) { s.Records[0].OccurredAt = "2026-10-24T12:00:00+00:00" },
		func(s *a.Snapshot) { s.Records[0].OccurredAt = "2026-10-24T12:00:00.0Z" },
		func(s *a.Snapshot) { s.Records[0].OccurredAt = "2026-10-24T12:00:60Z" },
		func(s *a.Snapshot) { s.Records[0].OccurredAt = "2101-01-01T00:00:00Z" },
		func(s *a.Snapshot) { s.OwnerRef = qaOther },
		func(s *a.Snapshot) { s.Records[0].EventID = "qa_event\n" },
		func(s *a.Snapshot) { s.Records = append(s.Records, s.Records[0]) },
	} {
		v := s
		v.Records = append([]a.Record{}, s.Records...)
		change(&v)
		qaReject(t, qaRaw(t, qaJSON(t, v), k), k, c)
	}
}
func TestQAFinalAuthenticationRequiredAtChunkBoundaries(t *testing.T) {
	c, s, k := qaFixture(t)
	base := qaJSON(t, s)
	for _, size := range []int{65535, 65536, 65537, 131071, 131072, 131073, a.MaxPlaintext} {
		t.Run(fmt.Sprintf("bytes_%d", size), func(t *testing.T) {
			p := append(append([]byte{}, base...), bytes.Repeat([]byte(" "), size-len(base))...)
			cipher := qaRaw(t, p, k)
			qaOpen(t, cipher, k, c)
			for _, n := range []int{1, 16, 17} {
				qaReject(t, cipher[:len(cipher)-n], k, c)
			}
			bad := append([]byte{}, cipher...)
			bad[len(bad)-1] ^= 0x80
			qaReject(t, bad, k, c)
			qaReject(t, append(append([]byte{}, cipher...), 0), k, c)
		})
	}
}
func TestQALimitsRejectWithoutPartialBatch(t *testing.T) {
	c, s, k := qaFixture(t)
	base := qaJSON(t, s)
	p := append(append([]byte{}, base...), bytes.Repeat([]byte(" "), a.MaxPlaintext+1-len(base))...)
	qaReject(t, qaRaw(t, p, k), k, c)
	qaReject(t, make([]byte, a.MaxCiphertext+1), k, c)
	s.Records = make([]a.Record, a.MaxRecords+1)
	for i := range s.Records {
		s.Records[i] = a.Record{EventID: fmt.Sprintf("qa_event_%04d", i), OccurredAt: "2026-10-24T12:00:00Z", CardID: "qa_card", ResponseID: "qa_wait"}
	}
	qaReject(t, qaRaw(t, qaJSON(t, s), k), k, c)
	if p, e := a.Seal(context.Background(), s, c, k.Recipient()); e == nil || p != nil {
		t.Fatal("export record cap bypass")
	}
}
func TestQARecipientProfileAndConcatenation(t *testing.T) {
	c, s, k := qaFixture(t)
	other, e := age.GenerateX25519Identity()
	if e != nil {
		t.Fatal("key fixture")
	}
	good := qaSeal(t, s, c, k)
	qaReject(t, good, other, c)
	qaReject(t, append(append([]byte{}, good...), good...), k, c)
	var buf bytes.Buffer
	w, e := age.Encrypt(&buf, k.Recipient(), other.Recipient())
	if e != nil {
		t.Fatal("multi fixture")
	}
	if _, e = w.Write(qaJSON(t, s)); e != nil || w.Close() != nil {
		t.Fatal("multi fixture completion")
	}
	qaReject(t, buf.Bytes(), k, c)
	randomPass := make([]byte, 24)
	if _, e := rand.Read(randomPass); e != nil {
		t.Fatal("passphrase fixture")
	}
	password, e := age.NewScryptRecipient(hex.EncodeToString(randomPass))
	if e != nil {
		t.Fatal("scrypt fixture")
	}
	password.SetWorkFactor(1)
	buf.Reset()
	w, e = age.Encrypt(&buf, password)
	if e != nil {
		t.Fatal("scrypt fixture")
	}
	if _, e = w.Write(qaJSON(t, s)); e != nil || w.Close() != nil {
		t.Fatal("scrypt completion")
	}
	qaReject(t, buf.Bytes(), k, c)
}
func TestQAConflictsAbortEntireImportAndReplay(t *testing.T) {
	c, s, k := qaFixture(t)
	h := qaStore(t, c)
	b := qaOpen(t, qaSeal(t, s, c, k), k, c)
	if h.Import(context.Background(), b) != nil {
		t.Fatal("initial import")
	}
	if h.Import(context.Background(), b) != a.ErrConflict {
		t.Fatal("identical replay contract")
	}
	s.Records[0].ResponseID = "qa_answer"
	s.Records = append([]a.Record{{EventID: "qa_new", OccurredAt: "2026-10-24T12:00:00Z", CardID: "qa_card", ResponseID: "qa_wait"}}, s.Records...)
	if h.Import(context.Background(), qaOpen(t, qaSeal(t, s, c, k), k, c)) != a.ErrConflict {
		t.Fatal("changed event not rejected")
	}
	if len(h.View()) != 1 || h.View()[0].Record.ResponseID != "qa_wait" {
		t.Fatal("partial mutation on conflict")
	}
	foreign, _ := a.NewMemoryHistory(qaOther, c)
	if foreign.Import(context.Background(), b) == nil || len(foreign.View()) != 0 {
		t.Fatal("cross owner import")
	}
}
func TestQAConcurrentCapacityAndReplayAtomicity(t *testing.T) {
	c, s, k := qaFixture(t)
	h := qaStore(t, c)
	s.Records = nil
	for i := 0; i < a.MaxRecords-1; i++ {
		s.Records = append(s.Records, a.Record{EventID: fmt.Sprintf("seed_%04d", i), OccurredAt: "2026-10-24T12:00:00Z", CardID: "qa_card", ResponseID: "qa_wait"})
	}
	if h.Import(context.Background(), qaOpen(t, qaSeal(t, s, c, k), k, c)) != nil {
		t.Fatal("capacity fixture")
	}
	batches := make([]*a.Batch, 8)
	for i := range batches {
		s.Records = []a.Record{{EventID: fmt.Sprintf("racer_%d", i), OccurredAt: "2026-10-24T12:00:00Z", CardID: "qa_card", ResponseID: "qa_wait"}}
		batches[i] = qaOpen(t, qaSeal(t, s, c, k), k, c)
	}
	start := make(chan struct{})
	results := make(chan error, len(batches))
	var wg sync.WaitGroup
	for _, b := range batches {
		wg.Add(1)
		go func(b *a.Batch) { defer wg.Done(); <-start; results <- h.Import(context.Background(), b) }(b)
	}
	close(start)
	wg.Wait()
	close(results)
	success := 0
	for e := range results {
		if e == nil {
			success++
		}
	}
	if success != 1 || len(h.View()) != a.MaxRecords {
		t.Fatal("concurrent limit bypass")
	}
}

type qaWriter struct {
	calls, at, kind int
	cancel          context.CancelFunc
	buf             bytes.Buffer
}

func (w *qaWriter) Write(p []byte) (int, error) {
	w.calls++
	if w.calls == w.at {
		switch w.kind {
		case 1:
			return len(p) - 1, nil
		case 2:
			return len(p) / 2, io.ErrClosedPipe
		case 3:
			return -1, nil
		case 4:
			return len(p) + 1, nil
		case 5:
			w.cancel()
		case 6:
			return 0, io.ErrShortWrite
		}
	}
	return w.buf.Write(p)
}
func TestQAEveryWriterBoundaryAndMalformedCount(t *testing.T) {
	c, s, k := qaFixture(t)
	probe := &qaWriter{}
	if a.SealTo(context.Background(), s, c, k.Recipient(), probe) != nil {
		t.Fatal("writer probe")
	}
	for kind := 1; kind <= 6; kind++ {
		for at := 1; at <= probe.calls; at++ {
			t.Run(fmt.Sprintf("kind_%d_write_%d", kind, at), func(t *testing.T) {
				ctx, cancel := context.WithCancel(context.Background())
				defer cancel()
				w := &qaWriter{at: at, kind: kind, cancel: cancel}
				if a.SealTo(ctx, s, c, k.Recipient(), w) == nil {
					t.Fatal("incomplete writer returned success")
				}
			})
		}
	}
}
func TestQACancelledOperationAndNoPlaintextInCipher(t *testing.T) {
	c, s, k := qaFixture(t)
	cipher := qaSeal(t, s, c, k)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if p, e := a.Seal(ctx, s, c, k.Recipient()); e != a.ErrCancelled || p != nil {
		t.Fatal("cancel export")
	}
	if b, e := a.Open(ctx, cipher, k, qaOwner, c); e != a.ErrCancelled || b != nil {
		t.Fatal("cancel open")
	}
	h := qaStore(t, c)
	if h.Import(ctx, qaOpen(t, cipher, k, c)) != a.ErrCancelled || len(h.View()) != 0 {
		t.Fatal("cancel import")
	}
	if bytes.Contains(cipher, qaJSON(t, s)) {
		t.Fatal("plaintext archive escaped encryption")
	}
}
func TestQAStoreCatalogHolderCannotBeRetargeted(t *testing.T) {
	c, s, k := qaFixture(t)
	h := qaStore(t, c)
	divergent, e := a.NewCatalog("qa_catalog", map[string][]string{"qa_card": {"forged_choice", "forged_other"}})
	if e != nil {
		t.Fatal("catalog fixture")
	}
	s.Records[0].ResponseID = "forged_choice"
	b := qaOpen(t, qaSeal(t, s, divergent, k), k, divergent)
	// External callers cannot edit private fields, but can replace an exported
	// value through a pointer. The store must retain its construction-time scope.
	*c = *divergent
	if h.Import(context.Background(), b) == nil || len(h.View()) != 0 {
		t.Fatal("store catalog holder retargeted")
	}
}

type qaStepContext struct {
	context.Context
	calls, stopAt int
}

func (c *qaStepContext) Err() error {
	c.calls++
	if c.calls >= c.stopAt {
		return context.Canceled
	}
	return nil
}
func TestQAMidReadCancellationNeverReturnsBatch(t *testing.T) {
	c, s, k := qaFixture(t)
	base := qaJSON(t, s)
	p := append(append([]byte{}, base...), bytes.Repeat([]byte(" "), a.MaxPlaintext-len(base))...)
	cipher := qaRaw(t, p, k)
	ctx := &qaStepContext{Context: context.Background(), stopAt: 6}
	b, e := a.Open(ctx, cipher, k, qaOwner, c)
	if e != a.ErrCancelled || b != nil || ctx.calls < ctx.stopAt {
		t.Fatal("midstream cancellation returned archive")
	}
}
