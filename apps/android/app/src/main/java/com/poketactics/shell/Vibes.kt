package com.poketactics.shell

import android.content.Context
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager

/** navigator.vibrate-style patterns ([on, off, on, …] in ms) on the native Vibrator. */
class Vibes(context: Context) {
    private val vibrator: Vibrator? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            (context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager)?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }

    fun play(pattern: LongArray): Boolean {
        val v = vibrator ?: return false
        if (!v.hasVibrator()) return false
        val steps = pattern.take(MAX_STEPS).map { it.coerceIn(0, MAX_STEP_MS) }
        if (steps.isEmpty() || steps.all { it == 0L }) {
            v.cancel()
            return false
        }
        // Android waveforms start with an "off" step; the web pattern starts with "on".
        val timings = (listOf(0L) + steps).toLongArray()
        v.vibrate(VibrationEffect.createWaveform(timings, -1))
        return true
    }

    companion object {
        private const val MAX_STEPS = 16
        private const val MAX_STEP_MS = 1000L
    }
}
