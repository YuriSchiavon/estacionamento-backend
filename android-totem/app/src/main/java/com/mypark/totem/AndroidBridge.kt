package com.mypark.totem

import android.app.Activity
import android.speech.tts.TextToSpeech
import android.util.Log
import android.webkit.JavascriptInterface
import android.webkit.WebView
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
 * chamam os métodos abaixo no lugar de `window.print()` quando essa
 * ponte existe.
 *
 * Impressora: br.com.gertec.gdk.printer.* (SDK "GerSDK Varejo", AAR em
 * app/libs/GerSDKVarejo_1_0_3.aar) -- essa parte segue de perto o
 * exemplo oficial da Gertec ("Micro exemplo de impressão com WebView -
 * GERSDK") e funciona (impressora testada e confirmada ao vivo).
 *
 * Leitor: NÃO passa por aqui. Testado no equipamento em 14/08/2026 --
 * o SK210 tem um app de sistema dedicado (`com.android.scanneraskeyboard`,
 * ativável em Configurações > Sistema > Idiomas e entrada > "Scanner
 * como teclado") que injeta o código lido como se fosse digitação de
 * teclado físico, direto no campo de texto em foco. Isso deixou toda a
 * integração via AIDL (com.topwise.cloudpos.aidl.camera.*) que estava
 * aqui antes desnecessária -- removida. Ver TotemActivity para a
 * checagem/tentativa de manter esse app de sistema ativo.
 */
class AndroidBridge(private val activity: Activity, private val webView: WebView) : Printer.Listener {

    private val TAG = "AndroidBridge"

    private val printer: Printer = Printer.getInstance(activity, this)
    private var tts: TextToSpeech? = null

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
     * antes os erros de impressão só iam pro Logcat (`Log.e`), então se
     * algo falhava o operador via "nada acontecer", sem saber se era
     * falha real ou se só precisava esperar. As páginas de totem definem
     * `window.receberErroNativo(mensagem)` pra exibir isso.
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
        tts?.stop()
        tts?.shutdown()
        tts = null
    }
}
