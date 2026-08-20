package com.mypark.totem

import android.content.Intent

/**
 * Sessão resolvida pelo login nativo (MainActivity), entregue de uma
 * vez só pra tela de totem escolhida via extras do Intent -- substitui
 * o esquema antigo de embutir tudo isso numa URL pro WebView ler de
 * `location.search` (ver git history de MainActivity.abrirTotem()).
 */
data class Sessao(
    val token: String,
    val papel: String,
    val nome: String,
    val podeLiberarManualmente: Boolean,
    var unidadeId: Int,
    var unidadeNome: String,
) {
    fun salvarEm(intent: Intent) {
        intent.putExtra(EXTRA_TOKEN, token)
        intent.putExtra(EXTRA_PAPEL, papel)
        intent.putExtra(EXTRA_NOME, nome)
        intent.putExtra(EXTRA_PODE_LIBERAR, podeLiberarManualmente)
        intent.putExtra(EXTRA_UNIDADE_ID, unidadeId)
        intent.putExtra(EXTRA_UNIDADE_NOME, unidadeNome)
    }

    companion object {
        private const val EXTRA_TOKEN = "sessao_token"
        private const val EXTRA_PAPEL = "sessao_papel"
        private const val EXTRA_NOME = "sessao_nome"
        private const val EXTRA_PODE_LIBERAR = "sessao_pode_liberar"
        private const val EXTRA_UNIDADE_ID = "sessao_unidade_id"
        private const val EXTRA_UNIDADE_NOME = "sessao_unidade_nome"

        fun lerDe(intent: Intent): Sessao = Sessao(
            token = intent.getStringExtra(EXTRA_TOKEN) ?: "",
            papel = intent.getStringExtra(EXTRA_PAPEL) ?: "",
            nome = intent.getStringExtra(EXTRA_NOME) ?: "",
            podeLiberarManualmente = intent.getBooleanExtra(EXTRA_PODE_LIBERAR, false),
            unidadeId = intent.getIntExtra(EXTRA_UNIDADE_ID, 0),
            unidadeNome = intent.getStringExtra(EXTRA_UNIDADE_NOME) ?: "",
        )
    }
}
