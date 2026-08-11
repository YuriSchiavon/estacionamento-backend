package com.mypark.totem

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
import androidx.core.content.ContextCompat
import br.com.gertec.easylayer.codescanner.CodeScanner
import br.com.gertec.gdk.printer.Alignment
import br.com.gertec.gdk.printer.BarcodeFormat
import br.com.gertec.gdk.printer.BarcodeType
import br.com.gertec.gdk.printer.CutType
import br.com.gertec.gdk.printer.Printer
import br.com.gertec.gdk.printer.PrinterError
import br.com.gertec.gdk.printer.TextFormat
import org.json.JSONObject
import java.util.Locale

/**
 * Ponte entre o JavaScript das páginas de totem e o Android nativo.
 * Exposta na WebView como `window.AndroidBridge` (ver
 * TotemActivity.onCreate) -- as páginas em app/static/totem_*.html
 * chamam os métodos abaixo no lugar de `window.print()`/leitura manual
 * quando essa ponte existe.
 *
 * Impressora: br.com.gertec.gdk.printer.* (SDK "GerSDK Varejo", AAR em
 * app/libs/GerSDKVarejo_1_0_3.aar). Leitor: br.com.gertec.easylayer.
 * codescanner.CodeScanner (SDK "EasyLayer", AAR em
 * app/libs/EasyLayer_SK210_v219_release.aar). Ambos baixados do portal
 * de desenvolvedor da Gertec (gertec.atlassian.net) a partir dos
 * exemplos oficiais "Micro exemplo de impressão com WebView - GERSDK" e
 * "Micro exemplo Scanner - SK210" -- a assinatura dos métodos abaixo
 * segue esses exemplos de perto de propósito, em vez de uma API
 * inventada, pra reduzir risco de divergir do que a Gertec testou.
 */
class AndroidBridge(private val activity: Activity, private val webView: WebView) : Printer.Listener {

    private val TAG = "AndroidBridge"
    private val TIMEOUT_WATCHDOG_MS = 5000L

    private val printer: Printer = Printer.getInstance(activity, this)
    private val codeScanner: CodeScanner = CodeScanner.getInstance(activity)
    private var tts: TextToSpeech? = null
    private val handler = Handler(Looper.getMainLooper())

