import java.nio.file.Files
import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("dev.flutter.flutter-gradle-plugin")
}

// No implicit AAR lookup/download: artifact path and expected digest are explicit.
val archivePath = providers.gradleProperty("wainekArchiveAar").orNull
val archiveHash = providers.gradleProperty("wainekArchiveSha256").orNull
require((archivePath == null) == (archiveHash == null)) { "archive_artifact_configuration" }
val archiveAar = archivePath?.let {
    require(it == "libs/wainek-archivebridge.aar") { "archive_artifact_path" }
    val candidate = file(it)
    require(candidate.isFile && archiveHash!!.matches(Regex("[a-f0-9]{64}"))) { "archive_artifact_missing" }
    var path = candidate.toPath()
    while (path != projectDir.toPath()) {
        require(!Files.isSymbolicLink(path)) { "archive_artifact_symlink" }
        path = path.parent ?: error("archive_artifact_path")
    }
    val digest = MessageDigest.getInstance("SHA-256")
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
    namespace = "com.nextaura.wainek"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    ndkVersion = "30.0.16248370"
    buildFeatures { buildConfig = true }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    defaultConfig {
        applicationId = "com.nextaura.wainek"
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

// AGP keeps variant version defaults even when the DSL signing config is null.
// Explicitly disable all formats; this never creates a config or a key.
androidComponents {
    onVariants(selector().all()) { variant ->
        variant.signingConfig?.let { config ->
            config.enableV1Signing.set(false)
            config.enableV2Signing.set(false)
            config.enableV3Signing.set(false)
            config.enableV4Signing.set(false)
        }
    }
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
