package com.mypark.totem

import android.app.Activity
import android.util.Log
import br.com.gertec.gdk.printer.Alignment
import br.com.gertec.gdk.printer.BarcodeFormat
import br.com.gertec.gdk.printer.BarcodeType
import br.com.gertec.gdk.printer.CutType
import br.com.gertec.gdk.printer.Printer
import br.com.gertec.gdk.printer.PrinterError
import br.com.gertec.gdk.printer.TextFormat

/**
 * Impressora térmica (SDK "GerSDK Varejo", AAR em app/libs/) sem
 * depender de WebView/JS -- mesma lógica que já funcionava dentro de
 * AndroidBridge (testada e confirmada ao vivo), só reaproveitável
 * direto pelas telas nativas de totem. Chamar sempre a partir da UI
 * thread da Activity dona.
 */
class Impressora(activity: Activity, private val aoFalhar: (String) -> Unit) : Printer.Listener {

    private val TAG = "Impressora"
    private val printer: Printer = Printer.getInstance(activity, this)

    fun texto(conteudo: String) {
        try {
            val formato = TextFormat()
            formato.setBold(false)
            formato.setFontSize(28)
            formato.setAlignment(Alignment.CENTER)
            printer.printText(formato, conteudo)
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao imprimir texto", e)
        }
    }

    fun codigo(conteudo: String) {
        try {
            val qr = BarcodeFormat(BarcodeType.QR_CODE)
            printer.printBarcode(qr, conteudo)
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao imprimir código", e)
        }
    }

    fun avancarPapel() {
        try {
            // Ver comentário histórico em AndroidBridge.kt: 80 é uma
            // estimativa pra ~1cm de sobra antes do corte (203dpi/8
            // dots-mm, padrão comum de impressora térmica de recibo).
            printer.scrollPaper(80)
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao avançar papel", e)
        }
    }

    fun cortar() {
        try {
            printer.cutPaper(CutType.PAPER_PARTIAL_CUT)
        } catch (e: Exception) {
            Log.e(TAG, "Erro ao cortar papel", e)
        }
    }

    override fun onPrinterError(printerError: PrinterError) {
        Log.e(TAG, "Erro na impressora: $printerError")
        aoFalhar("Erro na impressora: $printerError")
    }

    override fun onPrinterSuccessful(codigo: Int) {
        Log.i(TAG, "Impressão concluída: $codigo")
    }
}
