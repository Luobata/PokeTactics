package com.poketactics.shell

import android.app.Activity
import android.os.Bundle
import android.text.InputType
import android.util.TypedValue
import android.view.KeyEvent
import android.view.inputmethod.EditorInfo
import android.webkit.WebView
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/**
 * Hidden settings page (two fingers held 2 s, or 「设置地址」 on the error page):
 * server address (e.g. a branch server), landscape, the edge guard. docs/73.
 */
class SettingsActivity : Activity() {
    private lateinit var prefs: ShellPrefs
    private lateinit var url: EditText

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = ShellPrefs(this)
        val pad = dp(20)
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
        }
        fun note(text: CharSequence, size: Float = 13f) = TextView(this).apply {
            this.text = text
            textSize = size
            setPadding(0, dp(6), 0, dp(6))
        }
        column.addView(note(getString(R.string.settings_title), 22f))
        column.addView(note(getString(R.string.settings_entry_note)))
        column.addView(note(getString(R.string.settings_url), 15f))
        url = EditText(this).apply {
            id = R.id.settings_url
            setText(prefs.url)
            hint = BuildConfig.DEFAULT_URL
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            imeOptions = EditorInfo.IME_ACTION_GO
            setSingleLine()
            setSelectAllOnFocus(true)
            // IME "Go", or Enter on a hardware keyboard / `adb shell input keyevent ENTER` (IME_NULL).
            setOnEditorActionListener { _, action, event ->
                val enter = action == EditorInfo.IME_NULL && event?.action == KeyEvent.ACTION_DOWN
                if (action == EditorInfo.IME_ACTION_GO || action == EditorInfo.IME_ACTION_DONE || enter) { save(); true }
                else action == EditorInfo.IME_NULL
            }
        }
        column.addView(url)
        val landscape = CheckBox(this).apply {
            id = R.id.settings_landscape
            text = getString(R.string.settings_landscape)
            isChecked = prefs.allowLandscape
            setOnCheckedChangeListener { _, on -> prefs.allowLandscape = on }
        }
        column.addView(landscape)
        val gesture = CheckBox(this).apply {
            id = R.id.settings_gesture
            text = getString(R.string.settings_gesture)
            isChecked = prefs.gestureGuard
            setOnCheckedChangeListener { _, on -> prefs.gestureGuard = on }
        }
        column.addView(gesture)
        column.addView(note(getString(R.string.settings_gesture_note), 12f))
        column.addView(Button(this).apply {
            id = R.id.settings_save
            text = getString(R.string.settings_save)
            setOnClickListener { save() }
        })
        column.addView(Button(this).apply {
            id = R.id.settings_reset
            text = getString(R.string.settings_reset)
            setOnClickListener { url.setText(BuildConfig.DEFAULT_URL) }
        })
        column.addView(Button(this).apply {
            id = R.id.settings_clear
            text = getString(R.string.settings_clear)
            // HTTP cache only: localStorage keeps the save slot the game resumes from.
            setOnClickListener {
                WebView(this@SettingsActivity).apply { clearCache(true); destroy() }
                Toast.makeText(this@SettingsActivity, R.string.settings_cache_cleared, Toast.LENGTH_SHORT).show()
            }
        })
        column.addView(note("版本 ${BuildConfig.VERSION_NAME}（${BuildConfig.VERSION_CODE}）· 默认地址 ${BuildConfig.DEFAULT_URL}", 12f))
        setContentView(ScrollView(this).apply { addView(column) })
        url.requestFocus()
    }

    private fun save() {
        val value = url.text.toString().trim()
        if (!ShellPrefs.isValidUrl(value)) {
            url.error = getString(R.string.settings_bad_url)
            return
        }
        if (value == BuildConfig.DEFAULT_URL) prefs.resetUrl() else prefs.url = value
        finish()  // MainActivity.onResume reloads when the address changed
    }

    private fun dp(value: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value.toFloat(), resources.displayMetrics).toInt()
}
