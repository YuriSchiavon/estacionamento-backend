package com.mypark.totem

import android.app.Activity
import android.speech.tts.TextToSpeech
import java.util.Locale

/**
 * Áudio via TextToSpeech nativo, sem depender de WebView/JS -- mesma
 * ideia que já existia em AndroidBridge.tocarBoasVindas(), só
 * reaproveitável direto pelas telas nativas de totem. Pré-aquece no
 * construtor (ver comentário histórico em AndroidBridge.kt sobre o
 * atraso de ~4s na primeira fala se o TextToSpeech só for criado na
 * hora de falar).
 */
class Locutor(activity: Activity) {

    private var tts: TextToSpeech? = null

    init {
        tts = TextToSpeech(activity) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale("pt", "BR")
            }
        }
    }

    fun falar(texto: String) {
        try {
            tts?.speak(texto, TextToSpeech.QUEUE_FLUSH, null, texto)
        } catch (e: Exception) { /* áudio não é essencial -- silencioso */ }
    }

    fun liberar() {
        tts?.stop()
        tts?.shutdown()
        tts = null
    }
}