    // Testado no equipamento em 11/08/2026: o áudio de boas-vindas saía
    // uns 4s atrasado, porque o TextToSpeech só era criado na primeira
    // chamada de tocarBoasVindas() -- bem no momento em que o ticket
    // acabou de sair, quando a inicialização do engine (que não é
    // instantânea) já é o gargalo. Pré-aquece aqui, assim que a ponte é
    // criada (bem antes de qualquer ticket ser emitido), pra já estar
    // pronto na hora.
    init {
        tts = TextToSpeech(activity) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale("pt", "BR")
            }
        }
    }

    /**
     * Repassa uma mensagem de erro pra página web mostrar na tela --
     * antes os erros de impressão/leitura só iam pro Logcat (`Log.e`),
     * então se algo falhava o operador via "nada acontecer", sem saber
     * se era falha real ou se só precisava esperar. As páginas de totem
     * definem `window.receberErroNativo(mensagem)` pra exibir isso.
     */
    private fun avisarErroNaPagina(mensagem: String) {
        val chamada = "if (window.receberErroNativo) { window.receberErroNativo(${JSONObject.quote(mensagem)}); }"
        activity.runOnUiThread { webView.evaluateJavascript(chamada) { } }
    }

    // ---------------------------------------------------------------
    // Impressora -- cada chamada do JS corresponde a uma ação da GerSDK.
    // As páginas de totem chamam essas em sequência (texto, texto,
    // código, scrollPaper, cutPaper) pra montar o ticket/comprovante
    // inteiro -- ver chamarImpressao() em app/static/totem_*.html.
    // ---------------------------------------------------------------

    @JavascriptInterface
    fun printText(texto: String) {
        activity.runOnUiThread {
            try {
                val formato = TextFormat()
                formato.setBold(false)
                formato.setFontSize(28)
                formato.setAlignment(Alignment.CENTER)
                printer.printText(formato, texto)
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao imprimir texto", e)
            }
        }
    }

    @JavascriptInterface
    fun printCode(conteudo: String) {
        activity.runOnUiThread {
            try {
                val qr = BarcodeFormat(BarcodeType.QR_CODE)
                printer.printBarcode(qr, conteudo)
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao imprimir código", e)
            }
        }
    }

    @JavascriptInterface
    fun scrollPaper() {
        activity.runOnUiThread {
            try {
                // Testado no equipamento em 11/08/2026: com scrollPaper(20) o
                // corte saía colado no QR code, sem nenhuma margem (a SDK não
                // documenta a unidade). 80 é uma estimativa pra ~1cm supondo
                // 203dpi/8 dots-mm (padrão comum de impressora térmica de
                // recibo) -- conferir no próximo teste físico e ajustar esse
                // número se ainda não bater 1cm de sobra antes do corte.
                printer.scrollPaper(80)
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao avançar papel", e)
            }
        }
    }

    @JavascriptInterface
    fun cutPaper() {
        activity.runOnUiThread {
            try {
                printer.cutPaper(CutType.PAPER_PARTIAL_CUT)
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao cortar papel", e)
            }
        }
    }

    override fun onPrinterError(printerError: PrinterError) {
        Log.e(TAG, "Erro na impressora: $printerError")
        avisarErroNaPagina("Erro na impressora: $printerError")
    }

    override fun onPrinterSuccessful(codigo: Int) {
        Log.i(TAG, "Impressão concluída: $codigo")
    }

    // ---------------------------------------------------------------
    // Leitor -- NÃO funciona como teclado (testado e confirmado): as
    // páginas precisam pedir ativamente pra escanear. iniciarLeitura()
    // liga a câmera/leitor em modo contínuo; cada código lido volta pro
    // JS via TotemActivity.onActivityResult -> receberCodigoLido(),
    // definido em cada página de totem que aceita leitura. pararLeitura()
    // é chamada ao trocar de tela (ver mostrarPagina() nas páginas) e no
    // onPause da activity, pra nunca deixar a câmera ligada à toa.
    //
    // Testado ao vivo no SK210 em 11/08/2026: o leitor acendia a luz mas
    // nunca lia nada. Investigando o bytecode da EasyLayer, o scanCode()
    // desse aparelho passa por com.topwise.cloudpos.service.
    // DeviceServiceManager -- um bind com um serviço do sistema que
    // provavelmente é assíncrono. Duas corridas plausíveis explicam o
    // sintoma: (1) scanCode() sendo chamado antes da permissão de câmera
    // ter sido concedida (comum bem na instalação nova do app, com o
    // diálogo do Android ainda pendente -- ver checagem abaixo) e (2)
    // scanCode() chamado antes desse bind interno terminar, ficando
    // "preso" sem decodificar (ver watchdog abaixo).
    // ---------------------------------------------------------------

    private var leituraPendenteAposPermissao = false
    private var leituraAguardandoResultado = false
    private val watchdogLeitura = Runnable {
        if (leituraAguardandoResultado) {
            Log.w(TAG, "Nenhuma leitura em ${TIMEOUT_WATCHDOG_MS}ms -- reiniciando o leitor")
            reiniciarLeituraSilenciosa()
        }
    }

    @JavascriptInterface
    fun iniciarLeitura() {
        activity.runOnUiThread {
            if (ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED
            ) {
                // Câmera ainda não foi liberada -- chamar scanCode() aqui
                // sempre falhava silenciosamente nesse caso. Marca a
                // leitura como pendente; TotemActivity retoma sozinha via
                // retomarLeituraSePendente() assim que a permissão for
                // concedida (ver onRequestPermissionsResult).
                leituraPendenteAposPermissao = true
                Log.w(TAG, "Leitura pedida sem permissão de câmera ainda -- aguardando")
                return@runOnUiThread
            }
            leituraPendenteAposPermissao = false
            try {
                codeScanner.scanCode(activity)
                leituraAguardandoResultado = true
                handler.removeCallbacks(watchdogLeitura)
                handler.postDelayed(watchdogLeitura, TIMEOUT_WATCHDOG_MS)
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao iniciar leitura", e)
                avisarErroNaPagina("Erro ao ligar o leitor: ${e.message}")
            }
        }
    }

    private fun reiniciarLeituraSilenciosa() {
        try {
            codeScanner.stopService()
            codeScanner.scanCode(activity)
            handler.postDelayed(watchdogLeitura, TIMEOUT_WATCHDOG_MS)
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao reiniciar leitura", e)
        }
    }

    /** Chamada por TotemActivity quando a permissão de câmera acaba de ser concedida. */
    fun retomarLeituraSePendente() {
        if (leituraPendenteAposPermissao) {
            iniciarLeitura()
        }
    }

    /** Chamada por TotemActivity.onActivityResult assim que um código chega -- desarma o watchdog. */
    fun notificarLeituraRecebida() {
        leituraAguardandoResultado = false
        handler.removeCallbacks(watchdogLeitura)
    }

    @JavascriptInterface
    fun pararLeitura() {
        activity.runOnUiThread {
            leituraPendenteAposPermissao = false
            leituraAguardandoResultado = false
            handler.removeCallbacks(watchdogLeitura)
            try {
                codeScanner.stopService()
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao parar leitura", e)
            }
        }
    }

    // ---------------------------------------------------------------
    // Áudio de boas-vindas -- toca via TextToSpeech nativo do Android
    // (sem precisar de nenhum arquivo de áudio embutido). Chamado pela
    // página de totem_entrada.html assim que o ticket é emitido com
    // sucesso.
    // ---------------------------------------------------------------
    @JavascriptInterface
    fun tocarBoasVindas() {
        activity.runOnUiThread {
            try {
                tts?.speak("Seja bem-vindo", TextToSpeech.QUEUE_FLUSH, null, "boas-vindas")
            } catch (e: Exception) {
                Log.e(TAG, "Erro ao tocar áudio de boas-vindas", e)
            }
        }
    }

    fun liberarRecursos() {
        handler.removeCallbacksAndMessages(null)
        tts?.stop()
        tts?.shutdown()
        tts = null
    }
}
