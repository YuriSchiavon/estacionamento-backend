package com.mypark.totem

/**
 * URL base do backend (mesmo servidor do painel/operação/POS -- ver
 * README.md do repositório). Trocar aqui se o domínio mudar; nenhum
 * outro lugar do app precisa saber essa URL.
 */
object Config {
    const val BASE_URL = "https://www.patiomypark.com.br"

    const val URL_ENTRADA = "$BASE_URL/totem/entrada"
    const val URL_SAIDA = "$BASE_URL/totem/saida"
    const val URL_VALIDACAO = "$BASE_URL/totem/validacao"
}
