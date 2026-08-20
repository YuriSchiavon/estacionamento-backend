package com.mypark.totem

import android.app.ActivityManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.InputType
import android.text.TextWatcher
import android.view.KeyEvent
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import org.json.JSONObject
import java.util.Locale

/**
 * Tela nativa do totem de Saída -- substitui totem_saida.html + WebView
 * (ver TotemActivity, mantido por enquanto só para Entrada/Validação
 * até essas também ganharem versão nativa). Sem WebView, o leitor
 * físico ("Scanner como teclado") escreve direto nos EditText normais,
 * sem nenhuma das gambiarras que o WebView exigia (perda de teclas em
 * rajada rápida, teclado virtual subindo sozinho) -- só
 * showSoftInputOnFocus=false nos campos que são só pra leitura.
 *
 * Login e escolha de unidade já aconteceram em MainActivity antes de
 * chegar aqui (ver Sessao) -- essa tela não tem mais "trocar
 * conta"/"trocar unidade" no rodapé; sair (gesto de 5 toques ou botão
 * voltar) sempre volta pro login nativo, igual TotemActivity.
 */
class SaidaActivity : AppCompatActivity() {

    private lateinit var sessao: Sessao
    private lateinit var impressora: Impressora
    private lateinit var locutor: Locutor

    private lateinit var paginaTicket: View
    private lateinit var paginaResultado: View
    private lateinit var paginaValidar: View
    private lateinit var paginaPagamento: View
    private lateinit var paginaPix: View

    private val handler = Handler(Looper.getMainLooper())
    private var toquesSaida = 0
    private val resetToques = Runnable { toquesSaida = 0 }

    private var codigoAtual: String? = null
    private var ultimaVerificacao: JSONObject? = null
    private var chaveCupomPendente: String? = null
    private var cobrancaPixId: Int? = null

    private var debounceTicket: Runnable? = null
    private var debounceQr: Runnable? = null
    private var timeoutAutoReset: Runnable? = null
    private var pollingPix: Runnable? = null

