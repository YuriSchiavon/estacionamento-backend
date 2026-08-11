package com.mypark.totem

import android.Manifest
import android.app.ActivityManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.view.WindowManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject

/**
 * Tela real do totem: WebView em tela cheia carregando uma das 3 URLs
 * de totem, sem chrome de navegador, em modo quiosque (Lock Task Mode).
 * Nenhuma navegação escapa das 3 URLs conhecidas -- ver
 * shouldOverrideUrlLoading abaixo, é essa checagem nativa (não uma regra
 * em JavaScript) que garante que este app nunca alcança
 * home/gestão/operação/POS.
 */
class TotemActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var androidBridge: AndroidBridge
    private var toquesSaida = 0
    private val handler = Handler(Looper.getMainLooper())
    private val resetToques = Runnable { toquesSaida = 0 }

    companion object {
        const val EXTRA_URL = "extra_url"
        private const val JANELA_GESTO_SAIDA_MS = 3000L
        private const val TOQUES_PARA_SAIR = 5
        private const val REQUEST_CODE_CAMERA = 100

        private val URLS_PERMITIDAS = setOf(
            Config.URL_ENTRADA, Config.URL_SAIDA, Config.URL_VALIDACAO,
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_totem)
        ativarTelaCheia()
        pedirPermissaoCameraSeNecessario()

        // Testado no equipamento em 11/08/2026: o override do método
        // onBackPressed() antigo (deprecated) NÃO estava consumindo o
        // botão voltar físico -- o app caía de volta pra tela de login.
        // Registrar um OnBackPressedCallback (API atual do
        // androidx.activity) é a forma correta e garante que o botão
        // voltar não faça nada aqui, como já era a intenção.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                // no-op de propósito -- ver docstring da classe
            }
        })

        val url = intent.getStringExtra(EXTRA_URL) ?: Config.URL_ENTRADA

        webView = findViewById(R.id.webview)
        with(webView.settings) {
            javaScriptEnabled = true
            // Essencial -- os totens guardam a sessão de login (até 90
            // dias) em localStorage (ver CHAVE_SESSAO em
            // app/static/totem_*.html); sem DOM storage o app pediria
            // login toda vez que abrisse.
            domStorageEnabled = true
            setSupportZoom(false)
            builtInZoomControls = false
            displayZoomControls = false
        }
        androidBridge = AndroidBridge(this, webView)
        webView.addJavascriptInterface(androidBridge, "AndroidBridge")
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // Só deixa navegar dentro das 3 URLs de totem -- qualquer
                // outro destino (ex: o link "início" que as páginas
                // mostram quando ninguém está logado) é simplesmente
                // ignorado, sem navegar. Compara sem query string, já
                // que a URL inicial agora carrega token/unidade nos
                // parâmetros (ver MainActivity.abrirTotem()).
                val semQuery = request.url.buildUpon().clearQuery().build().toString()
                return semQuery !in URLS_PERMITIDAS
            }
        }
        webView.loadUrl(url)

        findViewById<View>(R.id.area_saida_quiosque).setOnClickListener { registrarToqueSaida() }
    }

    override fun onResume() {
        super.onResume()
        entrarEmModoQuiosque()
    }

    override fun onPause() {
        super.onPause()
        // Nunca deixa a câmera do leitor ligada se a tela sair de foco
        // por qualquer motivo -- mesmo cuidado do onDestroy() do exemplo
        // oficial da Gertec (ver AndroidBridge.pararLeitura).
        androidBridge.pararLeitura()
    }

    override fun onDestroy() {
        super.onDestroy()
        androidBridge.liberarRecursos()
    }

    // Resultado da leitura do scanner (CodeScanner.scanCode() da SDK
    // EasyLayer entrega o código lido via onActivityResult, não como
    // retorno direto -- ver AndroidBridge.iniciarLeitura()). Repassa o
    // texto lido pra página web via receberCodigoLido(), que cada
    // página de totem que aceita leitura já define (ver
    // app/static/totem_saida.html e totem_validacao.html).
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data == null) return
        val conteudo = data.getStringExtra("content")
        if (conteudo.isNullOrBlank()) return

        androidBridge.notificarLeituraRecebida()
        val chamada = "if (window.receberCodigoLido) { window.receberCodigoLido(${JSONObject.quote(conteudo)}); }"
        webView.evaluateJavascript(chamada) { }
        Log.i("TotemActivity", "Código lido repassado pra página")
    }

    /**
     * O leitor (EasyLayer/CodeScanner) usa a câmera -- é permissão
     * "perigosa" (Android 6+), precisa ser concedida em tempo de
     * execução, não só declarada no manifesto. O exemplo oficial da
     * Gertec não pede isso manualmente (a tela de captura deles
     * provavelmente já cuida disso sozinha, já que é baseada na
     * biblioteca zxing-android-embedded, que tem esse tratamento
     * embutido) -- pedimos aqui também, cedo, só por garantia: não
     * custa nada se já tiver sido concedida, e evita a câmera falhar
     * silenciosamente na primeira leitura se não tiver.
     */
    private fun pedirPermissaoCameraSeNecessario() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED
        ) {
            ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.CAMERA), REQUEST_CODE_CAMERA)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == REQUEST_CODE_CAMERA) {
            val concedida = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
            Log.i("TotemActivity", "Permissão de câmera: ${if (concedida) "concedida" else "negada"}")
            // Testado ao vivo: numa instalação nova, a página costuma pedir
            // pra escanear antes desse diálogo ser respondido -- essa
            // chamada retoma a leitura que ficou pendente (ver
            // AndroidBridge.iniciarLeitura()/retomarLeituraSePendente()).
            if (concedida) androidBridge.retomarLeituraSePendente()
        }
    }

    @Suppress("DEPRECATION")
    private fun ativarTelaCheia() {
        window.decorView.systemUiVisibility = (
            View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                or View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                or View.SYSTEM_UI_FLAG_FULLSCREEN
            )
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    /**
     * Fixa a tela (Lock Task Mode) -- mesmo mecanismo do "Fixar app"
     * manual que o README já documentava (Segurança → Fixar app), só
     * que automático ao entrar aqui: ninguém sai pro launcher/
     * notificações sem passar pelo gesto de 5 toques (ver
     * registrarToqueSaida). Funciona sem precisar cadastrar o app como
     * Device Owner; dependendo do fabricante/versão o Android pode
     * pedir uma confirmação na primeira vez.
     */
    private fun entrarEmModoQuiosque() {
        val activityManager = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        if (activityManager.lockTaskModeState == ActivityManager.LOCK_TASK_MODE_NONE) {
            try {
                startLockTask()
            } catch (e: Exception) {
                // Alguns fabricantes recusam startLockTask() sem Device
                // Owner configurado -- não trava o app por causa disso,
                // só não fica preso na tela até isso ser resolvido.
            }
        }
    }

    private fun registrarToqueSaida() {
        toquesSaida++
        handler.removeCallbacks(resetToques)
        if (toquesSaida >= TOQUES_PARA_SAIR) {
            toquesSaida = 0
            sairDoQuiosque()
        } else {
            handler.postDelayed(resetToques, JANELA_GESTO_SAIDA_MS)
        }
    }

    private fun sairDoQuiosque() {
        val activityManager = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        if (activityManager.lockTaskModeState != ActivityManager.LOCK_TASK_MODE_NONE) {
            try { stopLockTask() } catch (e: Exception) { }
        }
        finish()
    }
}
