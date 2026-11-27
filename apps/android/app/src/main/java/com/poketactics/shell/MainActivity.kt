package com.poketactics.shell

import android.annotation.SuppressLint
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.ActivityInfo
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Rect
import android.net.Uri
import android.net.http.SslCertificate
import android.net.http.SslError
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowManager
import android.webkit.ConsoleMessage
import android.webkit.RenderProcessGoneDetail
import android.webkit.SslErrorHandler
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.webkit.WebViewCompat
import androidx.webkit.WebViewFeature
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import kotlin.math.hypot
import kotlin.math.min

/**
 * The game in a full-screen WebView (docs/73).
 *
 * Back key / back swipe (predictive back included) never navigates the WebView history:
 * it asks the page to close its top overlay (`window.PokeTacticsShell.onBack()`, from
 * play_mobile.js), and only when nothing was open shows "退出游戏？".
 */
class MainActivity : ComponentActivity() {
    private lateinit var prefs: ShellPrefs
    private lateinit var root: FrameLayout
    private lateinit var webView: WebView
    private lateinit var loading: TextView
    private lateinit var errorView: LinearLayout
    private lateinit var errorDetail: TextView
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var vibes: Vibes

    private var loadedUrl: String? = null
    private var listenerOrigin: String? = null
    private var mainFrameFailed = false
    private var pageReady = false
    private var backPending = false
    private var exitDialog: AlertDialog? = null
    private var fileCallback: ValueCallback<Array<Uri>>? = null
    // An unreachable address (wrong network / VPN off) can hang in TCP connect for minutes.
    private val connectWatchdog = Runnable {
        if (!pageReady && !mainFrameFailed) {
            webView.stopLoading()
            showError("连接超时（${CONNECT_TIMEOUT_MS / 1000} 秒）：确认手机连着公司内网 / VPN")
        }
    }

