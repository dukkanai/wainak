// Package archivebridge is a synthetic-only, in-memory binding feasibility
// facade. It is not an account, key-custody, storage or live messaging API.
package archivebridge

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"math"
	"sort"
	"strconv"
	"strings"
	"sync"
	"unicode/utf8"

	"filippo.io/age"
	history "wainak.local/historyarchive"
)

const Profile = "wainak-synthetic-history-bridge-v1"
const maxSessions = 8
const maxWork = 2
const sampleVersion = "sample_v1"

var (
	errInvalid   = errors.New("bridge_invalid")
	errStale     = errors.New("bridge_stale")
	errBusy      = errors.New("bridge_busy")
	errCapacity  = errors.New("bridge_capacity")
	errCancelled = errors.New("bridge_cancelled")
	errConflict  = errors.New("bridge_conflict")
	errCrypto    = errors.New("bridge_crypto")
)

type session struct {
	epoch     int64
	owner     string
	catalog   *history.Catalog
	key       *age.X25519Identity
	history   *history.MemoryHistory
	operation *operation
}
type operation struct {
	handle, epoch int64
	session       *session
	owner         string
	catalog       *history.Catalog
	key           *age.X25519Identity
	history       *history.MemoryHistory
	ctx           context.Context
	cancel        context.CancelFunc
}
type registry struct {
	mu              sync.Mutex
	next            int64
	opening, active int
	sessions        map[int64]*session
	// Nonexported deterministic test seam; nil for the exported singleton.
	// It receives fixed stage names only, never keys or content.
	stage func(string)
}

func newRegistry() *registry { return &registry{sessions: make(map[int64]*session)} }

var registryInstance = newRegistry()

// NewSyntheticSession creates an isolated ephemeral key and fixed synthetic
// owner/catalog. No key import/export, account or caller catalog is exposed.
func NewSyntheticSession() (int64, error) { return registryInstance.open() }

// Epoch returns the current generation; it is not authentication or ownership.
func Epoch(handle int64) (int64, error) { return registryInstance.epoch(handle) }

// ExportHistory accepts only a strict JSON array of synthetic sample records.
func ExportHistory(handle, epoch int64, recordsJSON []byte) ([]byte, error) {
	return registryInstance.export(handle, epoch, recordsJSON)
}

// ImportHistory authenticates a complete archive before a guarded atomic RAM
// history commit. It restores no live authority, trust, delivery or outbox state.
func ImportHistory(handle, epoch int64, ciphertext []byte) error {
	return registryInstance.importHistory(handle, epoch, ciphertext)
}

// HistorySnapshot returns a copied, bounded JSON projection of untrusted rows.
func HistorySnapshot(handle, epoch int64) ([]byte, error) {
	return registryInstance.snapshot(handle, epoch)
}

// Cancel rejects a stale caller epoch, advances the generation and cancels its
// current work. Previously committed history is preserved, not rolled back.
func Cancel(handle, expectedEpoch int64) (int64, error) {
	return registryInstance.cancel(handle, expectedEpoch)
}

// Close invalidates a never-reused positive handle. Repeated Close is harmless.
// It drops references, not a secure-zeroization or OS memory protection promise.
func Close(handle int64) error { return registryInstance.close(handle) }

