package com.nextaura.wainek

import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine

class MainActivity : FlutterActivity() {
    private var archive: NativeArchiveChannel? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        archive = NativeArchiveChannel(
            flutterEngine.dartExecutor.binaryMessenger,
            ArchiveEngineFactory.create(),
            BuildConfig.DEBUG && BuildConfig.ARCHIVE_BRIDGE_AVAILABLE,
        )
    }

    override fun onStop() {
        archive?.clear()
        super.onStop()
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        archive?.dispose()
        archive = null
        super.cleanUpFlutterEngine(flutterEngine)
    }

    override fun onDestroy() {
        archive?.dispose()
        archive = null
        super.onDestroy()
    }
}
