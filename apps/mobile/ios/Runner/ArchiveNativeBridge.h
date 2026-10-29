#import <Foundation/Foundation.h>

// Private C ABI owned by this host. No NSError importer guessing and no keys,
// ciphertext or history crossing into Swift/Flutter. Enabled in Debug only by
// a reviewed artifact-derived configuration; no framework is bundled here.
#if defined(WAINEK_ARCHIVE_BRIDGE) && WAINEK_ARCHIVE_BRIDGE
FOUNDATION_EXPORT int64_t WainekArchiveOpen(void); // >0 handle, 0 failure, -1 cleanup uncertain
FOUNDATION_EXPORT int32_t WainekArchiveRoundTrip(int64_t session); // 2 or 0
FOUNDATION_EXPORT BOOL WainekArchiveClose(int64_t session);
#endif
