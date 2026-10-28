// Package historyarchive is an isolated synthetic history-only experiment.
// It has no API, filesystem, network, auth, device trust or messaging integration.
package historyarchive

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"regexp"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"filippo.io/age"
)

const (
	MaxPlaintext  = 1 << 20
	MaxCiphertext = 2 << 20
	MaxRecords    = 2000
	MaxHeader     = 4096
	SchemaVersion = "wainak-history-v1"
)

var (
	ErrInvalid   = errors.New("archive: invalid input")
	ErrCrypto    = errors.New("archive: authentication failed")
	ErrCancelled = errors.New("archive: cancelled")
	ErrWrite     = errors.New("archive: output incomplete")
	ErrConflict  = errors.New("archive: conflicting or repeated event")
	idRE         = regexp.MustCompile(`^[a-z][a-z0-9_]{1,63}$`)
	ownerRE      = regexp.MustCompile(`^owner_[a-z0-9]{16,64}$`)
)

// Catalog is a copied allowlist supplied by the caller, never by an archive.
// Version equality is not sufficient: every import rechecks the store's allowlist.
type Catalog struct {
	version string
	cards   map[string]map[string]bool
	valid   bool
}

func NewCatalog(version string, cards map[string][]string) (*Catalog, error) {
	if !idRE.MatchString(version) || len(cards) == 0 || len(cards) > 2000 {
		return nil, ErrInvalid
	}
	c := &Catalog{version: version, cards: make(map[string]map[string]bool, len(cards))}
	for card, choices := range cards {
		if !idRE.MatchString(card) || len(choices) < 2 || len(choices) > 5 {
			return nil, ErrInvalid
		}
		c.cards[card] = map[string]bool{}
		for _, choice := range choices {
			if !idRE.MatchString(choice) || c.cards[card][choice] {
				return nil, ErrInvalid
			}
			c.cards[card][choice] = true
		}
	}
	c.valid = true
	return c, nil
}

type Record struct {
	EventID    string `json:"event_id"`
	OccurredAt string `json:"occurred_at"`
	CardID     string `json:"card_id"`
	ResponseID string `json:"response_id"`
}

func (Record) String() string { return "HistoryRecord" }

type Snapshot struct {
	SchemaVersion  string   `json:"schema_version"`
	OwnerRef       string   `json:"owner_ref"`
	CatalogVersion string   `json:"catalog_version"`
	Records        []Record `json:"records"`
}

func (Snapshot) String() string { return "HistorySnapshot" }
func validRecord(r Record, c *Catalog) bool {
	if c == nil || !c.valid || !idRE.MatchString(r.EventID) || !c.cards[r.CardID][r.ResponseID] {
		return false
	}
	t, e := time.Parse(time.RFC3339, r.OccurredAt)
	return e == nil && t.Year() >= 1970 && t.Year() <= 2100 && t.UTC().Format("2006-01-02T15:04:05Z") == r.OccurredAt
}
func validate(s Snapshot, c *Catalog, owner string) error {
	if c == nil || !c.valid || !ownerRE.MatchString(owner) || s.OwnerRef != owner || s.SchemaVersion != SchemaVersion || s.CatalogVersion != c.version || s.Records == nil || len(s.Records) > MaxRecords {
		return ErrInvalid
	}
	ids := make(map[string]bool, len(s.Records))
	for _, r := range s.Records {
		if !validRecord(r, c) || ids[r.EventID] {
			return ErrInvalid
		}
		ids[r.EventID] = true
	}
	return nil
}
func cancelled(ctx context.Context) bool { return ctx == nil || ctx.Err() != nil }

// Seal returns only a complete ciphertext, or nil with a fixed non-sensitive error.
func Seal(ctx context.Context, s Snapshot, c *Catalog, to *age.X25519Recipient) ([]byte, error) {
	var out bytes.Buffer
	if err := SealTo(ctx, s, c, to, &out); err != nil {
		return nil, err
	}
	return append([]byte(nil), out.Bytes()...), nil
}

