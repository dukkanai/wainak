package archivebridge

import (
	"bytes"
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"math"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	history "wainek.local/historyarchive"
)

const sampleRecords = `[{"event_id":"event_one","occurred_at":"2026-10-24T00:00:00Z","card_id":"sample_card","response_id":"sample_defer"}]`

func setup(t *testing.T) (*registry, int64) {
	t.Helper()
	r := newRegistry()
	h, e := r.open()
	if e != nil {
		t.Fatal("setup")
	}
	t.Cleanup(func() { r.close(h) })
	return r, h
}
func cipherFor(t *testing.T, r *registry, h int64) []byte {
	t.Helper()
	b, e := r.export(h, 1, []byte(sampleRecords))
	if e != nil {
		t.Fatal("export setup")
	}
	return b
}
func rowCount(t *testing.T, r *registry, h, epoch int64) int {
	t.Helper()
	b, e := r.snapshot(h, epoch)
	if e != nil {
		t.Fatal("snapshot setup")
	}
	var view historyView
	if json.Unmarshal(b, &view) != nil || view.Profile != Profile || !view.Synthetic {
		t.Fatal("view envelope")
	}
	for _, v := range view.Records {
		if !v.Imported || v.AuthenticatedAuthor {
			t.Fatal("authority restored")
		}
	}
	return len(view.Records)
}
func barrier(r *registry, name string) (<-chan struct{}, func()) {
	reached := make(chan struct{})
	release := make(chan struct{})
	var once sync.Once
	r.stage = func(stage string) {
		if stage == name {
			once.Do(func() { close(reached) })
			<-release
		}
	}
	var releaseOnce sync.Once
	return reached, func() { releaseOnce.Do(func() { close(release) }) }
}
func waitStage(t *testing.T, ch <-chan struct{}) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(3 * time.Second):
		t.Fatal("barrier deadline")
	}
}
func waitErr(t *testing.T, ch <-chan error) error {
	t.Helper()
	select {
	case e := <-ch:
		return e
	case <-time.After(3 * time.Second):
		t.Fatal("operation deadline")
		return nil
	}
}

