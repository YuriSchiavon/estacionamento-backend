package com.mypark.totem

import android.content.Intent
import android.os.Bundle
import android.text.InputType
import android.text.method.HideReturnsTransformationMethod
import android.text.method.PasswordTransformationMethod
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ImageButton
import android.widget.LinearLayout
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Tela de escolha do equipamento -- só existem 3 destinos possíveis
 * (Entrada / Saída / Validação), e só ficam disponíveis depois de
 * logar. O login é feito aqui, nativamente (não dentro da WebView) --
 * é essa restrição nativa, e não uma regra em JavaScript, que garante
 * que este app nunca alcança gestão/operação/POS.
 *
 * A sessão (token + unidade resolvida) fica só em memória nesta
 * Activity -- nunca salva em disco. Toda vez que essa tela reaparece
 * (voltando de um totem via o gesto de 5 toques em TotemActivity), o
 * login é exigido de novo -- ver onResume().
 */
class MainActivity : AppCompatActivity() {

    // Sessão em memória -- limpa a cada vez que a tela de login reaparece.
    private var token: String? = null
    private var papel: String? = null
    private var nome: String? = null
    private var podeLiberarManualmente: Boolean = false
    private var unidadeOperacionalId: Int? = null
    private var unidadeOperacionalNome: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        findViewById<Button>(R.id.btn_login).setOnClickListener { tentarLogin() }
        findViewById<ImageButton>(R.id.btn_toggle_senha).setOnClickListener { alternarVisibilidadeSenha() }
        // Cards de escolha (Entrada/Saída/Validação) -- não são mais
        // Button, e sim um LinearLayout clicável (ver activity_main.xml),
        // pra caber ícone grande em cima e texto pequeno embaixo.
        findViewById<View>(R.id.btn_entrada).setOnClickListener { abrirTotem(Config.URL_ENTRADA) }
        // Saída já foi reescrita 100% nativa (ver SaidaActivity) -- não
        // passa mais por WebView. Entrada/Validação seguem pelo caminho
        // antigo até também ganharem versão nativa.
        findViewById<View>(R.id.btn_saida).setOnClickListener { abrirSaidaNativa() }
        findViewById<View>(R.id.btn_validacao).setOnClickListener { abrirTotem(Config.URL_VALIDACAO) }