    companion object {
        private const val JANELA_GESTO_SAIDA_MS = 3000L
        private const val TOQUES_PARA_SAIR = 5
        private const val ATRASO_RESET_MS = 8000L
        private const val DEBOUNCE_LEITURA_MS = 400L
        private const val INTERVALO_POLL_PIX_MS = 3000L
        private val NOMES_FORMA_PAGAMENTO = mapOf("pix" to "PIX", "credito" to "Crédito", "debito" to "Débito")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_saida)
        ativarTelaCheia()
        sessao = Sessao.lerDe(intent)
        impressora = Impressora(this) { mensagem -> mostrarErroNaPaginaAtual(mensagem) }
        locutor = Locutor(this)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() { sairDoQuiosque() }
        })

        paginaTicket = findViewById(R.id.pagina_ticket)
        paginaResultado = findViewById(R.id.pagina_resultado)
        paginaValidar = findViewById(R.id.pagina_validar)
        paginaPagamento = findViewById(R.id.pagina_pagamento)
        paginaPix = findViewById(R.id.pagina_pix)

        findViewById<View>(R.id.area_saida_quiosque).setOnClickListener { registrarToqueSaida() }

        configurarPaginaTicket()
        configurarPaginaResultado()
        configurarPaginaValidar()
        configurarPaginaPagamento()
        configurarPaginaPix()

        mostrarPagina(paginaTicket)
    }

    override fun onResume() {
        super.onResume()
        entrarEmModoQuiosque()
    }

    override fun onDestroy() {
        super.onDestroy()
        pararPollingPix()
        locutor.liberar()
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

    private fun entrarEmModoQuiosque() {
        val activityManager = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        if (activityManager.lockTaskModeState == ActivityManager.LOCK_TASK_MODE_NONE) {
            try { startLockTask() } catch (e: Exception) { /* sem Device Owner, segue sem travar */ }
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

    // -----------------------------------------------------------------
    // Troca de tela -- equivalente nativo de mostrarPagina() em
    // totem_saida.html. Cada página cuida de limpar/focar seus próprios
    // campos ao aparecer.
    // -----------------------------------------------------------------
    private fun mostrarPagina(pagina: View) {
        timeoutAutoReset?.let { handler.removeCallbacks(it) }
        timeoutAutoReset = null
        if (pagina !== paginaPix) pararPollingPix()
        listOf(paginaTicket, paginaResultado, paginaValidar, paginaPagamento, paginaPix).forEach {
            it.visibility = if (it === pagina) View.VISIBLE else View.GONE
        }
        when (pagina) {
            paginaTicket -> {
                val campo = findViewById<EditText>(R.id.campo_ticket)
                campo.setText("")
                campo.requestFocus()
            }
            paginaValidar -> {
                findViewById<EditText>(R.id.campo_qr).setText("")
                findViewById<View>(R.id.erro_validar).visibility = View.GONE
                findViewById<View>(R.id.valor_manual_wrap).visibility = View.GONE
                chaveCupomPendente = null
                findViewById<EditText>(R.id.campo_qr).requestFocus()
            }
        }
    }

    private fun focoSemTeclado(campo: EditText) {
        campo.showSoftInputOnFocus = false
    }

    private fun mostrarErroNaPaginaAtual(mensagem: String) {
        val idErro = when {
            paginaTicket.visibility == View.VISIBLE -> R.id.erro_ticket
            paginaValidar.visibility == View.VISIBLE -> R.id.erro_validar
            paginaPagamento.visibility == View.VISIBLE -> R.id.erro_pagamento
            paginaPix.visibility == View.VISIBLE -> R.id.erro_pix
            else -> return
        }
        findViewById<TextView>(idErro).apply {
            text = mensagem
            visibility = View.VISIBLE
        }
    }

    // -----------------------------------------------------------------
    // Passo 1: ticket
    // -----------------------------------------------------------------
    private fun configurarPaginaTicket() {
        val campo = findViewById<EditText>(R.id.campo_ticket)
        focoSemTeclado(campo)
        val botao = findViewById<Button>(R.id.btn_verificar_ticket)
        botao.setOnClickListener { disparaVerificacaoTicket() }
        campo.setOnEditorActionListener { _, actionId, evento ->
            if (actionId == EditorInfo.IME_ACTION_DONE || (evento?.keyCode == KeyEvent.KEYCODE_ENTER && evento.action == KeyEvent.ACTION_DOWN)) {
                disparaVerificacaoTicket()
                true
            } else false
        }
        // Verificação automática -- o leitor digita o código sem
        // necessariamente mandar Enter no final; debounce de 400ms
        // dispara sozinho assim que o campo para de mudar.
        campo.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                debounceTicket?.let { handler.removeCallbacks(it) }
                if (s.isNullOrBlank()) return
                val runnable = Runnable { disparaVerificacaoTicket() }
                debounceTicket = runnable
                handler.postDelayed(runnable, DEBOUNCE_LEITURA_MS)
            }
        })
    }

    private fun disparaVerificacaoTicket() {
        val codigo = findViewById<EditText>(R.id.campo_ticket).text.toString().trim()
        if (codigo.isBlank()) return
        debounceTicket?.let { handler.removeCallbacks(it) }
        val botao = findViewById<Button>(R.id.btn_verificar_ticket)
        botao.isEnabled = false
        findViewById<View>(R.id.erro_ticket).visibility = View.GONE
        Thread {
            try {
                val resposta = Api.get(
                    "/saida/verificar/${Uri.encode(codigo)}?unidade_id=${sessao.unidadeId}", sessao.token,
                )
                val r = JSONObject(resposta)
                runOnUiThread {
                    exibirResultado(r)
                    // Só recebe quem "bem-vindo" quando a interação vai
                    // continuar (precisa validar cupom/pagar) -- numa
                    // liberação imediata (isento), exibirResultado()
                    // já dispara "Volte sempre", e falar as duas coisas
                    // quase juntas cortava uma por cima da outra.
                    if (!r.optBoolean("liberar_cancela", false)) {
                        locutor.falar("Seja bem-vindo")
                    }
                    botao.isEnabled = true
                }
            } catch (e: ApiException) {
                runOnUiThread {
                    val erro = JSONObject().apply {
                        put("codigo_barras", codigo)
                        put("liberar_cancela", false)
                        put("motivo", e.message)
                        put("tempo_permanencia_minutos", 0)
                        put("valor_calculado", 0.0)
                    }
                    exibirResultado(erro, semDetalhesDeTempo = true)
                    locutor.falar("Ticket não encontrado")
                    botao.isEnabled = true
                }
            }
        }.start()
    }

    // -----------------------------------------------------------------
    // Passo 2: resultado
    // -----------------------------------------------------------------
    private fun configurarPaginaResultado() {
        findViewById<Button>(R.id.btn_novo_ticket).setOnClickListener { mostrarPagina(paginaTicket) }
        findViewById<Button>(R.id.btn_ir_pagamento).setOnClickListener {
            irParaPagamento(ultimaVerificacao?.optDouble("valor_calculado", 0.0) ?: 0.0)
        }
        findViewById<Button>(R.id.btn_ir_validar).setOnClickListener { mostrarPagina(paginaValidar) }
    }

    private fun exibirResultado(r: JSONObject, semDetalhesDeTempo: Boolean = false) {
        codigoAtual = r.optString("codigo_barras")
        ultimaVerificacao = r
        val liberado = r.optBoolean("liberar_cancela", false)

        val caixa = findViewById<View>(R.id.caixa_resultado)
        caixa.setBackgroundResource(if (liberado) R.drawable.bg_resultado_ok else R.drawable.bg_resultado_err)
        val status = findViewById<TextView>(R.id.resultado_status)
        status.text = if (liberado) "CANCELA LIBERADA" else "AGUARDANDO"
        status.setTextColor(getColor(if (liberado) R.color.ok_claro else R.color.danger_claro))
        findViewById<TextView>(R.id.resultado_motivo).text = r.optString("motivo")

        val linhaPermanencia = findViewById<View>(R.id.linha_permanencia)
        if (semDetalhesDeTempo) {
            linhaPermanencia.visibility = View.GONE
        } else {
            linhaPermanencia.visibility = View.VISIBLE
            findViewById<TextView>(R.id.resultado_permanencia).text =
                "${r.optInt("tempo_permanencia_minutos")} min"
        }

        val valorCalculado = r.optDouble("valor_calculado", 0.0)
        val linhaValor = findViewById<View>(R.id.linha_valor)
        if (!semDetalhesDeTempo && valorCalculado > 0) {
            linhaValor.visibility = View.VISIBLE
            findViewById<TextView>(R.id.resultado_valor).text = formatarReais(valorCalculado)
        } else {
            linhaValor.visibility = View.GONE
        }

        findViewById<View>(R.id.acoes_fallback).visibility = if (!liberado && !semDetalhesDeTempo) View.VISIBLE else View.GONE
        findViewById<Button>(R.id.btn_novo_ticket).text = if (liberado) "Concluir" else "Cancelar"
        mostrarPagina(paginaResultado)

        if (liberado) {
            // Único lugar que fala "Volte sempre" -- cobre liberação
            // isenta (direto na primeira leitura do ticket), depois de
            // validar cupom e depois de pagar, todas de uma vez, sem
            // duplicar a chamada em cada um desses fluxos.
            locutor.falar("Volte sempre")
            val runnable = Runnable { mostrarPagina(paginaTicket) }
            timeoutAutoReset = runnable
            handler.postDelayed(runnable, ATRASO_RESET_MS)
        }
    }

    private fun verificarSaidaEExibir(codigo: String, aoConcluir: (JSONObject) -> Unit) {
        Thread {
            try {
                val resposta = Api.get("/saida/verificar/${Uri.encode(codigo)}?unidade_id=${sessao.unidadeId}", sessao.token)
                val r = JSONObject(resposta)
                runOnUiThread {
                    exibirResultado(r)
                    aoConcluir(r)
                }
            } catch (e: ApiException) {
                runOnUiThread { mostrarErroNaPaginaAtual(e.message ?: "Erro desconhecido") }
            }
        }.start()
    }

    // -----------------------------------------------------------------
    // Passo 3: validar cupom fiscal
    // -----------------------------------------------------------------
    private fun configurarPaginaValidar() {
        val campo = findViewById<EditText>(R.id.campo_qr)
        focoSemTeclado(campo)
        findViewById<Button>(R.id.btn_voltar_validar).setOnClickListener { mostrarPagina(paginaResultado) }
        campo.setOnEditorActionListener { _, _, evento ->
            if (evento?.keyCode == KeyEvent.KEYCODE_ENTER && evento.action == KeyEvent.ACTION_DOWN) {
                processarLeituraCupom()
                true
            } else false
        }
        campo.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) {
                debounceQr?.let { handler.removeCallbacks(it) }
                if (s.isNullOrBlank()) return
                val runnable = Runnable { processarLeituraCupom() }
                debounceQr = runnable
                handler.postDelayed(runnable, DEBOUNCE_LEITURA_MS)
            }
        })

        findViewById<EditText>(R.id.campo_valor_manual).inputType =
            InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        findViewById<Button>(R.id.btn_confirmar_valor_manual).setOnClickListener {
            val erro = findViewById<TextView>(R.id.erro_validar)
            val valorTexto = findViewById<EditText>(R.id.campo_valor_manual).text.toString()
            val valor = valorTexto.replace(",", ".").toDoubleOrNull()
            if (valor == null || valor <= 0) {
                erro.text = "Informe um valor válido."
                erro.visibility = View.VISIBLE
                return@setOnClickListener
            }
            val chave = chaveCupomPendente ?: return@setOnClickListener
            findViewById<View>(R.id.valor_manual_wrap).visibility = View.GONE
            validarCupomComValor(chave, valor)
        }
    }

    /** Extrai chave de acesso (44 dígitos) e valor da compra do texto lido
     * pelo leitor. Layout "nacional" de QR de NFC-e é uma URL com
     * chNFe/vNF nos parâmetros; alguns estados (ex: MG) não embutem o
     * valor -- nesse caso `valor` volta null e a tela pede pro operador
     * digitar (ver validarCupomComValor / botão confirmar-valor-manual). */
    private fun lerCupomFiscal(textoLido: String): Pair<String?, Double?> {
        var chave: String? = null
        var valor: Double? = null
        try {
            val uri = Uri.parse(textoLido)
            if (uri.scheme != null) {
                chave = uri.getQueryParameter("chNFe") ?: uri.getQueryParameter("chave")
                val vRaw = uri.getQueryParameter("vNF") ?: uri.getQueryParameter("valor") ?: uri.getQueryParameter("valorTotal")
                valor = vRaw?.toDoubleOrNull()
            }
        } catch (e: Exception) { /* não é uma URL -- tenta como chave crua abaixo */ }
        if (chave == null) {
            val soDigitos = textoLido.filter { it.isDigit() }
            if (soDigitos.length == 44) chave = soDigitos
        }
        return chave to valor
    }

    private fun processarLeituraCupom() {
        val campo = findViewById<EditText>(R.id.campo_qr)
        val texto = campo.text.toString().trim()
        if (texto.isBlank()) return
        val erro = findViewById<TextView>(R.id.erro_validar)
        erro.visibility = View.GONE
        val (chave, valor) = lerCupomFiscal(texto)
        if (chave == null) {
            erro.text = "Não foi possível ler os dados do cupom. Tente novamente."
            erro.visibility = View.VISIBLE
            campo.setText("")
            locutor.falar("Não foi possível ler o cupom")
            return
        }
        if (valor == null) {
            chaveCupomPendente = chave
            findViewById<View>(R.id.valor_manual_wrap).visibility = View.VISIBLE
            findViewById<EditText>(R.id.campo_valor_manual).apply { setText(""); requestFocus() }
            return
        }
        validarCupomComValor(chave, valor)
    }

    private fun validarCupomComValor(chave: String, valor: Double) {
        val erro = findViewById<TextView>(R.id.erro_validar)
        val codigo = codigoAtual ?: return
        Thread {
            try {
                Api.post(
                    "/loja/validar-cupom", sessao.token,
                    JSONObject().apply {
                        put("codigo_barras", codigo)
                        put("chave_acesso_nfce", chave)
                        put("valor_compra", valor)
                        put("unidade_id", sessao.unidadeId)
                    },
                )
                runOnUiThread {
                    chaveCupomPendente = null
                    findViewById<View>(R.id.valor_manual_wrap).visibility = View.GONE
                }
                verificarSaidaEExibir(codigo) { r ->
                    val valorCalculado = r.optDouble("valor_calculado", 0.0)
                    if (!r.optBoolean("liberar_cancela", false) && valorCalculado > 0) {
                        irParaPagamento(valorCalculado)
                    }
                }
            } catch (e: ApiException) {
                runOnUiThread {
                    erro.text = e.message
                    erro.visibility = View.VISIBLE
                    findViewById<EditText>(R.id.campo_qr).setText("")
                    locutor.falar("Cupom inválido")
                }
            }
        }.start()
    }

    // -----------------------------------------------------------------
    // Passo 4: pagamento
    // -----------------------------------------------------------------
    private fun irParaPagamento(valor: Double) {
        findViewById<TextView>(R.id.pagamento_titulo).text = "Valor a pagar: ${formatarReais(valor)}"
        findViewById<View>(R.id.erro_pagamento).visibility = View.GONE
        mostrarPagina(paginaPagamento)
    }

    private fun configurarPaginaPagamento() {
        findViewById<Button>(R.id.btn_voltar_pagamento).setOnClickListener { mostrarPagina(paginaResultado) }
        // PIX de verdade (Pagar.me) tem um passo a mais -- gerar a
        // cobrança e mostrar o QR, em vez de já sair marcando como pago
        // (ver iniciarPagamentoPix). Crédito/débito continuam confiando
        // no totem confirmar (pago num POS à parte), igual sempre foi.
        findViewById<View>(R.id.btn_forma_pix).setOnClickListener { iniciarPagamentoPix() }
        findViewById<View>(R.id.btn_forma_credito).setOnClickListener { processarPagamento("credito") }
        findViewById<View>(R.id.btn_forma_debito).setOnClickListener { processarPagamento("debito") }
    }

    private fun botoesFormaPagamento() = listOf(R.id.btn_forma_pix, R.id.btn_forma_credito, R.id.btn_forma_debito)
        .map { findViewById<View>(it) }

    private fun processarPagamento(forma: String) {
        val codigo = codigoAtual ?: return
        val erro = findViewById<TextView>(R.id.erro_pagamento)
        erro.visibility = View.GONE
        botoesFormaPagamento().forEach { it.isEnabled = false }
        val valor = ultimaVerificacao?.optDouble("valor_calculado", 0.0) ?: 0.0
        Thread {
            try {
                Api.post(
                    "/saida/pagamento", sessao.token,
                    JSONObject().apply {
                        put("codigo_barras", codigo)
                        put("forma_pagamento", forma)
                        put("valor", valor)
                        put("unidade_id", sessao.unidadeId)
                    },
                )
                // "Volte sempre" sai de exibirResultado() quando
                // verificarSaidaEExibir() confirmar liberar_cancela=true
                // logo abaixo -- não repete aqui.
                runOnUiThread { imprimirComprovante(codigo, valor, forma) }
                verificarSaidaEExibir(codigo) { botoesFormaPagamento().forEach { it.isEnabled = true } }
            } catch (e: ApiException) {
                runOnUiThread {
                    erro.text = e.message
                    erro.visibility = View.VISIBLE
                    botoesFormaPagamento().forEach { it.isEnabled = true }
                    locutor.falar("Não foi possível concluir o pagamento")
                }
            }
        }.start()
    }

    private fun imprimirComprovante(codigo: String, valor: Double, forma: String) {
        val horario = java.text.SimpleDateFormat("dd/MM/yyyy HH:mm", Locale("pt", "BR")).format(java.util.Date())
        impressora.texto("MY PARK")
        impressora.texto(codigo)
        impressora.texto("Valor pago: ${formatarReais(valor)}")
        impressora.texto("Forma: ${NOMES_FORMA_PAGAMENTO[forma] ?: forma}")
        impressora.texto(horario)
        impressora.codigo(codigo)
        impressora.avancarPapel()
        impressora.cortar()
    }

    private fun formatarReais(valor: Double): String =
        "R$ " + String.format(Locale("pt", "BR"), "%.2f", valor)

    // -----------------------------------------------------------------
    // Passo 5: PIX de verdade (Pagar.me) -- cria a cobrança, mostra o QR
    // e fica consultando o status até a Pagar.me confirmar. Ver
    // app/pagarme.py no backend; sem PAGARME_API_KEY configurada, a
    // criação falha com uma mensagem clara em vez de fingir que
    // funcionou (ver erro_pagamento abaixo).
    // -----------------------------------------------------------------
    private fun configurarPaginaPix() {
        findViewById<Button>(R.id.btn_cancelar_pix).setOnClickListener {
            pararPollingPix()
            mostrarPagina(paginaPagamento)
        }
    }

    private fun iniciarPagamentoPix() {
        val codigo = codigoAtual ?: return
        val valor = ultimaVerificacao?.optDouble("valor_calculado", 0.0) ?: 0.0
        val erroPagamento = findViewById<TextView>(R.id.erro_pagamento)
        erroPagamento.visibility = View.GONE
        botoesFormaPagamento().forEach { it.isEnabled = false }
        Thread {
            try {
                val resposta = Api.post(
                    "/saida/pagamento-pix", sessao.token,
                    JSONObject().apply {
                        put("codigo_barras", codigo)
                        put("valor", valor)
                        put("unidade_id", sessao.unidadeId)
                    },
                )
                val cobranca = JSONObject(resposta)
                runOnUiThread {
                    botoesFormaPagamento().forEach { it.isEnabled = true }
                    abrirTelaPix(cobranca, valor)
                }
            } catch (e: ApiException) {
                runOnUiThread {
                    botoesFormaPagamento().forEach { it.isEnabled = true }
                    erroPagamento.text = e.message
                    erroPagamento.visibility = View.VISIBLE
                }
            }
        }.start()
    }

    private fun abrirTelaPix(cobranca: JSONObject, valor: Double) {
        cobrancaPixId = cobranca.optInt("id")
        val qrTexto = cobranca.optString("qr_code_texto")
        findViewById<TextView>(R.id.pix_valor).text = formatarReais(valor)
        findViewById<TextView>(R.id.pix_status).text = "Aguardando pagamento..."
        findViewById<View>(R.id.erro_pix).visibility = View.GONE
        findViewById<ImageView>(R.id.pix_qr_imagem).setImageBitmap(
            if (qrTexto.isNotBlank()) gerarBitmapQr(qrTexto, 600) else null,
        )
        mostrarPagina(paginaPix)
        arPollingPix()
    }

    private fun gerarBitmapQr(texto: String, tamanhoPx: Int): Bitmap {
        val matriz = QRCodeWriter().encode(texto, BarcodeFormat.QR_CODE, tamanhoPx, tamanhoPx)
        val bitmap = Bitmap.createBitmap(tamanhoPx, tamanhoPx, Bitmap.Config.RGB_565)
        for (x in 0 until tamanhoPx) {
            for (y in 0 until tamanhoPx) {
                bitmap.setPixel(x, y, if (matriz.get(x, y)) Color.BLACK else Color.WHITE)
            }
        }
        return bitmap
    }

    private fun arPollingPix() {
        pararPollingPix()
        val runnable = object : Runnable {
            override fun run() {
                consultarStatusPix()
                handler.postDelayed(this, INTERVALO_POLL_PIX_MS)
            }
        }
        pollingPix = runnable
        handler.postDelayed(runnable, INTERVALO_POLL_PIX_MS)
    }

    private fun pararPollingPix() {
        pollingPix?.let { handler.removeCallbacks(it) }
        pollingPix = null
    }

    private fun consultarStatusPix() {
        val id = cobrancaPixId ?: return
        Thread {
            try {
                val resposta = Api.get("/saida/pagamento-pix/$id/status", sessao.token)
                val cobranca = JSONObject(resposta)
                runOnUiThread { tratarStatusPix(cobranca) }
            } catch (e: ApiException) {
                // Silencioso -- falha pontual de rede não deve incomodar
                // quem está esperando o QR com uma mensagem de erro; só
                // tenta de novo no próximo ciclo.
            }
        }.start()
    }

    private fun tratarStatusPix(cobranca: JSONObject) {
        when (cobranca.optString("status")) {
            "pago" -> {
                pararPollingPix()
                val codigo = codigoAtual ?: return
                val valor = ultimaVerificacao?.optDouble("valor_calculado", 0.0) ?: 0.0
                imprimirComprovante(codigo, valor, "pix")
                // "Volte sempre" sai de exibirResultado() logo abaixo.
                verificarSaidaEExibir(codigo) { }
            }
            "expirado" -> {
                pararPollingPix()
                findViewById<TextView>(R.id.pix_status).text = "QR code expirado"
                findViewById<TextView>(R.id.erro_pix).apply {
                    text = "O tempo pra pagar esse QR code acabou. Volte e tente de novo."
                    visibility = View.VISIBLE
                }
                locutor.falar("QR code expirado")
            }
            // "pendente" -- continua esperando, sem fazer nada.
        }
    }
}
