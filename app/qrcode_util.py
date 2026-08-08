"""
Geração de QR code para o ticket impresso no totem de entrada -- permite
que o totem de saída e o totem de validação leiam o código do ticket
diretamente pelo scanner, sem precisar digitar.

Gerado no backend (não no navegador) pra não precisar embutir uma lib de
QR code em cada página de totem -- essas páginas são HTML autocontido,
sem processo de build.
"""
import qrcode
import qrcode.image.svg


def gerar_qr_svg(texto: str) -> str:
    """Devolve o SVG do QR code como string (só a tag <svg>...</svg>,
    sem a declaração <?xml ...?> na frente -- injetada via innerHTML no
    navegador, e a declaração XML não é válida em HTML)."""
    imagem = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage)
    svg = imagem.to_string().decode("utf-8")
    inicio = svg.find("<svg")
    return svg[inicio:] if inicio != -1 else svg