        // Esta é a raiz da tarefa (não existe tela anterior dentro do
        // app) -- o botão voltar aqui NUNCA deve fechar o app e cair no
        // launcher do Android, mesmo sem estar em Lock Task Mode. Como
        // esta tela não alcança gestão/operação/POS (só login e escolha
        // de totem), não há nenhum risco em simplesmente ignorar o
        // gesto.
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                // no-op de propósito
            }
        })
    }

    override fun onResume() {
        super.onResume()
        // Sempre que esta tela volta a aparecer (cold start ou retorno de
        // TotemActivity via o gesto de 5 toques), zera a sessão e mostra
        // o login de novo -- "a única forma de sair [de um totem] é
        // retomar a tela com as opções novamente e com usuário e senha".
        limparSessao()
        mostrarTela("login")
    }

    private fun limparSessao() {
        token = null
        papel = null
        nome = null
        podeLiberarManualmente = false
        unidadeOperacionalId = null
        unidadeOperacionalNome = null
        val campoSenha = findViewById<EditText>(R.id.login_senha)
        campoSenha.setText("")
        campoSenha.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        campoSenha.transformationMethod = PasswordTransformationMethod.getInstance()
        findViewById<ImageButton>(R.id.btn_toggle_senha).setImageResource(R.drawable.ic_olho)
    }

    // Alterna o campo de senha entre oculto e visível (ícone de olho).
    //
    // Testado no equipamento em 14/08/2026: a versão antiga só mudava o
    // inputType (TYPE_TEXT_VARIATION_VISIBLE_PASSWORD) e confiava que o
    // Android trocaria o TransformationMethod sozinho -- na prática,
    // nessa ROM (ver comentário grande de AndroidBridge.kt sobre o
    // firmware da Topwise por trás do SK210), isso não bastou e a senha
    // continuava mascarada mesmo com o ícone mudando. Setar o
    // transformationMethod diretamente é o mecanismo que de fato
    // controla se os caracteres aparecem ou viram •••, então é o que
    // decide a visibilidade aqui -- o inputType continua sendo ajustado
    // só para o teclado não tentar sugestão/autocorreção com a senha à
    // mostra.
    private fun alternarVisibilidadeSenha() {
        val campo = findViewById<EditText>(R.id.login_senha)
        val botao = findViewById<ImageButton>(R.id.btn_toggle_senha)
        val selecaoAtual = campo.selectionStart.coerceAtLeast(0)
        val oculta = campo.transformationMethod is PasswordTransformationMethod
        if (oculta) {
            campo.transformationMethod = HideReturnsTransformationMethod.getInstance()
            campo.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD
            botao.setImageResource(R.drawable.ic_olho_fechado)
            botao.contentDescription = getString(R.string.ocultar_senha)
        } else {
            campo.transformationMethod = PasswordTransformationMethod.getInstance()
            campo.inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            botao.setImageResource(R.drawable.ic_olho)
            botao.contentDescription = getString(R.string.mostrar_senha)
        }
        campo.setSelection(selecaoAtual)
    }

    private fun mostrarTela(tela: String) {
        findViewById<View>(R.id.tela_login).visibility = if (tela == "login") View.VISIBLE else View.GONE
        findViewById<View>(R.id.tela_selecao_unidade).visibility = if (tela == "selecao") View.VISIBLE else View.GONE
        findViewById<View>(R.id.tela_picker).visibility = if (tela == "picker") View.VISIBLE else View.GONE
    }

    private fun mostrarErroLogin(mensagem: String) {
        val erro = findViewById<TextView>(R.id.login_erro)
        erro.text = mensagem
        erro.visibility = View.VISIBLE
    }

    // -----------------------------------------------------------------
    // Login -- POST /auth/login nativamente (sem passar pela WebView).
    // Mesma API que app/static/totem_*.html já usa.
    // -----------------------------------------------------------------
    private fun tentarLogin() {
        val usuario = findViewById<EditText>(R.id.login_usuario).text.toString()
        val senha = findViewById<EditText>(R.id.login_senha).text.toString()
        findViewById<TextView>(R.id.login_erro).visibility = View.GONE
        if (usuario.isBlank() || senha.isBlank()) {
            mostrarErroLogin("Preencha usuário e senha")
            return
        }

        Thread {
            try {
                val conn = URL("${Config.BASE_URL}/auth/login").openConnection() as HttpURLConnection
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.connectTimeout = 15000
                conn.readTimeout = 15000
                val corpo = JSONObject().apply {
                    put("username", usuario)
                    put("senha", senha)
                }.toString()
                conn.outputStream.use { it.write(corpo.toByteArray(Charsets.UTF_8)) }

                val codigo = conn.responseCode
                val texto = (if (codigo in 200..299) conn.inputStream else conn.errorStream)
                    .bufferedReader().use { it.readText() }
                val json = JSONObject(texto)

                runOnUiThread {
                    if (codigo in 200..299) {
                        token = json.getString("token")
                        papel = json.getString("papel")
                        nome = json.getString("nome")
                        podeLiberarManualmente = json.optBoolean("pode_liberar_manualmente", false)
                        resolverUnidade(forcarSelecao = false)
                    } else {
                        mostrarErroLogin(json.optString("detail", "Usuário ou senha inválidos"))
                    }
                }
            } catch (e: Exception) {
                runOnUiThread { mostrarErroLogin("Erro de conexão: ${e.message}") }
            }
        }.start()
    }

    // -----------------------------------------------------------------
    // Resolve em qual unidade este login vai operar -- mesma lógica que
    // resolverUnidadeOperacional() já usa em app/static/operacao.html:
    // 0 unidades bloqueia, 1 segue direto, mais de uma pede pra escolher.
    // -----------------------------------------------------------------
    private fun resolverUnidade(forcarSelecao: Boolean) {
        val tokenAtual = token ?: return
        Thread {
            try {
                val conn = URL("${Config.BASE_URL}/auth/minhas-unidades").openConnection() as HttpURLConnection
                conn.requestMethod = "GET"
                conn.setRequestProperty("Authorization", "Bearer $tokenAtual")
                conn.connectTimeout = 15000
                conn.readTimeout = 15000

                val codigo = conn.responseCode
                if (codigo == 401) {
                    runOnUiThread {
                        limparSessao()
                        mostrarErroLogin("Sessão inválida, tente entrar de novo")
                        mostrarTela("login")
                    }
                    return@Thread
                }
                val texto = conn.inputStream.bufferedReader().use { it.readText() }
                val unidades = JSONArray(texto)

                runOnUiThread {
                    if (unidades.length() == 0) {
                        limparSessao()
                        mostrarErroLogin("Sua conta não tem nenhuma unidade disponível")
                        mostrarTela("login")
                        return@runOnUiThread
                    }
                    if (unidades.length() == 1) {
                        val u = unidades.getJSONObject(0)
                        unidadeOperacionalId = u.getInt("id")
                        unidadeOperacionalNome = u.getString("nome")
                        mostrarTela("picker")
                        return@runOnUiThread
                    }
                    montarSelecaoUnidade(unidades)
                }
            } catch (e: Exception) {
                runOnUiThread { mostrarErroLogin("Erro ao carregar unidades: ${e.message}") }
            }
        }.start()
    }

    private fun montarSelecaoUnidade(unidades: JSONArray) {
        val lista = findViewById<LinearLayout>(R.id.lista_unidades)
        lista.removeAllViews()
        for (i in 0 until unidades.length()) {
            val u = unidades.getJSONObject(i)
            val id = u.getInt("id")
            val nomeUnidade = u.getString("nome")
            val botao = Button(this).apply {
                text = nomeUnidade
                setTextColor(resources.getColor(R.color.texto_claro, theme))
                background = resources.getDrawable(R.drawable.bg_botao_secundario, theme)
                setPadding(32, 32, 32, 32)
                setOnClickListener {
                    unidadeOperacionalId = id
                    unidadeOperacionalNome = nomeUnidade
                    mostrarTela("picker")
                }
            }
            val params = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
            params.bottomMargin = 24
            lista.addView(botao, params)
        }
        mostrarTela("selecao")
    }

    // -----------------------------------------------------------------
    // Abre o totem escolhido, já com a sessão embutida na URL (query
    // params) -- assim a WebView não precisa pedir login de novo. Ver
    // carregarSessao() em app/static/totem_*.html, que lê esses mesmos
    // parâmetros antes de cair no login próprio da página.
    // -----------------------------------------------------------------
    private fun abrirTotem(baseUrl: String) {
        val t = token ?: return
        val unidadeId = unidadeOperacionalId ?: return
        val enc = { s: String? -> URLEncoder.encode(s ?: "", "UTF-8") }
        val url = "$baseUrl?token=${enc(t)}&papel=${enc(papel)}&nome=${enc(nome)}" +
            "&pode_liberar_manualmente=$podeLiberarManualmente" +
            "&unidade_operacional_id=$unidadeId&unidade_operacional_nome=${enc(unidadeOperacionalNome)}"
        val intent = Intent(this, TotemActivity::class.java)
        intent.putExtra(TotemActivity.EXTRA_URL, url)
        startActivity(intent)
    }

    // Igual abrirTotem() acima, mas pra tela nativa (sem WebView, sem
    // URL) -- a sessão vai direto como extras do Intent, ver Sessao.kt.
    private fun abrirSaidaNativa() {
        val t = token ?: return
        val unidadeId = unidadeOperacionalId ?: return
        val sessao = Sessao(
            token = t,
            papel = papel ?: "",
            nome = nome ?: "",
            podeLiberarManualmente = podeLiberarManualmente,
            unidadeId = unidadeId,
            unidadeNome = unidadeOperacionalNome ?: "",
        )
        val intent = Intent(this, SaidaActivity::class.java)
        sessao.salvarEm(intent)
        startActivity(intent)
    }
}
