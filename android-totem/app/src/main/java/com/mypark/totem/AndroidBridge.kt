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
import br.com.gertec.gdk.printer.Alignment
import br.com.gertec.gdk.printer.BarcodeFormat
import br.com.gertec.gdk.printer.BarcodeType
import br.com.gertec.gdk.printer.CutType
import br.com.gertec.gdk.printer.Printer
import br.com.gertec.gdk.printer.PrinterError
import br.com.gertec.gdk.printer.TextFormat
import com.topwise.cloudpos.aidl.camera.AidlCameraScanCode
import com.topwise.cloudpos.aidl.camera.AidlDecodeCallBack
import com.topwise.cloudpos.aidl.camera.DecodeMode
import com.topwise.cloudpos.aidl.camera.DecodeParameter
import com.topwise.cloudpos.service.DeviceServiceManager
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
 * app/libs/GerSDKVarejo_1_0_3.aar) -- essa parte segue de perto o
 * exemplo oficial da Gertec ("Micro exemplo de impressão com WebView -
 * GERSDK") e funciona (impressora testada e confirmada ao vivo).
 *
 * Leitor: fala DIRETO com o serviço de sistema da Topwise (fabricante do
 * hardware por trás do SK210) via com.topwise.cloudpos.aidl.camera.* --
 * ver o bloco de comentário grande logo antes de dispararLeitura() pra
 * entender por que a gente não usa mais o wrapper CodeScanner/Scanner da
 * SDK EasyLayer da Gertec pra isso.
 */
class AndroidBridge(private val activity: Activity, private val webView: WebView) : Printer.Listener {

    private val TAG = "AndroidBridge"
    private val TIMEOUT_WATCHDOG_MS = 5000L

    private val printer: Printer = Printer.getInstance(activity, this)
    private var tts: TextToSpeech? = null
    private val handler = Handler(Looper.getMainLooper())
    private val deviceServiceManager = DeviceServiceManager.getInstance()
    private var cameraManager: AidlCameraScanCode? = null

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
        try {
            deviceServiceManager.init(activity)
            cameraManager = deviceServiceManager.getCameraManager()
            Log.i(TAG, "cameraManager inicializado: ${cameraManager != null}")
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao inicializar o gerenciador de câmera da Topwise", e)
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
    // JS via receberCodigoLido(), definido em cada página de totem que
    // aceita leitura. pararLeitura() é chamada ao trocar de tela (ver
    // mostrarPagina() nas páginas) e no onPause da activity, pra nunca
    // deixar a câmera ligada à toa.
    //
    // HISTÓRICO DA INVESTIGAÇÃO (decompilado o .aar em 11/08/2026,
    // EasyLayer v219): a princípio usávamos CodeScanner/Scanner (a SDK
    // "EasyLayer" da Gertec). Achamos e corrigimos um bug real ali
    // (scanCode(activity) nunca inicializava o campo scanConfig,
    // NullPointerException garantida) -- mas mesmo depois de corrigir
    // isso, o leitor continuou "ligando" (câmera/luz ativa, piscando)
    // sem nunca decodificar nada. Cavando mais fundo, achamos por quê
    // dessa vez é praticamente impossível saber COM CERTEZA sem decompilar
    // de novo: o callback interno da EasyLayer (Scanner$1) trata erro de
    // decodificação (onError) mostrando só um Toast do Android que a
    // gente não tem nenhuma forma de interceptar, e o código de retorno
    // de startDecode() (que indicaria se o pedido foi aceito ou recusado)
    // é descartado (`pop` logo depois da chamada, no bytecode) -- ou
    // seja, mesmo com o NPE corrigido, continuávamos sem nenhuma
    // visibilidade real do que estava de fato acontecendo internamente.
    //
    // Por isso agora pulamos o wrapper EasyLayer inteiro pro leitor e
    // falamos direto com o serviço de sistema da própria Topwise
    // (fabricante do hardware por trás do SK210) via
    // com.topwise.cloudpos.aidl.camera.* -- são classes públicas que já
    // vêm dentro do próprio .aar da EasyLayer (libs/TOPSDK_*.jar), não é
    // dependência nova. Com nosso próprio AidlDecodeCallBack, onError()
    // e o código de retorno de startDecode() finalmente aparecem de
    // verdade na tela via avisarErroNaPagina(), em vez de sumirem num
    // Toast que ninguém vê.
    // ---------------------------------------------------------------

    // Nomes EXATOS que o decodificador da Topwise espera (achados
    // decompilando Scanner.allCodes/getCodes -- não são os mesmos nomes
    // que a EasyLayer expõe como constantes públicas, tipo "QR_CODE").
    // "QR CODE" cobre tanto o próprio ticket (impresso como QR, ver
    // printCode() acima) quanto o QR da nota fiscal na tela de
    // validação; o resto cobre os formatos 1D mais comuns, por garantia.
    private val tiposCodigoSuportados = listOf(
        "QR CODE", "AZTEC", "DATA MATRIX", "MAXICODE", "PDF417",
        "C128", "C39", "C93", "EAN-13", "EAN-8", "I25", "Codabar",
        "UPC-A", "UPC-E", "GS1 DATABAR",
    )

    private val callbackLeitura = object : AidlDecodeCallBack.Stub() {
        override fun onResult(resultado: String?) {
            // Roda numa thread de Binder, não na UI -- nunca mexer na
            // WebView direto aqui fora do runOnUiThread.
            if (resultado.isNullOrBlank()) return
            Log.i(TAG, "onResult do leitor: código lido")
            activity.runOnUiThread {
                notificarLeituraRecebida()
                val chamada = "if (window.receberCodigoLido) { window.receberCodigoLido(${JSONObject.quote(resultado)}); }"
                webView.evaluateJavascript(chamada) { }
            }
        }

        override fun onError(codigoErro: Int) {
            // Esse é exatamente o retorno que a EasyLayer engolia num
            // Toast interno inacessível -- agora chega de verdade na tela.
            Log.e(TAG, "onError do leitor: código=$codigoErro")
            avisarErroNaPagina("Erro do leitor (código $codigoErro)")
        }

        override fun onPreview(dados: ByteArray?, largura: Int, altura: Int) {
            // Sem preview visual na tela -- só precisamos do resultado
            // decodificado, não da imagem crua da câmera.
        }
    }

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
                // Câmera ainda não foi liberada -- chamar startDecode() aqui
                // sempre falhava silenciosamente nesse caso. Marca a
                // leitura como pendente; TotemActivity retoma sozinha via
                // retomarLeituraSePendente() assim que a permissão for
                // concedida (ver onRequestPermissionsResult).
                leituraPendenteAposPermissao = true
                Log.w(TAG, "Leitura pedida sem permissão de câmera ainda -- aguardando")
                return@runOnUiThread
            }
            leituraPendenteAposPermissao = false
            dispararLeitura()
        }
    }

    private fun dispararLeitura() {
        val camera = cameraManager
        if (camera == null) {
            Log.e(TAG, "cameraManager é nulo -- getCameraManager() da Topwise não retornou instância")
            avisarErroNaPagina("Leitor indisponível (gerenciador de câmera não inicializou)")
            return
        }
        val parametro = DecodeParameter().apply {
            setDecodeMode(DecodeMode.MODE_CONTINUE_SCAN_CODE)
            setDecodeIntervalTime(200)
            setDecodeSingleTimeout(10000)
            setFlashLightTimeout(0)
            setAutoDetect(1)
            setSupportCodeTypeList(tiposCodigoSuportados)
            setNoSupportCodeTypeList(emptyList())
        }
        try {
            camera.setDecodeLibrary(0)
            val codigoRetorno = camera.startDecode(parametro, callbackLeitura)
            if (codigoRetorno != 0) {
                Log.e(TAG, "startDecode retornou código $codigoRetorno (esperado 0)")
                avisarErroNaPagina("Leitor recusou iniciar (código $codigoRetorno)")
                return
            }
            leituraAguardandoResultado = true
            handler.removeCallbacks(watchdogLeitura)
            handler.postDelayed(watchdogLeitura, TIMEOUT_WATCHDOG_MS)
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao iniciar leitura", e)
            avisarErroNaPagina("Erro ao ligar o leitor: ${e.message}")
        }
    }

    private fun reiniciarLeituraSilenciosa() {
        try {
            cameraManager?.stopDecode()
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao parar leitura antes de reiniciar", e)
        }
        dispararLeitura()
    }

    /** Chamada por TotemActivity quando a permissão de câmera acaba de ser concedida. */
    fun retomarLeituraSePendente() {
        if (leituraPendenteAposPermissao) {
            iniciarLeitura()
        }
    }

    /** Desarma o watchdog assim que um código chega (ver callbackLeitura.onResult). */
    private fun notificarLeituraRecebida() {
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
                cameraManager?.stopDecode()
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
        try {
            cameraManager?.stopDecode()
        } catch (e: Exception) { /* já estamos saindo, não importa */ }
        tts?.stop()
        tts?.shutdown()
        tts = null
    }
}
