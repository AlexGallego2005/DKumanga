# ─────────────────────────────────────────────
#  DKumanga — descargador de manga para kumanga.com
#  Requiere: requests, colorama, tqdm
#  Opcional: Pillow (para --pdf)
# ─────────────────────────────────────────────

import os
import re
import sys
import base64
import requests
import json
import glob
import colorama
import argparse
import zipfile
from time import sleep
from tqdm import tqdm

# ── Configuración global ──────────────────────
ARCHIVAL  = False               # Si True, empaqueta cada capítulo en .cbz al terminar
PDF_MODE  = False               # Si True, genera un PDF por capítulo al terminar
PDF_ONLY  = False               # Si True (requiere --pdf), borra las imágenes tras generar el PDF
MAX_RETRIES = 5                 # Número máximo de reintentos ante errores HTTP
BASE_DIR  = "Descargas_Kumanga" # Carpeta raíz donde se guardan todas las descargas
KNOWN_VERSION = "kx.reader.js?v=0.7"  # Versión del lector conocida (referencia)

retries = 0  # Contador global de reintentos; se resetea por capítulo


# ── Utilidades generales ──────────────────────

def clean(name):
    """Elimina caracteres no válidos en nombres de archivo/carpeta."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def createChapterUrl(mangaId, chapterN):
    """Construye la URL de un capítulo a partir del ID del manga y el número de capítulo."""
    return f"https://www.kumanga.com/manga/{ mangaId }/capitulo/{ chapterN }"

def createReadUrl(chapterId):
    """Construye la URL del lector a partir del ID de capítulo."""
    return f"https://www.kumanga.com/manga/leer/{ chapterId }"

def chapterFormat(cap_str):
    """
    Formatea el número de capítulo con ceros a la izquierda.
    Ejemplos: '1' → '01', '5.5' → '05.5'
    """
    cap_str = str(cap_str)
    if '.' in cap_str:
        entero, decimal = cap_str.split('.')
        return f"{entero.zfill(2)}.{decimal}"
    return cap_str.zfill(2)


# ── Descifrado de URLs de imágenes ────────────

def decrypt(p):
    """
    Descifra el payload Base64+XOR que contiene las URLs de las imágenes.
    El servidor cifra la lista de imágenes con una clave fija mediante XOR byte a byte.
    Devuelve la lista de objetos ya parseada como JSON.
    """
    key = "Jr54VwepF4La"
    decoded_bytes = base64.b64decode(p)
    string = ""
    for i in range(len(decoded_bytes)):
        char_code     = decoded_bytes[i]
        key_char_code = ord(key[i % len(key)])
        string += chr(char_code ^ key_char_code)  # XOR byte a byte con la clave cíclica
    return json.loads(string)


# ── Detección de formato por Magic Numbers ────

def extension(image_bytes):
    """
    Determina la extensión correcta del archivo leyendo la firma de los primeros bytes
    (magic numbers) en lugar de confiar en la extensión de la URL.
    """
    if image_bytes.startswith(b'\xff\xd8'):                          return '.jpg'
    elif image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):               return '.png'
    elif image_bytes[0:4] == b'RIFF' and image_bytes[8:12] == b'WEBP': return '.webp'
    elif image_bytes.startswith(b'GIF8'):                            return '.gif'
    else:                                                            return '.jpg'  # fallback


# ── Validación de archivos ya descargados ─────

def checkExisting(baseName: str, dir: str, pbar):
    """
    Comprueba si ya existe un archivo con ese nombre base (sin importar la extensión)
    en el directorio de destino. Si existe, lo informa y devuelve True para saltarlo.
    """
    pattern = os.path.join(glob.escape(dir), f"{ baseName }.*")
    files = glob.glob(pattern)
    if files:
        fullName = os.path.basename(files[0])
        pbar.write(f"{ colorama.Fore.BLACK }{ colorama.Style.BRIGHT }#{ os.path.join(dir, fullName) }{ colorama.Style.RESET_ALL }")
        return True
    return False


# ── Descarga de una imagen ────────────────────

def fetchChapterImage(url: str, session: requests.Session, pbar):
    """
    Descarga una imagen individual usando la sesión HTTP activa.
    Añade cabeceras User-Agent y Referer para simular una petición de navegador.
    Reintenta automáticamente ante errores HTTP hasta MAX_RETRIES veces.
    Propaga KeyboardInterrupt para permitir Ctrl+C limpio.
    """
    global retries

    # Normalizar URLs relativas al protocolo (//)
    if url.startswith("//"): url = "https:" + url

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Referer':    'https://www.kumanga.com/'
    }
    try:
        response = session.get(url=url, headers=headers, timeout=10)
        if response.status_code != 200:
            pbar.write(f"{ colorama.Fore.RED }[kumanga][error] { response.status_code } Error downloading image (retrying in 5 seconds... [{ retries + 1 }/{ MAX_RETRIES }])")
            retries += 1
            if retries == MAX_RETRIES:
                pbar.write(f"{ colorama.Fore.RED }[kumanga][error] Could not download the image within the max retries.")
                sys.exit(1)
            else:
                sleep(5)
                return fetchChapterImage(url=url, session=session, pbar=pbar)
        else:
            return response
    except KeyboardInterrupt:
        raise  # Dejar que el Ctrl+C burbujee hasta el manejador principal
    except Exception:
        pbar.write(f"{ colorama.Fore.RED }[kumanga][error] There was an error while downloading the image, skipping.")
        return False


# ── Barra de progreso ─────────────────────────

def createProgressBar(images: list, num: str):
    """Crea y devuelve una barra de progreso tqdm para la descarga de un capítulo."""
    return tqdm(enumerate(images, 1), total=len(images),
                desc=f"Chapter: { num }", unit="img",
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}]")


# ── Empaquetado en CBZ ────────────────────────

def archive(chapterDir: str, title: str, chapter: str):
    """
    Comprime todas las imágenes del capítulo en un archivo .cbz (ZIP sin compresión)
    dentro del mismo directorio del capítulo. Elimina las imágenes originales tras archivarlas.
    CBZ es el formato estándar para lectores de cómic/manga de escritorio.
    """
    name    = f"{ title } - Ch. { chapter }.cbz"
    cbzPath = os.path.join(chapterDir, name)

    if os.path.exists(cbzPath):
        print(f"{ colorama.Fore.YELLOW }[kumanga][warn] Archive already exists for chapter { chapter }, skipping.")
        return

    print(f"{ colorama.Fore.WHITE }[kumanga][info] Archiving chapter { chapter } into a CBZ file.")
    with zipfile.ZipFile(cbzPath, "w", zipfile.ZIP_STORED) as cbz:
        pattern = os.path.join(glob.escape(chapterDir), "p*.*")
        files   = glob.glob(pattern)
        images  = sorted([f for f in files if f.endswith((".jpg", ".png", ".webp", ".gif"))])
        for image in images:
            cbz.write(image, arcname=os.path.basename(image))
            os.remove(image)  # Borrar imagen suelta una vez añadida al CBZ

    print(f"{ colorama.Fore.WHITE }[kumanga][info] Archive completed and created for chapter { chapter }.")


# ── Generación de PDF ─────────────────────────

def createPdf(chapterDir: str, title: str, chapter: str, remove_images: bool = False):
    """
    Genera un PDF multipágina con todas las imágenes del capítulo usando Pillow.
    Requiere 'pip install Pillow'. Las imágenes se convierten a RGB antes de guardar
    para garantizar compatibilidad (evita problemas con canales alpha en PNG/WEBP).
    Si remove_images=True, elimina las imágenes originales tras generar el PDF
    (modo --pdf-only).
    """
    try:
        from PIL import Image
    except ImportError:
        print(f"{ colorama.Fore.RED }[kumanga][error] Pillow is required for PDF generation. Install it with: pip install Pillow")
        return

    pdfName = f"{ title } - Ch. { chapter }.pdf"
    pdfPath = os.path.join(chapterDir, pdfName)

    if os.path.exists(pdfPath):
        print(f"{ colorama.Fore.YELLOW }[kumanga][warn] PDF already exists for chapter { chapter }, skipping.")
        return

    # Recopilar y ordenar todas las imágenes del capítulo
    pattern    = os.path.join(glob.escape(chapterDir), "p*.*")
    files      = glob.glob(pattern)
    imageFiles = sorted([f for f in files if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))])

    if not imageFiles:
        print(f"{ colorama.Fore.YELLOW }[kumanga][warn] No images found to create PDF for chapter { chapter }.")
        return

    print(f"{ colorama.Fore.WHITE }[kumanga][info] Creating PDF for chapter { chapter } ({len(imageFiles)} pages).")

    pil_images = []
    for imgPath in imageFiles:
        try:
            img = Image.open(imgPath).convert("RGB")  # RGB requerido por el formato PDF de Pillow
            pil_images.append(img)
        except Exception as e:
            print(f"{ colorama.Fore.YELLOW }[kumanga][warn] Could not open image { imgPath }: { e }")

    if not pil_images:
        print(f"{ colorama.Fore.RED }[kumanga][error] No valid images to build PDF for chapter { chapter }.")
        return

    # La primera imagen es la página base; el resto se añaden como páginas adicionales
    first = pil_images[0]
    rest  = pil_images[1:]
    first.save(pdfPath, save_all=True, append_images=rest, format="PDF")
    print(f"{ colorama.Fore.WHITE }[kumanga][info] PDF created: { pdfPath }")

    # En modo --pdf-only eliminar las imágenes sueltas una vez el PDF está completo
    if remove_images:
        for imgPath in imageFiles:
            try:
                os.remove(imgPath)
            except Exception as e:
                print(f"{ colorama.Fore.YELLOW }[kumanga][warn] Could not remove image { imgPath }: { e }")
        print(f"{ colorama.Fore.WHITE }[kumanga][info] Source images removed (--pdf-only).")


# ── Descarga completa de un capítulo ──────────

def downloadChapter(mId: str, title: str, group: str, chapter: str, images: list):
    """
    Orquesta la descarga de todas las imágenes de un capítulo.
    Crea la estructura de carpetas BASE_DIR/título/fansub/Cap.XX/,
    descarga cada página, y al finalizar ejecuta el empaquetado si corresponde.
    """
    print(f"{ colorama.Fore.WHITE }[kumanga][info] Starting download for chapter { chapter }.")

    # Sanear nombres para usarlos como carpetas
    title   = clean(title)
    group   = clean(group)
    chapter = chapterFormat(chapter)

    # Una sesión por capítulo para reutilizar la conexión TCP durante todas las páginas
    session = requests.Session()

    # Estructura: BASE_DIR / título / fansub / Cap. XX /
    mangaDir   = os.path.join(BASE_DIR, title)
    groupDir   = os.path.join(mangaDir, group)
    chapterDir = os.path.join(groupDir, f"Cap. { chapter }")
    if not os.path.exists(chapterDir): os.makedirs(chapterDir)

    print(f"{ colorama.Style.DIM }[kumanga][info] Group: { group }.{ colorama.Style.RESET_ALL }")
    print(f"{ colorama.Style.DIM }[kumanga][info] Saving to: { chapterDir }.{ colorama.Style.RESET_ALL }")

    pbar = createProgressBar(images=images, num=chapter)

    for idx, url in pbar:
        try:
            baseName = f"p{ str(idx).zfill(3) }"  # p001, p002, …

            # Saltar si la página ya existe en disco (cualquier extensión)
            exists = checkExisting(baseName=baseName, dir=chapterDir, pbar=pbar)
            if exists: continue

            response = fetchChapterImage(url=url, session=session, pbar=pbar)
            if not response: continue

            # Determinar extensión real por magic numbers y guardar
            ext      = extension(response.content)
            name     = f"{ baseName }{ ext }"
            pathFile = os.path.join(chapterDir, name)

            with open(pathFile, 'wb') as f: f.write(response.content)
            pbar.write(f"{ colorama.Fore.GREEN }{ pathFile }{ colorama.Style.RESET_ALL } OK")
            sleep(0.1)  # Pequeña pausa para no saturar el servidor

        except KeyboardInterrupt:
            pbar.close()
            raise  # Propagar para salida limpia
        except Exception as e:
            pbar.write(f"{ colorama.Fore.RED }[kumanga][error] Page { idx } download failed: { e }.")

    pbar.close()

    # Post-procesado opcional al terminar el capítulo
    if PDF_MODE:
        createPdf(chapterDir=chapterDir, title=title, chapter=chapter, remove_images=PDF_ONLY)
    if ARCHIVAL:
        archive(chapterDir=chapterDir, title=title, chapter=chapter)


# ── Fetch de la página principal del manga ────

def fetchMangaUrl(url: str):
    """
    Descarga el HTML de la página principal del manga.
    Reintenta ante errores HTTP hasta MAX_RETRIES veces.
    Propaga KeyboardInterrupt para salida limpia con Ctrl+C.
    """
    global retries

    try:
        response = requests.get(url=url)
        if response.status_code != 200:
            print(f"{ colorama.Fore.RED }[kumanga][error] { response.status_code } Error Found (retrying in 5 seconds... [{ retries + 1 }/{ MAX_RETRIES }])")
            retries += 1
            if retries == MAX_RETRIES:
                print(f"{ colorama.Fore.RED }[kumanga][error] Could not fetch the manga URL within the max retries.")
                sys.exit(1)
            else:
                sleep(5)
                return fetchMangaUrl(url=url)
        else:
            return response.text
    except KeyboardInterrupt:
        raise
    except Exception:
        print(f"{ colorama.Fore.RED }[kumanga][error] There was an error while fetching the manga URL, exiting.")
        sys.exit(1)


# ── Parseo de metadatos del manga ─────────────

def parseMangaData(url: str, html: str):
    """
    Extrae del HTML el título, ID y lista completa de capítulos del manga.
    Los capítulos visibles en la página se obtienen por 'data-sort'; los capítulos
    adicionales (paginados) vienen en la variable JS 'OTHER_CHAPTERS'.
    Devuelve la lista ordenada de menor a mayor número de capítulo.
    """
    # Extraer título del h1
    mangaTitle = re.search(r'<h1.+?>(.+)<small>', html)
    if mangaTitle: mangaTitle = mangaTitle.group(1).strip()
    else:
        print(f"{ colorama.Fore.RED }[kumanga][error] Could not parse the manga title.")
        sys.exit(1)

    # Extraer ID numérico del manga desde la URL
    mangaId = re.search(r"manga\/([0-9.]+)\/", url)
    if mangaId: mangaId = mangaId.group(1).strip()
    else:
        print(f"{ colorama.Fore.RED }[kumanga][error] Could not parse the manga Id.")
        sys.exit(1)

    print(f"{ colorama.Fore.WHITE }[kumanga][info] Loaded manga { colorama.Style.BRIGHT }{ mangaTitle }{ colorama.Style.NORMAL } with Id { colorama.Style.DIM }{ mangaId }{ colorama.Style.NORMAL }")

    # Capítulos adicionales inyectados por JS (mangas con muchos capítulos los pagina)
    chapter_str = re.search(r'let OTHER_CHAPTERS = (\[.*?\]);', html)
    try:
        if chapter_str: chapter_str = json.loads(chapter_str.group(1))
        else:           chapter_str = json.loads("[]")
    except Exception:
        print(f"{ colorama.Fore.YELLOW }[kumanga][warn] Error while parsing additional chapters.")

    # Capítulos visibles directamente en el HTML
    chapter_html = re.findall(r'data-sort="([0-9.]+)"', html)
    if len(chapter_html) < 1:
        print(f"{ colorama.Fore.YELLOW }[kumanga][warn] No chapters have been found, are you sure the URL is correct?")

    # Combinar ambas fuentes y ordenar de menor a mayor
    chapters = list(reversed(chapter_html + [cap["NumCap"] for cap in chapter_str]))
    if len(chapters) < 1:
        print(f"{ colorama.Fore.RED }[kumanga][error] A total of 0 chapters were found, exiting.")
        sys.exit(1)
    else:
        print(f"{ colorama.Fore.WHITE }[kumanga][info] { len(chapters) } total chapters were found during scrapping.")

    return chapters, mangaTitle, mangaId


# ── Resolución de URL real del capítulo ───────

def fetchChapterRealUrl(url: str):
    """
    Resuelve la URL definitiva de un capítulo. Kumanga puede redirigir directamente
    (un solo fansub) o mostrar una página con múltiples versiones del capítulo
    (varios fansubs). En el segundo caso extrae todos los IDs disponibles.
    Devuelve una lista de IDs/URLs o False si falla.
    """
    global retries

    try:
        response = requests.get(url=url)
        if response.status_code != 200:
            print(f"{ colorama.Fore.RED }[kumanga][error] { response.status_code } Failed to fetch chapter URL (retrying in 5 seconds... [{ retries + 1 }/{ MAX_RETRIES }])")
            retries += 1
            if retries == MAX_RETRIES:
                print(f"{ colorama.Fore.RED }[kumanga][error] There was an error getting the URL for this chapter, skipping.")
                return False
            else:
                sleep(5)
                return fetchChapterRealUrl(url=url)

        if url != response.url:
            # Hubo redirección → un único fansub disponible, devolver URL final directamente
            return [response.url]
        else:
            # Sin redirección → página de selección con múltiples fansubs
            html = response.text
            urls = re.findall(r'href="\/manga\/c\/([0-9.]+)"', html)
            if len(urls) < 1:
                print(f"{ colorama.Fore.RED }[kumanga][error] No available URLs found for this chapter.")
                return False
            else:
                return urls
    except KeyboardInterrupt:
        raise
    except Exception:
        print(f"{ colorama.Fore.RED }[kumanga][error] There was an error getting the URL for this chapter, skipping.")
        return False


# ── Fetch del HTML del lector ─────────────────

def fetchReadChapter(url: str):
    """
    Descarga el HTML de la página del lector de un capítulo concreto.
    Es desde aquí donde se extrae el payload cifrado con las URLs de las imágenes.
    Reintenta ante errores HTTP hasta MAX_RETRIES veces.
    """
    global retries

    try:
        response = requests.get(url=url)
        if response.status_code != 200:
            print(f"{ colorama.Fore.RED }[kumanga][error] { response.status_code } Error Found (retrying in 5 seconds... [{ retries + 1 }/{ MAX_RETRIES }])")
            retries += 1
            if retries == MAX_RETRIES:
                print(f"{ colorama.Fore.RED }[kumanga][error] Could not fetch the chapter URL within the max retries.")
                sys.exit(1)
            else:
                sleep(5)
                return fetchReadChapter(url=url)
        else:
            return response.text
    except KeyboardInterrupt:
        raise
    except Exception:
        print(f"{ colorama.Fore.RED }[kumanga][error] There was an error while fetching the chapter URL, skipping.")
        return False


# ── Parseo de datos del capítulo ──────────────

def parseChapterData(url: str):
    """
    Extrae del HTML del lector el nombre del fansub y la lista de URLs de imágenes.
    Las URLs están cifradas en la variable JS 'p' con Base64+XOR; se llama a decrypt()
    para obtenerlas y luego se convierten de hexadecimal a ASCII.
    Devuelve (group, images) o (False, False) si algo falla.
    """
    global retries

    retries = 0
    html = fetchReadChapter(url=url)
    if not html: return False, False

    try:
        # Extraer nombre del fansub/grupo que subió el capítulo
        group = re.search(r'Subido por: (.*?)<\/', html)
        if group: group = group.group(1).strip()
        else:     group = "None"

        # Extraer el payload cifrado (variable JS 'p')
        p = re.search(r'const p = "(.*?)"', html)
        if p: p = p.group(1).strip()
        else:
            print(f"{ colorama.Fore.RED }[kumanga][error] Variable <p> not found on website (retrying in 5 seconds... [{ retries + 1 }/{ MAX_RETRIES }])")
            retries += 1
            if retries == MAX_RETRIES:
                print(f"{ colorama.Fore.RED }[kumanga][error] Could not find the variable, skipping chapter.")
                return False, False
            else:
                sleep(5)
                return parseChapterData(url=url)

        # Descifrar el payload y convertir cada URL de HEX a ASCII
        images = []
        try:
            hexImages = decrypt(p)
            for hexUrl in hexImages:
                hexImage = hexUrl.split("=")[1]
                # Cada par de caracteres hex representa un byte del carácter ASCII
                urlImage = ''.join([chr(int(hexImage[i:i+2], 16)) for i in range(0, len(hexImage), 2)])
                images.append(urlImage)
        except Exception:
            print(f"{ colorama.Fore.RED }[kumanga][error] Error decrypting or converting the images from HEX to ASCII.")
            return False, False

        print(f"{ colorama.Fore.WHITE }[kumanga][info] A total of { len(images) } images were found during the scan.")
        return group, images

    except KeyboardInterrupt:
        raise
    except Exception:
        print(f"{ colorama.Fore.RED }[kumanga][error] Something failed while parsing the chapter data.")
        return False, False


# ── Filtro de capítulos por rango ─────────────

def getDesiredChapters(chapters, min, max):
    """Filtra la lista de capítulos para quedarse solo con los del rango [min, max]."""
    return [c for c in chapters if min <= float(c) <= max]


# ── Flujo principal ───────────────────────────

def main(mangaUrl: str, chapterMin: float, chapterMax: float):
    """
    Punto de entrada lógico del script. Carga el manga, filtra capítulos
    según el rango indicado e itera descargando cada uno.
    Por cada capítulo puede haber varios fansubs; se descargan todos.
    """
    global retries

    retries = 0
    html = fetchMangaUrl(mangaUrl)
    chapters, title, mId = parseMangaData(url=mangaUrl, html=html)

    # Aplicar filtro de rango e informar si se redujo la lista
    prev     = len(chapters)
    chapters = getDesiredChapters(chapters=chapters, min=chapterMin, max=chapterMax)
    if prev != len(chapters):
        print(f"{ colorama.Fore.CYAN }[kumanga][info] After filtering, only { len(chapters) } chapters are elegible for download.")
        print(f"{ colorama.Fore.CYAN }[kumanga][info] Downloading from chapter { colorama.Style.BRIGHT }{ chapters[0] }{ colorama.Style.NORMAL } to chapter { colorama.Style.BRIGHT }{ chapters[-1] }{ colorama.Style.NORMAL }.")

    for chapterN in chapters:
        retries = 0
        print(f"{ colorama.Fore.WHITE }[kumanga][info] Starting scanning chapter { chapterN }.")

        # Obtener la(s) URL(s) reales del capítulo (puede haber varias por fansub)
        tempUrl = createChapterUrl(mangaId=mId, chapterN=chapterN)
        urlList = fetchChapterRealUrl(tempUrl)
        if not urlList: continue

        # Iterar sobre cada versión del capítulo (un fansub distinto por URL)
        for url in urlList:
            cId = re.search(r"\/([0-9.]+)$", url)
            if cId: cId = cId.group(1).strip()
            else:   cId = url

            url = createReadUrl(cId)
            group, imageUrls = parseChapterData(url=url)
            if not group and not imageUrls: continue

            downloadChapter(mId=mId, title=title, group=group, chapter=chapterN, images=imageUrls)


# ── Entrada del script ────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso incorrecto. Debes proporcionar la URL del manga.")
        print("Ejemplo: python kumanga.py https://www.kumanga.com/manga/1498/honey-lemon-soda")
        sys.exit(1)

    parser = argparse.ArgumentParser(prog="Kumanga downloader", description="Download manga chapters from kumanga.com")
    parser.add_argument("url",                   help="The manga URL to download chapters from")
    parser.add_argument("-cm", "--chapter-minimum",
                        type=float, default=0,
                        help="The minimum chapter from where to download (included)")
    parser.add_argument("-cx", "--chapter-maximum",
                        type=float, default=float("inf"),
                        help="The maximum chapter until where to download (included)")
    parser.add_argument("--max-retries",
                        type=int,   default=5,
                        help="The maximum number of retries to do for fetching URLs")
    parser.add_argument("--archive",
                        action="store_true",
                        help="Archive into a CBZ file when a chapter finishes downloading")
    parser.add_argument("--pdf",
                        action="store_true",
                        help="Generate a PDF file per chapter after downloading (requires Pillow: pip install Pillow)")
    parser.add_argument("--pdf-only",
                        action="store_true",
                        help="Like --pdf but deletes the source images after the PDF is created. Implies --pdf.")

    args = parser.parse_args()
    colorama.init(autoreset=True)

    # --pdf-only implica --pdf; validar que no se use solo sin --pdf
    if args.pdf_only and not args.pdf:
        args.pdf = True

    # Volcar argumentos en las variables globales de configuración
    MAX_RETRIES = args.max_retries
    ARCHIVAL    = args.archive
    PDF_MODE    = args.pdf
    PDF_ONLY    = args.pdf_only

    try:
        main(mangaUrl=args.url, chapterMin=args.chapter_minimum, chapterMax=args.chapter_maximum)
    except KeyboardInterrupt:
        # Capturado aquí tras propagarse desde cualquier función anidada
        print(f"\n{ colorama.Fore.YELLOW }[kumanga][info] Descarga interrumpida por el usuario.")
        sys.exit(0)
