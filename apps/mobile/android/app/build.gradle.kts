plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("dev.flutter.flutter-gradle-plugin")
}

// No implicit AAR lookup/download: artifact path and expected digest are explicit.
val archivePath = providers.gradleProperty("wainakArchiveAar").orNull
val archiveHash = providers.gradleProperty("wainakArchiveSha256").orNull
require((archivePath == null) == (archiveHash == null)) { "archive_artifact_configuration" }
val archiveAar = archivePath?.let {
    require(it == "libs/wainak-archivebridge.aar") { "archive_artifact_path" }
    val candidate = file(it)
    require(candidate.isFile && archiveHash!!.matches(Regex("[a-f0-9]{64}"))) { "archive_artifact_missing" }
    var path = candidate.toPath()
    while (path != projectDir.toPath()) {
        require(!java.nio.file.Files.isSymbolicLink(path)) { "archive_artifact_symlink" }
        path = path.parent ?: error("archive_artifact_path")
    }
    val digest = java.security.MessageDigest.getInstance("SHA-256")
    candidate.inputStream().use { input ->
        val buffer = ByteArray(65536)
        while (true) {
            val read = input.read(buffer)
            if (read < 0) break
            digest.update(buffer, 0, read)
        }
    }
    require(digest.digest().joinToString("") { "%02x".format(it) } == archiveHash) { "archive_artifact_digest" }
    candidate
}

android {
    namespace = "invalid.example.wainak.wainak_mobile"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    ndkVersion = "30.0.16248370"
    buildFeatures { buildConfig = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    defaultConfig {
        applicationId = "invalid.example.wainak.wainak_mobile"
        minSdk = 24
        targetSdk = 36
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        buildConfigField("boolean", "ARCHIVE_BRIDGE_AVAILABLE", (archiveAar != null).toString())
    }
    // This isolated spike is UNSIGNED, including debug/profile. Never generate
    // ~/.android/debug.keystore or use release credentials to test this slice.
    buildTypes.configureEach { signingConfig = null }
    sourceSets.getByName("main").java.srcDir(
        if (archiveAar == null) "src/archiveUnavailable/kotlin" else "src/archiveBridge/kotlin"
    )
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

if (archiveAar != null) {
    dependencies { implementation(files(archiveAar)) }
}

flutter { source = "../.." }
