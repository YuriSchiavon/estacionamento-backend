package com.mypark.totem

import android.app.Activity
import android.content.Context
import android.print.PrintAttributes
import android.print.PrintManager
import android.webkit.JavascriptInterface
import android.webkit.WebView

/**
 * Ponte entre o JavaScript das páginas de totem e o Android nativo.
 * Exposta na WebView como `window.AndroidBridge` (ver
 * TotemActivity.onCreate) -- as páginas em app/static/totem_*.html
 * chamam `AndroidBridge.imprimir(...)` no lugar de `window.print()`
 * quando essa ponte existe (ver hook em imprimirTicket()/
 * imprimirComprovante()).
 */
class AndroidBridge(private val activity: Activity, private val webView: WebView) {

    /**
     * `dadosJson` é reservado pra quando a impressão real (SDK da
     * Gertec) entrar -- ver README.md, seção "Tablets Android como
     * totem". Por enquanto, a impressão usa o próprio conteúdo já
     * renderizado da WebView: a página já populou a div
     * `#area-impressao` com os dados do ticket/comprovante antes de
     * chamar isso (mesma função que antes chamava só `window.print()`),
     * e o CSS `@media print` de cada página já esconde todo o resto --
     * então o PrintManager do Android imprime exatamente o mesmo
     * conteúdo que o `window.print()` de navegador imprimiria, só que
     * disparado nativamente (sem chrome de navegador pra clicar).
     *
     * TODO: assim que a documentação/SDK da impressora térmica da
     * Gertec chegar (pendência registrada no plano), trocar isto pela
     * chamada direta ao SDK deles, sem passar pelo diálogo de impressão
     * genérico do Android.
     */
    @JavascriptInterface
    fun imprimir(dadosJson: String) {
        activity.runOnUiThread {
            val printManager = activity.getSystemService(Context.PRINT_SERVICE) as PrintManager
            val nomeTrabalho = "MY PARK"
            val adapter = webView.createPrintDocumentAdapter(nomeTrabalho)
            printManager.print(nomeTrabalho, adapter, PrintAttributes.Builder().build())
        }
    }
}