func (r *registry) open() (int64, error) {
	r.mu.Lock()
	if len(r.sessions)+r.opening >= maxSessions || r.next == math.MaxInt64 {
		r.mu.Unlock()
		return 0, errCapacity
	}
	if r.active >= maxWork {
		r.mu.Unlock()
		return 0, errBusy
	}
	r.next++
	handle := r.next
	r.opening++
	r.active++
	r.mu.Unlock()
	r.pause("open_reserved")
	// Reserve both a context and a work slot before generating a key. No global
	// lock is held over cryptographic work and there is no waiting-work queue.
	key, e := age.GenerateX25519Identity()
	catalog, ce := history.NewCatalog(sampleVersion, map[string][]string{"sample_card": {"sample_yes", "sample_defer"}})
	owner := "owner_demo" + strings.Repeat("0", 19-len(strconv.FormatInt(handle, 10))) + strconv.FormatInt(handle, 10)
	store, se := history.NewMemoryHistory(owner, catalog)
	r.mu.Lock()
	defer r.mu.Unlock()
	r.opening--
	r.active--
	if e != nil || ce != nil || se != nil {
		return 0, errCrypto
	}
	r.sessions[handle] = &session{epoch: 1, owner: owner, catalog: catalog, key: key, history: store}
	return handle, nil
}
func (r *registry) epoch(handle int64) (int64, error) {
	if handle <= 0 {
		return 0, errInvalid
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	s := r.sessions[handle]
	if s == nil {
		return 0, errStale
	}
	return s.epoch, nil
}
func (r *registry) begin(handle, epoch int64) (*operation, error) {
	if handle <= 0 || epoch <= 0 {
		return nil, errInvalid
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	s := r.sessions[handle]
	if s == nil || s.epoch != epoch {
		return nil, errStale
	}
	if s.operation != nil || r.active >= maxWork {
		return nil, errBusy
	}
	ctx, cancel := context.WithCancel(context.Background())
	op := &operation{handle: handle, epoch: epoch, session: s, owner: s.owner, catalog: s.catalog, key: s.key, history: s.history, ctx: ctx, cancel: cancel}
	s.operation = op
	r.active++
	return op, nil
}
func (r *registry) done(op *operation) {
	op.cancel()
	r.mu.Lock()
	defer r.mu.Unlock()
	if op.session.operation == op {
		op.session.operation = nil
	}
	r.active--
	// Closed operations keep only bounded local references until this actual
	// completion. Close never releases their global work slot prematurely.
}
func (r *registry) currentLocked(op *operation) error {
	if r.sessions[op.handle] != op.session || op.session.epoch != op.epoch {
		return errStale
	}
	if op.ctx.Err() != nil {
		return errCancelled
	}
	return nil
}
func (r *registry) pause(stage string) {
	if r.stage != nil {
		r.stage(stage)
	}
}
func (r *registry) export(handle, epoch int64, input []byte) ([]byte, error) {
	if len(input) == 0 || len(input) > history.MaxPlaintext {
		return nil, errInvalid
	}
	op, e := r.begin(handle, epoch)
	if e != nil {
		return nil, e
	}
	defer r.done(op)
	r.pause("export_before_copy")
	owned := append([]byte(nil), input...)
	r.pause("export_after_copy")
	records, e := parseRecords(owned)
	if e != nil {
		return nil, errInvalid
	}
	s := history.Snapshot{SchemaVersion: history.SchemaVersion, OwnerRef: op.owner, CatalogVersion: sampleVersion, Records: records}
	cipher, e := history.Seal(op.ctx, s, op.catalog, op.key.Recipient())
	if e != nil {
		return nil, mapError(e)
	}
	r.pause("export_before_publish")
	r.mu.Lock()
	defer r.mu.Unlock()
	if e = r.currentLocked(op); e != nil {
		return nil, e
	}
	return append([]byte(nil), cipher...), nil
}
func (r *registry) importHistory(handle, epoch int64, input []byte) error {
	if len(input) == 0 || len(input) > history.MaxCiphertext {
		return errInvalid
	}
	op, e := r.begin(handle, epoch)
	if e != nil {
		return e
	}
	defer r.done(op)
	r.pause("import_before_copy")
	owned := append([]byte(nil), input...)
	r.pause("import_after_copy")
	batch, e := history.Open(op.ctx, owned, op.key, op.owner, op.catalog)
	if e != nil {
		return mapError(e)
	}
	r.pause("import_before_commit")
	// Epoch check and the bounded in-memory commit share one linearization lock.
	// Cancel/Close before it wins; after it, an already committed import remains.
	r.mu.Lock()
	defer r.mu.Unlock()
	if e = r.currentLocked(op); e != nil {
		return e
	}
	return mapError(op.history.Import(op.ctx, batch))
}

type recordView struct {
	EventID             string `json:"event_id"`
	OccurredAt          string `json:"occurred_at"`
	CardID              string `json:"card_id"`
	ResponseID          string `json:"response_id"`
	Imported            bool   `json:"imported"`
	AuthenticatedAuthor bool   `json:"authenticated_author"`
}
type historyView struct {
	Profile   string       `json:"profile"`
	Synthetic bool         `json:"synthetic"`
	Records   []recordView `json:"records"`
}

func (r *registry) snapshot(handle, epoch int64) ([]byte, error) {
	op, e := r.begin(handle, epoch)
	if e != nil {
		return nil, e
	}
	defer r.done(op)
	rows := op.history.View()
	view := historyView{Profile: Profile, Synthetic: true, Records: make([]recordView, 0, len(rows))}
	for _, row := range rows {
		v := row.Record
		view.Records = append(view.Records, recordView{v.EventID, v.OccurredAt, v.CardID, v.ResponseID, true, false})
	}
	sort.Slice(view.Records, func(i, j int) bool { return view.Records[i].EventID < view.Records[j].EventID })
	out, e := json.Marshal(view)
	if e != nil || len(out) > history.MaxPlaintext {
		return nil, errInvalid
	}
	r.pause("snapshot_before_publish")
	r.mu.Lock()
	defer r.mu.Unlock()
	if e = r.currentLocked(op); e != nil {
		return nil, e
	}
	return append([]byte(nil), out...), nil
}
func (r *registry) cancel(handle, expected int64) (int64, error) {
	if handle <= 0 || expected <= 0 {
		return 0, errInvalid
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	s := r.sessions[handle]
	if s == nil || s.epoch != expected {
		return 0, errStale
	}
	if s.epoch == math.MaxInt64 {
		if s.operation != nil {
			s.operation.cancel()
		}
		delete(r.sessions, handle)
		s.key = nil
		s.catalog = nil
		s.history = nil
		return 0, errCapacity
	}
	s.epoch++
	if s.operation != nil {
		s.operation.cancel()
	}
	return s.epoch, nil
}
func (r *registry) close(handle int64) error {
	if handle <= 0 {
		return errInvalid
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	s := r.sessions[handle]
	if s == nil {
		return nil
	}
	if s.operation != nil {
		s.operation.cancel()
	}
	delete(r.sessions, handle)
	s.key = nil
	s.catalog = nil
	s.history = nil
	return nil
}
func mapError(e error) error {
	switch e {
	case nil:
		return nil
	case history.ErrInvalid:
		return errInvalid
	case history.ErrCancelled:
		return errCancelled
	case history.ErrConflict:
		return errConflict
	default:
		return errCrypto
	}
}

// A deliberately small DTO parser. Decoded duplicate/unknown/case-aliased keys,
// nested values, non-string values, lone surrogates, invalid UTF-8 and trailing
// data are rejected before conversion to the core's typed snapshot.
func parseRecords(input []byte) ([]history.Record, error) {
	if len(input) == 0 || len(input) > history.MaxPlaintext || !utf8.Valid(input) {
		return nil, errInvalid
	}
	d := json.NewDecoder(bytes.NewReader(input))
	token, e := d.Token()
	if e != nil || token != json.Delim('[') {
		return nil, errInvalid
	}
	records := make([]history.Record, 0)
	for d.More() {
		if len(records) >= history.MaxRecords {
			return nil, errInvalid
		}
		token, e = d.Token()
		if e != nil || token != json.Delim('{') {
			return nil, errInvalid
		}
		fields := map[string]string{}
		for d.More() {
			token, e = d.Token()
			name, ok := token.(string)
			if e != nil || !ok || len(name) > 32 {
				return nil, errInvalid
			}
			if name != "event_id" && name != "occurred_at" && name != "card_id" && name != "response_id" {
				return nil, errInvalid
			}
			if _, exists := fields[name]; exists {
				return nil, errInvalid
			}
			token, e = d.Token()
			value, ok := token.(string)
			if e != nil || !ok || len(value) > 256 || strings.ContainsRune(value, '\ufffd') {
				return nil, errInvalid
			}
			fields[name] = value
		}
		token, e = d.Token()
		if e != nil || token != json.Delim('}') || len(fields) != 4 {
			return nil, errInvalid
		}
		records = append(records, history.Record{EventID: fields["event_id"], OccurredAt: fields["occurred_at"], CardID: fields["card_id"], ResponseID: fields["response_id"]})
	}
	token, e = d.Token()
	if e != nil || token != json.Delim(']') {
		return nil, errInvalid
	}
	if _, e = d.Token(); e != io.EOF {
		return nil, errInvalid
	}
	return records, nil
}