func TestPublicSyntheticRoundTrip(t *testing.T) {
	h, e := NewSyntheticSession()
	if e != nil {
		t.Fatal("open")
	}
	defer Close(h)
	epoch, e := Epoch(h)
	if e != nil || epoch != 1 {
		t.Fatal("epoch")
	}
	cipher, e := ExportHistory(h, epoch, []byte(sampleRecords))
	if e != nil {
		t.Fatal("export")
	}
	if e = ImportHistory(h, epoch, cipher); e != nil {
		t.Fatal("import")
	}
	b, e := HistorySnapshot(h, epoch)
	if e != nil {
		t.Fatal("snapshot")
	}
	var view historyView
	if json.Unmarshal(b, &view) != nil || len(view.Records) != 1 || !view.Synthetic || !view.Records[0].Imported || view.Records[0].AuthenticatedAuthor {
		t.Fatal("history flags")
	}
	if e = ImportHistory(h, epoch, cipher); e != errConflict {
		t.Fatal("replay")
	}
	next, e := Cancel(h, epoch)
	if e != nil || next != 2 {
		t.Fatal("cancel")
	}
	if _, e = HistorySnapshot(h, epoch); e != errStale {
		t.Fatal("old epoch")
	}
	if e = Close(h); e != nil {
		t.Fatal("close")
	}
	if e = Close(h); e != nil {
		t.Fatal("repeat close")
	}
	if _, e = Epoch(h); e != errStale {
		t.Fatal("closed handle")
	}
}
func TestStrictRecordDTO(t *testing.T) {
	r, h := setup(t)
	bad := []string{"", `null`, `{}`, `[null]`, `[] []`, strings.Replace(sampleRecords, `"event_id"`, `"Event_ID"`, 1), strings.Replace(sampleRecords, `"event_id":"event_one"`, `"event_id":"event_one","event_\u0069d":"event_two"`, 1), strings.Replace(sampleRecords, `"event_id":"event_one"`, `"event_id":3`, 1), strings.Replace(sampleRecords, `"event_id":"event_one"`, `"event_id":true`, 1), strings.Replace(sampleRecords, `"event_id":"event_one"`, `"event_id":{}`, 1), strings.Replace(sampleRecords, `"event_id":"event_one"`, `"event_id":"\ud800"`, 1), strings.Replace(sampleRecords, `"event_id":"event_one"`, `"event_id":"event_one","outbox":"send"`, 1), strings.Replace(sampleRecords, `"sample_defer"`, `"unknown"`, 1), strings.Replace(sampleRecords, `"sample_card"`, `"other_card"`, 1), strings.Replace(sampleRecords, `"2026-10-24T00:00:00Z"`, `"2026-10-24T00:00:00+00:00"`, 1), strings.Repeat(" ", history.MaxPlaintext+1), string([]byte{'[', '"', 0xff, '"', ']'})}
	for i, input := range bad {
		t.Run("bad_"+strconv.Itoa(i), func(t *testing.T) {
			b, e := r.export(h, 1, []byte(input))
			if e == nil || b != nil {
				t.Fatal("invalid DTO accepted")
			}
		})
	}
	if b, e := r.export(h, 1, []byte("[]")); e != nil || len(b) == 0 {
		t.Fatal("empty array")
	}
	dup := "[" + strings.Trim(sampleRecords, "[]") + "," + strings.Trim(sampleRecords, "[]") + "]"
	if _, e := r.export(h, 1, []byte(dup)); e != errInvalid {
		t.Fatal("duplicate record ID")
	}
	if e := r.importHistory(h, 1, make([]byte, history.MaxCiphertext+1)); e != errInvalid {
		t.Fatal("cipher bound")
	}
}
func TestCancelExportAndStaleCancel(t *testing.T) {
	r, h := setup(t)
	reached, release := barrier(r, "export_before_publish")
	defer release()
	done := make(chan error, 1)
	go func() {
		b, e := r.export(h, 1, []byte(sampleRecords))
		if b != nil {
			done <- errInvalid
		} else {
			done <- e
		}
	}()
	waitStage(t, reached)
	epoch, e := r.cancel(h, 1)
	if e != nil || epoch != 2 {
		t.Fatal("cancel")
	}
	if _, e = r.cancel(h, 1); e != errStale {
		t.Fatal("stale cancel")
	}
	if _, e = r.begin(h, 2); e != errBusy {
		t.Fatal("premature slot reuse")
	}
	release()
	if waitErr(t, done) != errStale {
		t.Fatal("stale export returned")
	}
	if epoch, e = r.epoch(h); e != nil || epoch != 2 || r.active != 0 {
		t.Fatal("generation/accounting")
	}
}
func TestCancelImportBeforeCommit(t *testing.T) {
	r, h := setup(t)
	cipher := cipherFor(t, r, h)
	reached, release := barrier(r, "import_before_commit")
	defer release()
	done := make(chan error, 1)
	go func() { done <- r.importHistory(h, 1, cipher) }()
	waitStage(t, reached)
	if _, e := r.cancel(h, 1); e != nil {
		t.Fatal("cancel")
	}
	release()
	if waitErr(t, done) != errStale {
		t.Fatal("stale import result")
	}
	if rowCount(t, r, h, 2) != 0 {
		t.Fatal("cancelled import committed")
	}
}
func TestCloseImportAndNeverReuse(t *testing.T) {
	r, h := setup(t)
	cipher := cipherFor(t, r, h)
	store := r.sessions[h].history
	reached, release := barrier(r, "import_before_commit")
	defer release()
	done := make(chan error, 1)
	go func() { done <- r.importHistory(h, 1, cipher) }()
	waitStage(t, reached)
	if r.close(h) != nil || r.active != 1 {
		t.Fatal("close accounting")
	}
	next, e := r.open()
	if e != nil || next <= h {
		t.Fatal("handle reused")
	}
	defer r.close(next)
	release()
	if waitErr(t, done) != errStale || len(store.View()) != 0 {
		t.Fatal("closed import committed")
	}
}
func TestCancelSnapshotCannotReturnOldRows(t *testing.T) {
	r, h := setup(t)
	if r.importHistory(h, 1, cipherFor(t, r, h)) != nil {
		t.Fatal("setup")
	}
	reached, release := barrier(r, "snapshot_before_publish")
	defer release()
	done := make(chan error, 1)
	go func() {
		b, e := r.snapshot(h, 1)
		if b != nil {
			done <- errInvalid
		} else {
			done <- e
		}
	}()
	waitStage(t, reached)
	r.cancel(h, 1)
	release()
	if waitErr(t, done) != errStale {
		t.Fatal("stale snapshot escaped")
	}
}
func TestCancelAfterCommitPreservesHistory(t *testing.T) {
	r, h := setup(t)
	if r.importHistory(h, 1, cipherFor(t, r, h)) != nil {
		t.Fatal("import")
	}
	if _, e := r.cancel(h, 1); e != nil {
		t.Fatal("cancel")
	}
	if rowCount(t, r, h, 2) != 1 {
		t.Fatal("cancel rolled back committed history")
	}
}
func TestCapacityAndSlotsUntilRealCompletion(t *testing.T) {
	r := newRegistry()
	handles := []int64{}
	for i := 0; i < maxSessions; i++ {
		h, e := r.open()
		if e != nil {
			t.Fatal("capacity setup")
		}
		handles = append(handles, h)
	}
	defer func() {
		for _, h := range handles {
			r.close(h)
		}
	}()
	if _, e := r.open(); e != errCapacity {
		t.Fatal("context cap")
	}
	one, e := r.begin(handles[0], 1)
	if e != nil {
		t.Fatal("slot1")
	}
	two, e := r.begin(handles[1], 1)
	if e != nil {
		t.Fatal("slot2")
	}
	if _, e = r.begin(handles[2], 1); e != errBusy {
		t.Fatal("work cap")
	}
	r.close(handles[0])
	r.close(handles[1])
	if _, e = r.open(); e != errBusy {
		t.Fatal("close released active slot")
	}
	r.done(one)
	h, e := r.open()
	if e != nil {
		t.Fatal("released slot unavailable")
	}
	r.close(h)
	r.done(two)
	if r.active != 0 || r.opening != 0 {
		t.Fatal("slot leak")
	}
}
func TestCrossContextKeyOwnerAndCatalogue(t *testing.T) {
	r, h := setup(t)
	cipher := cipherFor(t, r, h)
	other, e := r.open()
	if e != nil {
		t.Fatal("setup")
	}
	defer r.close(other)
	if e = r.importHistory(other, 1, cipher); e != errCrypto {
		t.Fatal("cross key")
	}
	r.sessions[other].key = r.sessions[h].key
	if e = r.importHistory(other, 1, cipher); e != errInvalid {
		t.Fatal("cross owner")
	}
	r.sessions[other].owner = r.sessions[h].owner
	divergent, _ := history.NewCatalog(sampleVersion, map[string][]string{"sample_card": {"other_yes", "other_no"}})
	r.sessions[other].catalog = divergent
	if e = r.importHistory(other, 1, cipher); e != errInvalid {
		t.Fatal("same version divergent catalogue")
	}
	if rowCount(t, r, other, 1) != 0 {
		t.Fatal("cross-context partial commit")
	}
}
func TestSnapshotsAreCopiesAndStable(t *testing.T) {
	r, h := setup(t)
	cipher := cipherFor(t, r, h)
	original := append([]byte(nil), cipher...)
	if r.importHistory(h, 1, cipher) != nil {
		t.Fatal("import")
	}
	for i := range cipher {
		cipher[i] = 0
	}
	one, e := r.snapshot(h, 1)
	if e != nil {
		t.Fatal("snapshot")
	}
	saved := append([]byte(nil), one...)
	for i := range one {
		one[i] = 0
	}
	two, e := r.snapshot(h, 1)
	if e != nil || !bytes.Equal(saved, two) {
		t.Fatal("mutable returned history")
	}
	if r.importHistory(h, 1, original) != errConflict {
		t.Fatal("input alias modified stored history")
	}
}
func TestPositiveHandleAndOverflowGuards(t *testing.T) {
	r := newRegistry()
	if _, e := r.epoch(0); e != errInvalid {
		t.Fatal("zero handle")
	}
	if r.close(-1) != errInvalid {
		t.Fatal("negative handle")
	}
	if r.close(99) != nil {
		t.Fatal("idempotent close")
	}
	r.next = math.MaxInt64
	if _, e := r.open(); e != errCapacity {
		t.Fatal("handle overflow")
	}
	r, h := setup(t)
	r.sessions[h].epoch = math.MaxInt64
	if _, e := r.cancel(h, math.MaxInt64); e != errCapacity {
		t.Fatal("epoch overflow")
	}
	if _, e := r.epoch(h); e != errStale {
		t.Fatal("overflow context remains")
	}
}
func TestExportedABITypesAreNarrow(t *testing.T) {
	f, e := parser.ParseFile(token.NewFileSet(), filepath.Join("bridge.go"), nil, 0)
	if e != nil {
		t.Fatal("source parse")
	}
	allowed := func(x ast.Expr) bool {
		switch v := x.(type) {
		case *ast.Ident:
			return v.Name == "int64" || v.Name == "error"
		case *ast.ArrayType:
			n, ok := v.Elt.(*ast.Ident)
			return v.Len == nil && ok && n.Name == "byte"
		}
		return false
	}
	count := 0
	for _, decl := range f.Decls {
		fn, ok := decl.(*ast.FuncDecl)
		if !ok || !fn.Name.IsExported() {
			continue
		}
		count++
		if fn.Recv != nil {
			t.Fatal("exported object ABI")
		}
		for _, list := range []*ast.FieldList{fn.Type.Params, fn.Type.Results} {
			if list == nil {
				continue
			}
			for _, field := range list.List {
				if !allowed(field.Type) {
					t.Fatal("unsupported exported type")
				}
			}
		}
	}
	if count != 7 {
		t.Fatal("exported function surface changed")
	}
}

func TestLegacyWainakBridgeProfileSurvivesBrandRename(t *testing.T) {
	if Profile != "wainak-synthetic-history-bridge-v1" {
		t.Fatal("legacy bridge profile changed")
	}
}
