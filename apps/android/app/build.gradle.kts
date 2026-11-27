import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Inputs from tools/android/build.sh (docs/73); the defaults let a plain Gradle build work too.
fun prop(name: String, default: String) = (findProperty(name) as String?)?.takeIf { it.isNotBlank() } ?: default
val defaultUrl = prop("poketactics.defaultUrl", "https://10.37.30.198:8821/play")
val previewHosts = prop("poketactics.hosts", "10.37.30.198")
val shellVersionCode = prop("poketactics.versionCode", "1").toInt()
val shellVersionName = prop("poketactics.versionName", "1.0.$shellVersionCode")
val generatedRes = file("src/generated/res")
if (!generatedRes.resolve("xml/network_security_config.xml").isFile) {
    throw GradleException("Missing $generatedRes: build through tools/android/build.sh (it writes the trust config).")
}

// Fixed self-signed key so a newer APK installs over an older one. Lives outside the
// repository (default ~/.config/poketactics-android/keystore.properties, docs/73).
val keystoreProps = file(prop("poketactics.keystoreProperties",
    "${System.getProperty("user.home")}/.config/poketactics-android/keystore.properties"))
val keystore = Properties().apply { if (keystoreProps.isFile) keystoreProps.inputStream().use { load(it) } }

android {
    namespace = "com.poketactics.shell"
    compileSdk = 36
    buildToolsVersion = "36.0.0"

    defaultConfig {
        applicationId = "com.poketactics.shell"
        minSdk = 26
        targetSdk = 36
        versionCode = shellVersionCode
        versionName = shellVersionName
        buildConfigField("String", "DEFAULT_URL", "\"$defaultUrl\"")
        buildConfigField("String", "PREVIEW_HOSTS", "\"$previewHosts\"")
    }

    signingConfigs {
        if (keystore.getProperty("storeFile") != null) {
            create("shell") {
                storeFile = file(keystore.getProperty("storeFile"))
                storePassword = keystore.getProperty("storePassword")
                keyAlias = keystore.getProperty("keyAlias")
                keyPassword = keystore.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        // The preview App ships the debug build: WebView remote debugging stays on for
        // the adb E2E (tools/android/shell_e2e.py), and it is never published to a store.
        getByName("debug") {
            signingConfigs.findByName("shell")?.let { signingConfig = it }
        }
        getByName("release") {
            isMinifyEnabled = false
            signingConfigs.findByName("shell")?.let { signingConfig = it }
        }
    }

    sourceSets["main"].res.srcDir(generatedRes)

    buildFeatures { buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin { jvmToolchain(17) }

dependencies {
    implementation("androidx.core:core-ktx:1.16.0")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("androidx.webkit:webkit:1.14.0")
}