// SealTo is a bounded output seam for synthetic fault injection. Any error means
// the caller MUST discard all output, even if it looks like an age file. It does
// not implement atomic file/provider saving or make a recoverability promise.
func SealTo(ctx context.Context, s Snapshot, c *Catalog, to *age.X25519Recipient, dst io.Writer) error {
	if cancelled(ctx) {
		return ErrCancelled
	}
	if to == nil || dst == nil || validate(s, c, s.OwnerRef) != nil {
		return ErrInvalid
	}
	plain, err := json.Marshal(s)
	if err != nil || len(plain) > MaxPlaintext {
		return ErrInvalid
	}
	checked := &checkedWriter{ctx: ctx, dst: dst}
	w, err := age.Encrypt(checked, to)
	if err != nil {
		if cancelled(ctx) {
			return ErrCancelled
		}
		return ErrWrite
	}
	n, err := w.Write(plain)
	if err != nil || n != len(plain) {
		if cancelled(ctx) {
			return ErrCancelled
		}
		return ErrWrite
	}
	// Required final authenticated chunk; never report success before Close.
	if err = w.Close(); err != nil {
		if cancelled(ctx) {
			return ErrCancelled
		}
		return ErrWrite
	}
	if cancelled(ctx) {
		return ErrCancelled
	}
	return nil
}

type checkedWriter struct {
	ctx context.Context
	dst io.Writer
	n   int
}

func (w *checkedWriter) Write(p []byte) (int, error) {
	if cancelled(w.ctx) {
		return 0, ErrCancelled
	}
	if len(p) > MaxCiphertext-w.n {
		return 0, ErrWrite
	}
	n, err := w.dst.Write(p)
	if n < 0 || n > len(p) {
		return 0, ErrWrite
	}
	w.n += n
	if cancelled(w.ctx) {
		return n, ErrCancelled
	}
	if err != nil || n != len(p) {
		return n, ErrWrite
	}
	return n, nil
}

// singleIdentity uses the library's public identity interface, not a new cipher
// or header parser. This profile intentionally rejects multi-recipient, plugins,
// SSH, passphrases and hybrid keys. Native X25519 unwrap remains upstream code.
type singleIdentity struct{ key *age.X25519Identity }

func (i singleIdentity) Unwrap(s []*age.Stanza) ([]byte, error) {
	if i.key == nil || len(s) != 1 || s[0].Type != "X25519" {
		return nil, ErrCrypto
	}
	return i.key.Unwrap(s)
}

// Batch cannot be manufactured or mutated outside this package. No plaintext
// callbacks or partial results escape before authenticated EOF and validation.
type Batch struct {
	owner, version string
	records        []Record
	valid          bool
}

func (*Batch) String() string { return "ImportedUntrustedBatch" }
func Open(ctx context.Context, cipher []byte, key *age.X25519Identity, owner string, c *Catalog) (*Batch, error) {
	if cancelled(ctx) {
		return nil, ErrCancelled
	}
	if key == nil || c == nil || !c.valid || !ownerRE.MatchString(owner) || len(cipher) == 0 || len(cipher) > MaxCiphertext {
		return nil, ErrInvalid
	}
	end := len(cipher)
	if end > MaxHeader {
		end = MaxHeader
	}
	if !bytes.HasPrefix(cipher, []byte("age-encryption.org/v1\n")) || bytes.Index(cipher[:end], []byte("\n--- ")) < 0 {
		return nil, ErrCrypto
	}
	r, err := age.Decrypt(bytes.NewReader(cipher), singleIdentity{key})
	if err != nil {
		return nil, ErrCrypto
	}
	plain, err := io.ReadAll(io.LimitReader(&contextReader{ctx: ctx, r: r}, MaxPlaintext+1))
	if cancelled(ctx) {
		return nil, ErrCancelled
	}
	if err != nil {
		return nil, ErrCrypto
	}
	if len(plain) > MaxPlaintext {
		return nil, ErrInvalid
	}
	// LimitReader is exhausted only for oversized input (rejected above); all
	// successful results have consumed the upstream reader through authenticated EOF.
	s, err := parse(plain)
	if err != nil || validate(s, c, owner) != nil {
		return nil, ErrInvalid
	}
	if cancelled(ctx) {
		return nil, ErrCancelled
	}
	return &Batch{owner: s.OwnerRef, version: s.CatalogVersion, records: append([]Record(nil), s.Records...), valid: true}, nil
}

type contextReader struct {
	ctx context.Context
	r   io.Reader
}

func (r *contextReader) Read(p []byte) (int, error) {
	if cancelled(r.ctx) {
		return 0, ErrCancelled
	}
	n, e := r.r.Read(p)
	if cancelled(r.ctx) {
		return n, ErrCancelled
	}
	return n, e
}

