package com.mypark.totem

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

/**
 * Tela de escolha do equipamento: só existem 3 destinos possíveis
 * (Entrada / Saída / Validação) -- é essa restrição nativa, e não uma
 * regra em JavaScript, que garante que este app nunca alcança
 * gestão/operação/POS. TotemActivity entra em modo quiosque sozinha ao
 * abrir; o gesto de 5 toques no canto (ver TotemActivity) volta pra cá.
 */
class MainActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        findViewById<android.widget.Button>(R.id.btn_entrada).setOnClickListener {
            abrirTotem(Config.URL_ENTRADA)
        }
        findViewById<android.widget.Button>(R.id.btn_saida).setOnClickListener {
            abrirTotem(Config.URL_SAIDA)
        }
        findViewById<android.widget.Button>(R.id.btn_validacao).setOnClickListener {
            abrirTotem(Config.URL_VALIDACAO)
        }
    }

    private fun abrirTotem(url: String) {
        val intent = Intent(this, TotemActivity::class.java)
        intent.putExtra(TotemActivity.EXTRA_URL, url)
        startActivity(intent)
    }
}
