package com.mypark.totem

import android.app.ActivityManager
import android.content.Context
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.view.WindowManager
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.EditText
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity

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

        private val URLS_PERMITIDAS = setOf(
            Config.URL_ENTRADA, Config.URL_SAIDA, Config.URL_VALIDACAO,
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_totem)
        ativarTelaCheia()

        // Testado no equipamento em 11/08/2026: o override do método
        // onBackPressed() antigo (deprecated) não estava consumindo o
        // botão voltar físico -- por isso o registro via
        // OnBackPressedCallback (API atual do androidx.activity), que de
        // fato intercepta o botão.
        //
        // Testado em 14/08/2026: o botão voltar deve encerrar o totem e
        // retornar à MainActivity, igual ao gesto de 5 toques
        // (sairDoQuiosque()) -- MainActivity.onResume() já exige login de
        // novo automaticamente, então isso não abre nenhum atalho de
        // segurança, só dá outra forma de sair além do gesto.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                sairDoQuiosque()
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
        val campoCaptura = findViewById<EditText>(R.id.campo_captura_nativa)
        androidBridge = AndroidBridge(this, webView, campoCaptura)
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

    override fun onDestroy() {
        super.onDestroy()
        androidBridge.liberarRecursos()
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