func exactKeys(raw json.RawMessage, want ...string) bool {
	var m map[string]json.RawMessage
	if json.Unmarshal(raw, &m) != nil || len(m) != len(want) {
		return false
	}
	for _, k := range want {
		if _, ok := m[k]; !ok {
			return false
		}
	}
	return true
}
func parse(data []byte) (Snapshot, error) {
	var s Snapshot
	if len(data) == 0 || len(data) > MaxPlaintext || !utf8.Valid(data) {
		return s, ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	budget := MaxRecords*12 + 100
	if walk(d, 0, &budget) != nil {
		return s, ErrInvalid
	}
	if _, err := d.Token(); err != io.EOF {
		return s, ErrInvalid
	}
	if !exactKeys(data, "schema_version", "owner_ref", "catalog_version", "records") {
		return s, ErrInvalid
	}
	var top map[string]json.RawMessage
	if json.Unmarshal(data, &top) != nil {
		return s, ErrInvalid
	}
	var records []json.RawMessage
	if json.Unmarshal(top["records"], &records) != nil || records == nil || len(records) > MaxRecords {
		return s, ErrInvalid
	}
	for _, r := range records {
		if !exactKeys(r, "event_id", "occurred_at", "card_id", "response_id") {
			return s, ErrInvalid
		}
	}
	if json.Unmarshal(data, &s) != nil {
		return Snapshot{}, ErrInvalid
	}
	return s, nil
}

// walk rejects duplicate keys after JSON unescaping, non-string primitives,
// invalid unicode replacement values, deep input and unbounded collections.
func walk(d *json.Decoder, depth int, budget *int) error {
	*budget--
	if depth > 8 || *budget < 0 {
		return ErrInvalid
	}
	t, e := d.Token()
	if e != nil {
		return ErrInvalid
	}
	switch v := t.(type) {
	case string:
		if len(v) > 256 || strings.ContainsRune(v, '\ufffd') {
			return ErrInvalid
		}
		return nil
	case json.Delim:
		switch v {
		case '{':
			keys := map[string]bool{}
			for d.More() {
				k, e := d.Token()
				s, ok := k.(string)
				if e != nil || !ok || len(s) > 64 || keys[s] || strings.ContainsRune(s, '\ufffd') {
					return ErrInvalid
				}
				keys[s] = true
				if len(keys) > 8 {
					return ErrInvalid
				}
				if walk(d, depth+1, budget) != nil {
					return ErrInvalid
				}
			}
			x, e := d.Token()
			if e != nil || x != json.Delim('}') {
				return ErrInvalid
			}
			return nil
		case '[':
			count := 0
			for d.More() {
				count++
				if count > MaxRecords || walk(d, depth+1, budget) != nil {
					return ErrInvalid
				}
			}
			x, e := d.Token()
			if e != nil || x != json.Delim(']') {
				return ErrInvalid
			}
			return nil
		}
	}
	return ErrInvalid
}

// MemoryHistory is only a synthetic transactional import target, not persistent
// storage. Imported rows are always untrusted history, never permissions/events.
type MemoryHistory struct {
	mu      sync.Mutex
	owner   string
	catalog *Catalog
	rows    map[string]Record
}

func NewMemoryHistory(owner string, c *Catalog) (*MemoryHistory, error) {
	if !ownerRE.MatchString(owner) || c == nil || !c.valid {
		return nil, ErrInvalid
	}
	owned := *c
	return &MemoryHistory{owner: owner, catalog: &owned, rows: map[string]Record{}}, nil
}
func (h *MemoryHistory) Import(ctx context.Context, b *Batch) error {
	if h == nil || b == nil || !b.valid {
		return ErrInvalid
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if cancelled(ctx) {
		return ErrCancelled
	}
	s := Snapshot{SchemaVersion: SchemaVersion, OwnerRef: b.owner, CatalogVersion: b.version, Records: append([]Record{}, b.records...)}
	if validate(s, h.catalog, h.owner) != nil || len(h.rows)+len(b.records) > MaxRecords {
		return ErrInvalid
	}
	for _, r := range b.records {
		if _, exists := h.rows[r.EventID]; exists {
			return ErrConflict
		}
	}
	if cancelled(ctx) {
		return ErrCancelled
	}
	for _, r := range b.records {
		h.rows[r.EventID] = r
	}
	return nil
}

// View returns a copy. Imported is always true and AuthenticatedAuthor always
// false: a valid age archive does not prove who authored its contents.
type HistoryView struct {
	Record              Record
	Imported            bool
	AuthenticatedAuthor bool
}

func (h *MemoryHistory) View() []HistoryView {
	if h == nil {
		return nil
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	rows := make([]HistoryView, 0, len(h.rows))
	for _, r := range h.rows {
		rows = append(rows, HistoryView{Record: r, Imported: true, AuthenticatedAuthor: false})
	}
	return rows
}
