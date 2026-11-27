package com.poketactics.shell

import android.content.Context
import android.net.Uri

/** Settings of the shell App (hidden settings page, docs/73). */
class ShellPrefs(context: Context) {
    private val prefs = context.getSharedPreferences("shell", Context.MODE_PRIVATE)

    var url: String
        get() = prefs.getString(KEY_URL, null)?.takeIf { it.isNotBlank() } ?: BuildConfig.DEFAULT_URL
        set(value) = prefs.edit().putString(KEY_URL, value.trim()).apply()

    /** Default: portrait locked. */
    var allowLandscape: Boolean
        get() = prefs.getBoolean(KEY_LANDSCAPE, false)
        set(value) = prefs.edit().putBoolean(KEY_LANDSCAPE, value).apply()

    /** Default on: the middle of each side edge does not start the back swipe. */
    var gestureGuard: Boolean
        get() = prefs.getBoolean(KEY_GESTURE, true)
        set(value) = prefs.edit().putBoolean(KEY_GESTURE, value).apply()

    fun resetUrl() = prefs.edit().remove(KEY_URL).apply()

    companion object {
        private const val KEY_URL = "url"
        private const val KEY_LANDSCAPE = "allow_landscape"
        private const val KEY_GESTURE = "gesture_guard"

        /** "scheme://host:port" of a URL, as WebView origin rules and same-origin checks want it. */
        fun originOf(url: String): String? {
            val uri = Uri.parse(url)
            val scheme = uri.scheme?.lowercase() ?: return null
            val host = uri.host ?: return null
            if (scheme != "http" && scheme != "https") return null
            val port = if (uri.port != -1) uri.port else if (scheme == "https") 443 else 80
            return "$scheme://$host:$port"
        }

        fun isValidUrl(url: String): Boolean = originOf(url.trim()) != null
    }
}