    private val pickFile = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        fileCallback?.onReceiveValue(uri?.let { arrayOf(it) } ?: arrayOf())
        fileCallback = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        prefs = ShellPrefs(this)
        vibes = Vibes(this)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        WindowCompat.setDecorFitsSystemWindows(window, false)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            window.attributes = window.attributes.apply {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }
        // The debug build is the one the preview ships: chrome://inspect and the adb E2E.
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)
        buildViews()
        applyOrientation()
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = onSystemBack()
        })
        load(prefs.url)
    }

    // ------------------------------------------------------------------ views
    @SuppressLint("SetJavaScriptEnabled")
    private fun buildViews() {
        root = FrameLayout(this).apply {
            id = R.id.shell_root
            // Shows only in the cutout band (padding below): match the game's HUD, not black.
            setBackgroundColor(getColor(R.color.pt_letterbox))
        }
        webView = newWebView()
        loading = TextView(this).apply {
            id = R.id.shell_loading
            text = getString(R.string.loading)
            setTextColor(getColor(R.color.pt_text))
            textSize = 16f
            gravity = Gravity.CENTER
            setBackgroundColor(getColor(R.color.pt_background))
        }
        errorDetail = TextView(this).apply {
            id = R.id.shell_error_detail
            setTextColor(getColor(R.color.pt_text))
            textSize = 13f
            gravity = Gravity.CENTER
            setPadding(0, dp(8), 0, dp(20))
        }
        errorView = LinearLayout(this).apply {
            id = R.id.shell_error
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setPadding(dp(32), dp(32), dp(32), dp(32))
            setBackgroundColor(getColor(R.color.pt_background))
            visibility = View.GONE
            addView(TextView(context).apply {
                text = getString(R.string.error_title)
                setTextColor(getColor(R.color.pt_text))
                textSize = 20f
                gravity = Gravity.CENTER
            })
            addView(errorDetail)
            addView(Button(context).apply {
                id = R.id.error_retry
                text = getString(R.string.error_retry)
                setOnClickListener { load(prefs.url, force = true) }
            })
            addView(Button(context).apply {
                id = R.id.error_settings
                text = getString(R.string.error_settings)
                setOnClickListener { openSettings() }
            })
        }
        val match = FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
        root.addView(webView, match)
        root.addView(loading, match)
        root.addView(errorView, match)
        setContentView(root)

        // Bars are hidden, so only the camera cutout needs keeping clear.
        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val cut = insets.getInsets(WindowInsetsCompat.Type.displayCutout())
            view.setPadding(cut.left, cut.top, cut.right, cut.bottom)
            val bars = insets.isVisible(WindowInsetsCompat.Type.statusBars()) ||
                insets.isVisible(WindowInsetsCompat.Type.navigationBars())
            if (bars) ui.postDelayed({ hideSystemBars() }, 2500)
            Log.i(TAG, "insets statusBars=${insets.isVisible(WindowInsetsCompat.Type.statusBars())} " +
                "navigationBars=${insets.isVisible(WindowInsetsCompat.Type.navigationBars())} cutoutTop=${cut.top}")
            insets
        }
        root.addOnLayoutChangeListener { _, _, _, _, _, _, _, _, _ -> applyGestureGuard() }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun newWebView(): WebView = WebView(this).apply {
        id = R.id.shell_webview
        setBackgroundColor(Color.TRANSPARENT)
        overScrollMode = View.OVER_SCROLL_NEVER
        isHapticFeedbackEnabled = false
        settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            @Suppress("DEPRECATION")
            databaseEnabled = true
            cacheMode = WebSettings.LOAD_DEFAULT
            mediaPlaybackRequiresUserGesture = false
            loadWithOverviewMode = false
            useWideViewPort = true
            textZoom = 100  // the layout is tuned for the page's own sizes, not the system font scale
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false
            setSupportMultipleWindows(false)
            javaScriptCanOpenWindowsAutomatically = false
            allowFileAccess = false
            allowContentAccess = false
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            userAgentString = "$userAgentString PokeTacticsShell/${BuildConfig.VERSION_NAME}"
        }
        webViewClient = ShellClient()
        webChromeClient = ShellChrome()
        setDownloadListener { url, _, _, _, _ -> openExternal(url) }
    }

    // ------------------------------------------------------------------ loading
    private fun load(url: String, force: Boolean = false) {
        if (!force && url == loadedUrl && pageReady) return
        bindBridge(url)
        loadedUrl = url
        pageReady = false
        mainFrameFailed = false
        errorView.visibility = View.GONE
        loading.visibility = View.VISIBLE
        Log.i(TAG, "load $url")
        ui.removeCallbacks(connectWatchdog)
        ui.postDelayed(connectWatchdog, CONNECT_TIMEOUT_MS)
        webView.loadUrl(url)
    }

    /**
     * Native bridge for the configured game origin only (WebMessageListener, not
     * addJavascriptInterface: other origins never see it). Messages: {"type":"vibrate","pattern":[...]}.
     */
    private fun bindBridge(url: String) {
        val rule = originRule(url) ?: return
        if (rule == listenerOrigin || !WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) return
        if (listenerOrigin != null) WebViewCompat.removeWebMessageListener(webView, BRIDGE)
        WebViewCompat.addWebMessageListener(webView, BRIDGE, setOf(rule)) { _, message, _, _, _ ->
            handleMessage(message.data ?: return@addWebMessageListener)
        }
        listenerOrigin = rule
    }

    private fun handleMessage(data: String) {
        val json = runCatching { JSONObject(data) }.getOrNull() ?: return
        when (json.optString("type")) {
            "vibrate" -> {
                val raw = json.optJSONArray("pattern")
                val pattern = if (raw != null) LongArray(raw.length()) { raw.optLong(it) }
                              else longArrayOf(json.optLong("pattern", 30))
                if (vibes.play(pattern)) Log.i(TAG, "vibrate ${pattern.joinToString(",", "[", "]")}")
            }
        }
    }

    private fun showError(detail: String) {
        ui.removeCallbacks(connectWatchdog)
        mainFrameFailed = true
        pageReady = false
        loading.visibility = View.GONE
        errorDetail.text = "$detail\n${prefs.url}"
        errorView.visibility = View.VISIBLE
        Log.w(TAG, "error page: $detail")
    }

    // ------------------------------------------------------------------ back key / back swipe
    private fun onSystemBack() {
        if (exitDialog?.isShowing == true || backPending) return
        if (!pageReady) {
            Log.i(TAG, "back -> exit dialog (page not ready)")
            return showExitDialog()
        }
        backPending = true
        val timeout = Runnable {
            if (backPending) {
                backPending = false
                Log.i(TAG, "back -> exit dialog (page did not answer)")
                showExitDialog()
            }
        }
        ui.postDelayed(timeout, 1200)
        webView.evaluateJavascript(BACK_HOOK) { result ->
            if (!backPending) return@evaluateJavascript
            backPending = false
            ui.removeCallbacks(timeout)
            if (result == "true") {
                Log.i(TAG, "back -> page closed an overlay")
            } else {
                Log.i(TAG, "back -> exit dialog (page result $result)")
                showExitDialog()
            }
        }
    }

    private fun showExitDialog() {
        if (exitDialog?.isShowing == true) return
        val builder = AlertDialog.Builder(this, R.style.Theme_PokeTactics_Dialog)
            .setTitle(R.string.exit_title)
            .setMessage(R.string.exit_message)
            .setPositiveButton(R.string.exit_cancel) { dialog, _ -> dialog.dismiss() }
            .setNegativeButton(R.string.exit_confirm) { _, _ ->
                Log.i(TAG, "exit confirmed")
                finish()
            }
        if (offGamePage()) builder.setNeutralButton(R.string.exit_to_game) { _, _ -> load(prefs.url, force = true) }
        val dialog = builder.create()
        dialog.setOnDismissListener {
            Log.i(TAG, "exit dialog dismissed")
            hideSystemBars()
        }
        // Show without taking focus first so the bars stay hidden, then make it focusable.
        dialog.window?.setFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE, WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE)
        dialog.show()
        dialog.window?.let { w ->
            WindowCompat.getInsetsController(w, w.decorView).apply {
                hide(WindowInsetsCompat.Type.systemBars())
                systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            }
            w.clearFlags(WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE)
        }
        exitDialog = dialog
        Log.i(TAG, "exit dialog shown")
    }

    /** True when the page in view is not the configured game page (e.g. the site's 图鉴). */
    private fun offGamePage(): Boolean {
        val current = webView.url?.let(Uri::parse) ?: return false
        val game = Uri.parse(prefs.url)
        return current.path?.trimEnd('/') != game.path?.trimEnd('/') ||
            ShellPrefs.originOf(current.toString()) != ShellPrefs.originOf(prefs.url)
    }

    // ------------------------------------------------------------------ immersive full screen
    private fun hideSystemBars() {
        WindowCompat.getInsetsController(window, window.decorView).apply {
            systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            hide(WindowInsetsCompat.Type.systemBars())
        }
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) hideSystemBars()
    }

    private fun applyOrientation() {
        requestedOrientation = if (prefs.allowLandscape) ActivityInfo.SCREEN_ORIENTATION_FULL_USER
                               else ActivityInfo.SCREEN_ORIENTATION_PORTRAIT
    }

    /**
     * Optional edge guard: the middle band of the left/right edges (where the board and
     * the bench sit) does not start the system back swipe. Android caps it at 200dp per edge.
     */
    private fun applyGestureGuard() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) return
        val rects = mutableListOf<Rect>()
        if (prefs.gestureGuard && root.width > 0) {
            val insets = ViewCompat.getRootWindowInsets(root)?.getInsets(WindowInsetsCompat.Type.systemGestures())
            val left = maxOf(insets?.left ?: 0, dp(24))
            val right = maxOf(insets?.right ?: 0, dp(24))
            val band = min(dp(200), root.height)
            val top = (root.height - band) / 2
            rects += Rect(0, top, left, top + band)
            rects += Rect(root.width - right, top, root.width, top + band)
        }
        ViewCompat.setSystemGestureExclusionRects(root, rects)
    }

    // ------------------------------------------------------------------ hidden settings: two fingers held 2 s
    private var twoFingerStart: Pair<Float, Float>? = null
    private val openSettingsLater = Runnable {
        twoFingerStart = null
        Log.i(TAG, "settings via two-finger hold")
        openSettings()
    }

    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_POINTER_DOWN -> if (event.pointerCount == 2) {
                twoFingerStart = centroid(event)
                ui.postDelayed(openSettingsLater, 2000)
            } else cancelTwoFinger()
            MotionEvent.ACTION_MOVE -> twoFingerStart?.let { (x, y) ->
                val (cx, cy) = centroid(event)
                if (hypot(cx - x, cy - y) > dp(40)) cancelTwoFinger()
            }
            MotionEvent.ACTION_POINTER_UP, MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> cancelTwoFinger()
        }
        return super.dispatchTouchEvent(event)
    }

    private fun cancelTwoFinger() {
        twoFingerStart = null
        ui.removeCallbacks(openSettingsLater)
    }

    private fun centroid(event: MotionEvent): Pair<Float, Float> {
        var x = 0f
        var y = 0f
        for (i in 0 until event.pointerCount) { x += event.getX(i); y += event.getY(i) }
        return x / event.pointerCount to y / event.pointerCount
    }

    private fun openSettings() = startActivity(Intent(this, SettingsActivity::class.java))

    // ------------------------------------------------------------------ lifecycle
    override fun onResume() {
        super.onResume()
        webView.onResume()
        applyOrientation()
        hideSystemBars()
        applyGestureGuard()
        // Back from the settings page with a new address.
        if (loadedUrl != null && prefs.url != loadedUrl) load(prefs.url, force = true)
    }

    override fun onPause() {
        webView.onPause()
        super.onPause()
    }

    override fun onDestroy() {
        exitDialog?.dismiss()
        ui.removeCallbacksAndMessages(null)
        webView.destroy()
        super.onDestroy()
    }

    // ------------------------------------------------------------------ WebView clients
    private inner class ShellClient : WebViewClient() {
        override fun onPageStarted(view: WebView, url: String, favicon: Bitmap?) {
            mainFrameFailed = false
        }

        override fun onPageCommitVisible(view: WebView, url: String) {
            ui.removeCallbacks(connectWatchdog)  // the server answered; big assets may still load
        }

        override fun onPageFinished(view: WebView, url: String) {
            if (mainFrameFailed) return
            pageReady = true
            loading.visibility = View.GONE
            errorView.visibility = View.GONE
            Log.i(TAG, "page ready $url")
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
            if (request.isForMainFrame && !mainFrameFailed) showError("${error.description}（${error.errorCode}）")
        }

        override fun onReceivedHttpError(view: WebView, request: WebResourceRequest, response: WebResourceResponse) {
            if (request.isForMainFrame && response.statusCode >= 500) showError("HTTP ${response.statusCode}")
        }

        override fun onReceivedSslError(view: WebView, handler: SslErrorHandler, error: SslError) {
            // The network security config already trusts the bundled preview CA; this is
            // the fallback for WebView builds that do not consult it. Only that CA, only
            // the preview machine's addresses, only an otherwise valid certificate.
            if (error.primaryError == SslError.SSL_UNTRUSTED && trustedPreviewCert(error)) {
                Log.i(TAG, "ssl: preview CA accepted for ${error.url}")
                handler.proceed()
            } else {
                handler.cancel()
                if (error.url == view.url || error.url == loadedUrl) showError("证书不受信任（${error.primaryError}）")
            }
        }

        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            val url = request.url.toString()
            if (ShellPrefs.originOf(url) == ShellPrefs.originOf(prefs.url)) return false
            openExternal(url)
            return true
        }

        override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
            Log.w(TAG, "renderer gone (crash=${detail.didCrash()}); rebuilding the WebView")
            val index = root.indexOfChild(view)
            root.removeView(view)
            view.destroy()
            listenerOrigin = null
            webView = newWebView()
            root.addView(webView, index, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
            load(prefs.url, force = true)
            return true
        }
    }

    private inner class ShellChrome : WebChromeClient() {
        override fun onConsoleMessage(message: ConsoleMessage): Boolean {
            Log.d(TAG, "console ${message.messageLevel()} ${message.message()} (${message.sourceId()}:${message.lineNumber()})")
            return true
        }

        override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
            fileCallback?.onReceiveValue(null)
            fileCallback = callback
            return try {
                pickFile.launch(params.acceptTypes.firstOrNull { it.isNotBlank() } ?: "*/*")
                true
            } catch (_: ActivityNotFoundException) {
                fileCallback = null
                false
            }
        }
    }

    private fun trustedPreviewCert(error: SslError): Boolean {
        val host = Uri.parse(error.url).host ?: return false
        if (host !in BuildConfig.PREVIEW_HOSTS.split(',').map { it.trim() }) return false
        val ca = previewCa() ?: return false
        val leaf = x509Of(error.certificate) ?: return false
        return runCatching {
            leaf.checkValidity()
            leaf.verify(ca.publicKey)
            true
        }.getOrDefault(false)
    }

    private fun previewCa(): X509Certificate? {
        @SuppressLint("DiscouragedApi")
        val id = resources.getIdentifier("preview_ca", "raw", packageName)
        if (id == 0) return null
        return runCatching {
            resources.openRawResource(id).use {
                CertificateFactory.getInstance("X.509").generateCertificate(it) as X509Certificate
            }
        }.getOrNull()
    }

    private fun x509Of(cert: SslCertificate): X509Certificate? {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) return cert.x509Certificate
        val bytes = SslCertificate.saveState(cert).getByteArray("x509-certificate") ?: return null
        return runCatching {
            CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(bytes)) as X509Certificate
        }.getOrNull()
    }

    private fun openExternal(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (_: ActivityNotFoundException) {
            Log.w(TAG, "no app for $url")
        }
    }

    private fun dp(value: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value.toFloat(), resources.displayMetrics).toInt()

    companion object {
        const val TAG = "PokeTacticsShell"
        private const val BRIDGE = "PokeTacticsNative"
        private const val CONNECT_TIMEOUT_MS = 15_000L
        // "true": the page closed an overlay; "false"/"null": nothing to close / no hook.
        private const val BACK_HOOK =
            "(function(){try{var s=window.PokeTacticsShell;return s&&typeof s.onBack==='function'?!!s.onBack():null}catch(e){return null}})()"

        /** WebView origin rule: scheme://host[:port], the port only when not the default. */
        fun originRule(url: String): String? {
            val uri = Uri.parse(url)
            val scheme = uri.scheme?.lowercase() ?: return null
            val host = uri.host ?: return null
            if (scheme != "http" && scheme != "https") return null
            val defaultPort = if (scheme == "https") 443 else 80
            return if (uri.port == -1 || uri.port == defaultPort) "$scheme://$host" else "$scheme://$host:${uri.port}"
        }
    }
}
