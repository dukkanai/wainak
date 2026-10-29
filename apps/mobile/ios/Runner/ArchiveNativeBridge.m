#import "ArchiveNativeBridge.h"

#if defined(WAINEK_ARCHIVE_BRIDGE) && WAINEK_ARCHIVE_BRIDGE
// Exact generated prototypes: header SHA256 2ba29fb669cfc99e867fc33168a31f40e14790626ccc429c3d641e516c313ba3.
// Framework/module packaging is source-verified, not Apple-compiled evidence.
#import <Archivebridge/Archivebridge.h>
#import <CoreFoundation/CoreFoundation.h>

static BOOL WainekBool(id value, BOOL expected) {
  return [value isKindOfClass:[NSNumber class]] &&
    CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID() &&
    [(NSNumber *)value boolValue] == expected;
}

static BOOL WainekKeys(NSDictionary *value, NSArray<NSString *> *keys) {
  return value.count == keys.count &&
    [[NSSet setWithArray:value.allKeys] isEqualToSet:[NSSet setWithArray:keys]];
}

static BOOL WainekCloseChecked(int64_t session) {
  if (session <= 0) return NO;
  NSError *error = nil;
  BOOL closed = ArchivebridgeClose(session, &error);
  return closed && error == nil;
}

int64_t WainekArchiveOpen(void) {
  @autoreleasepool {
    int64_t session = 0;
    NSError *error = nil;
    BOOL opened = ArchivebridgeNewSyntheticSession(&session, &error);
    if (!opened || error != nil || session <= 0) {
      if (session > 0 && !WainekCloseChecked(session)) return -1;
      return 0;
    }
    return session;
  }
}

int32_t WainekArchiveRoundTrip(int64_t session) {
  @autoreleasepool {
    if (session <= 0) return 0;
    NSError *error = nil;
    int64_t epoch = 0;
    if (!ArchivebridgeEpoch(session, &epoch, &error) || error != nil || epoch <= 0) return 0;
    static const char records[] =
      "[{\"event_id\":\"event_one\",\"occurred_at\":\"2026-10-24T00:00:00Z\",\"card_id\":\"sample_card\",\"response_id\":\"sample_defer\"},"
      "{\"event_id\":\"event_two\",\"occurred_at\":\"2026-10-24T00:01:00Z\",\"card_id\":\"sample_card\",\"response_id\":\"sample_yes\"}]";
    NSData *input = [[NSData alloc] initWithBytes:records length:sizeof(records) - 1];
    error = nil;
    NSData *exported = ArchivebridgeExportHistory(session, epoch, input, &error);
    // Validate BEFORE copying. `copy` on immutable NSData can preserve aliases.
    if (error != nil || exported == nil || exported.length == 0 || exported.length > 2 * 1024 * 1024) return 0;
    NSData *cipher = [[NSData alloc] initWithBytes:exported.bytes length:exported.length];
    NSData *importInput = [[NSData alloc] initWithBytes:cipher.bytes length:cipher.length];
    error = nil;
    if (!ArchivebridgeImportHistory(session, epoch, importInput, &error) || error != nil) return 0;
    error = nil;
    NSData *snapshot = ArchivebridgeHistorySnapshot(session, epoch, &error);
    if (error != nil || snapshot == nil || snapshot.length == 0 || snapshot.length > 1024 * 1024) return 0;
    NSData *history = [[NSData alloc] initWithBytes:snapshot.bytes length:snapshot.length];
    if ([[NSString alloc] initWithData:history encoding:NSUTF8StringEncoding] == nil) return 0;
    error = nil;
    id decoded = [NSJSONSerialization JSONObjectWithData:history options:0 error:&error];
    if (error != nil || ![decoded isKindOfClass:[NSDictionary class]]) return 0;
    NSDictionary *root = decoded;
    if (!WainekKeys(root, @[@"profile", @"synthetic", @"records"]) ||
        ![root[@"profile"] isEqual:@"wainak-synthetic-history-bridge-v1"] ||
        !WainekBool(root[@"synthetic"], YES) ||
        ![root[@"records"] isKindOfClass:[NSArray class]]) return 0;
    NSArray *rows = root[@"records"];
    if (rows.count != 2) return 0;
    NSDictionary *expected = @{
      @"event_one": @[@"2026-10-24T00:00:00Z", @"sample_defer"],
      @"event_two": @[@"2026-10-24T00:01:00Z", @"sample_yes"]
    };
    NSMutableSet<NSString *> *seen = [NSMutableSet setWithCapacity:2];
    for (id raw in rows) {
      if (![raw isKindOfClass:[NSDictionary class]]) return 0;
      NSDictionary *row = raw;
      if (!WainekKeys(row, @[@"event_id", @"occurred_at", @"card_id", @"response_id", @"imported", @"authenticated_author"]) ||
          ![row[@"event_id"] isKindOfClass:[NSString class]]) return 0;
      NSString *event = row[@"event_id"];
      NSArray *pair = expected[event];
      if (pair == nil || [seen containsObject:event] ||
          ![row[@"occurred_at"] isEqual:pair[0]] ||
          ![row[@"card_id"] isEqual:@"sample_card"] ||
          ![row[@"response_id"] isEqual:pair[1]] ||
          !WainekBool(row[@"imported"], YES) ||
          !WainekBool(row[@"authenticated_author"], NO)) return 0;
      [seen addObject:event];
    }
    return 2;
  }
}

BOOL WainekArchiveClose(int64_t session) {
  @autoreleasepool { return WainekCloseChecked(session); }
}
#endif
