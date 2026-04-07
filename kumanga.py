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

ARCHIVAL = False
MAX_RETRIES = 5
BASE_DIR = "Descargas_Kumanga"
KNOWN_VERSION = "kx.reader.js?v=0.7"

retries = 0

def clean(name): return re.sub(r'[\\/*?:"<>|]', "", name).strip()
def createChapterUrl(mangaId, chapterN): return f"https://www.kumanga.com/manga/{ mangaId }/capitulo/{ chapterN }"
def createReadUrl(chapterId): return f"https://www.kumanga.com/manga/leer/{ chapterId }"

def chapterFormat(cap_str):
    cap_str = str(cap_str)
    if '.' in cap_str:
        entero, decimal = cap_str.split('.')
        return f"{entero.zfill(2)}.{decimal}"
    return cap_str.zfill(2)

def decrypt(p):
    key = "Jr54VwepF4La"
    decoded_bytes = base64.b64decode(p)
    string = ""

    for i in range(len(decoded_bytes)):
        char_code = decoded_bytes[i]
        key_char_code = ord(key[i % len(key)])
        string += chr(char_code ^ key_char_code)
    return json.loads(string)

def extension(image_bytes):
    if image_bytes.startswith(b'\xff\xd8'): return '.jpg'
    elif image_bytes.startswith(b'\x89PNG\r\n\x1a\n'): return '.png'
    elif image_bytes[0:4] == b'RIFF' and image_bytes[8:12] == b'WEBP': return '.webp'
    elif image_bytes.startswith(b'GIF8'): return '.gif'
    else: return '.jpg'

def checkExisting(baseName: str, dir: str, pbar):
    pattern = os.path.join(glob.escape(dir), f"{ baseName }.*")
    files = glob.glob(pattern)

    if files:
        fullName = os.path.basename(files[0])
        pbar.write(f"{ colorama.Fore.BLACK }{ colorama.Style.BRIGHT }#{ os.path.join(dir, fullName) }{ colorama.Style.RESET_ALL }")
        return True
    return False

def fetchChapterImage(url: str, session: requests.Session, pbar):
    global retries
    
    if (url.startswith("//")): url = "https:" + url
    headers = { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36', 'Referer': 'https://www.kumanga.com/' }

    try:
        response = session.get(url=url, headers=headers, timeout=10)
        if (response.status_code != 200):
            pbar.write(f"{ colorama.Fore.RED }[kumanga][error] { response.status_code } Error downloading image (retrying in 5 seconds... [{ retries + 1 }/{ MAX_RETRIES }])")
            retries += 1
            if retries == MAX_RETRIES:
                pbar.write(f"{ colorama.Fore.RED }[kumanga][error] Could not download the image within the max retries.")
                sys.exit(1)
            else:
                sleep(5)
                return fetchChapterImage(url=url)
        else:
            return response
    except:
        pbar.write(f"{ colorama.Fore.RED }[kumanga][error] There was an error while downloading the image, skipping.")
        return False

def createProgressBar(images: list, num: str):
    return tqdm(enumerate(images, 1), total=len(images),
                desc=f"Chapter: { num }", unit="img",
                bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}]")

def archive(dir: str, title: str, chapter: str):
    name = f"{ title } - Ch. { chapter }.cbz"
    cbzDir = os.path.join(dir, name)

    if os.path.exists(cbzDir):
        print(f"{ colorama.Fore.YELLOW }[kumanga][warn] Archive already exists for chapter { chapter }, skipping.")
        return
    print(f"{ colorama.Fore.WHITE }[kumanga][info] Archiving chapter { chapter } into a CBZ file.")

    with zipfile.ZipFile(cbzDir, "w", zipfile.ZIP_STORED) as cbz:
        pattern = os.path.join(glob.escape(dir), f"ch{ chapter }_p*.*")
        files = glob.glob(pattern)
        images = sorted([f for f in files if f.endswith((".jpg", ".png", ".webp", ".gif"))])
        for image in images:
            cbz.write(image, arcname=image)
            os.remove(image)
    
    print(f"{ colorama.Fore.WHITE }[kumanga][info] Archive completed and created for chapter { chapter }.")

def downloadChapter(mId: str, title: str, group: str, chapter: str, images: list):
    print(f"{ colorama.Fore.WHITE }[kumanga][info] Starting download for chapter { chapter }.")
    title = clean(title)
    group = clean(group)
    chapter = chapterFormat(chapter)

    session = requests.Session()

    mangaDir = os.path.join(BASE_DIR, title)
    groupDir = os.path.join(mangaDir, group)
    if not os.path.exists(groupDir): os.makedirs(groupDir)

    print(f"{ colorama.Style.DIM }[kumanga][info] Group: { group }.{ colorama.Style.RESET_ALL }")

    pbar = createProgressBar(images=images, num=chapter)

    for idx, url in pbar:
        try:
            baseName = f"ch{ chapter }_p{ str(idx).zfill(2) }"
            exists = checkExisting(baseName=baseName, dir=groupDir, pbar=pbar)
            if exists: continue

            response = fetchChapterImage(url=url, session=session, pbar=pbar)
            if not response: continue
            
            ext = extension(response.content)
            name = f"{ baseName }{ ext }"
            pathFile = os.path.join(groupDir, name)

            with open(pathFile, 'wb') as f: f.write(response.content)
            pbar.write(f"{ colorama.Fore.GREEN }{ pathFile }{ colorama.Style.RESET_ALL } OK")
            sleep(0.1)
        except Exception as e:
            pbar.write(f"{ colorama.Fore.RED }[kumanga][error] Page { idx } download failed: { e }.")

    pbar.close()
    if ARCHIVAL: archive(dir=groupDir, title=title, chapter=chapter)

def fetchMangaUrl(url: str):
    global retries
    
    try:
        response = requests.get(url=url)
        if (response.status_code != 200):
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
    except:
        print(f"{ colorama.Fore.RED }[kumanga][error] There was an error while fetching the manga URL, exiting.")
        sys.exit(1)
    
def parseMangaData(url: str, html: str):
    mangaTitle = re.search(r'<h1.+?>(.+)<small>', html)
    if mangaTitle: mangaTitle = mangaTitle.group(1).strip()
    else:
        print(f"{ colorama.Fore.RED }[kumanga][error] Could not parse the manga title.")
        sys.exit(1)
        
    mangaId = re.search(r"manga\/([0-9.]+)\/", url)
    if mangaId: mangaId = mangaId.group(1).strip()
    else:
        print(f"{ colorama.Fore.RED }[kumanga][error] Could not parse the manga Id.")
        sys.exit(1)

    print(f"{ colorama.Fore.WHITE }[kumanga][info] Loaded manga { colorama.Style.BRIGHT }{ mangaTitle }{ colorama.Style.NORMAL } with Id { colorama.Style.DIM }{ mangaId }{ colorama.Style.NORMAL }")

    chapter_str = re.search(r'let OTHER_CHAPTERS = (\[.*?\]);', html)
    try:
        if chapter_str: chapter_str = json.loads(chapter_str.group(1))
        else: chapter_str = json.loads("[]")
    except:
        print(f"{ colorama.Fore.YELLOW }[kumanga][warn] Error while parsing additional chapters.")
    
    chapter_html = re.findall(r'data-sort="([0-9.]+)"', html)
    if len(chapter_html) < 1:
        print(f"{ colorama.Fore.YELLOW }[kumanga][warn] No chapters have been found, are you sure the URL is correct?")
    
    chapters = list(reversed(chapter_html + [cap["NumCap"] for cap in chapter_str]))
    if len(chapters) < 1:
        print(f"{ colorama.Fore.RED }[kumanga][error] A total of 0 chapters were found, exiting.")
        sys.exit(1)
    else:
        print(f"{ colorama.Fore.WHITE }[kumanga][info] { len(chapters) } total chapters were found during scrapping.")

    return chapters, mangaTitle, mangaId

def fetchChapterRealUrl(url: str):
    global retries
    
    try:
        response = requests.get(url=url)
        if (response.status_code != 200):
            print(f"{ colorama.Fore.RED }[kumanga][error] { response.status_code } Failed to fetch chapter URL (retrying in 5 seconds... [{ retries + 1 }/{ MAX_RETRIES }])")
            retries += 1
            if retries == MAX_RETRIES:
                print(f"{ colorama.Fore.RED }[kumanga][error] There was an error getting the URL for this chapter, skipping.")
                return False
            else:
                sleep(5)
                return fetchChapterRealUrl(url=url)
        
        if url != response.url: return [response.url]
        else:
            html = response.text
            urls = re.findall(r'href="\/manga\/c\/([0-9.]+)"', html)
            if len(urls) < 1:
                print(f"{ colorama.Fore.RED }[kumanga][error] No available URLs found for this chapter.")
                return False
            else: return urls
    except:
        print(f"{ colorama.Fore.RED }[kumanga][error] There was an error getting the URL for this chapter, skipping.")
        return False
    
def fetchReadChapter(url: str):
    global retries

    try:
        response = requests.get(url=url)
        if (response.status_code != 200):
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
    except:
        print(f"{ colorama.Fore.RED }[kumanga][error] There was an error while fetching the chapter URL, skipping.")
        return False

def parseChapterData(url: str):
    global retries

    retries = 0
    html = fetchReadChapter(url=url)
    if not html: return False, False
    
    try:
        group = re.search(r'Subido por: (.*?)<\/', html)
        if group: group = group.group(1).strip()
        else: group = "None"

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
        #script = re.search(r'"(.*?kx.reader.js.+?)"', html).group(1)
        
        images = []
        try:
            hexImages = decrypt(p)
            for hexUrl in hexImages:
                hexImage = hexUrl.split("=")[1]
                urlImage = ''.join([chr(int(hexImage[i:i+2], 16)) for i in range(0, len(hexImage), 2)])
                images.append(urlImage)
        except:
            print(f"{ colorama.Fore.RED }[kumanga][error] Error decrypting or converting the images from HEX to ASCII.")
            return False, False

        print(f"{ colorama.Fore.WHITE }[kumanga][info] A total of { len(images) } images were found during the scan.")
        return group, images
    except:
        print(f"{ colorama.Fore.RED }[kumanga][error] Something failed while parsing the chapter data.")
        return False, False

def getDesiredChapters(chapters, min, max):
    return [c for c in chapters if min <= float(c) <= max]

def main(mangaUrl: str, chapterMin: float, chapterMax: float):
    global retries
    
    retries = 0
    html = fetchMangaUrl(mangaUrl)
    chapters, title, mId = parseMangaData(url=mangaUrl, html=html)
    prev = len(chapters)
    chapters = getDesiredChapters(chapters=chapters, min=chapterMin, max=chapterMax)
    if prev != len(chapters):
        print(f"{ colorama.Fore.CYAN }[kumanga][info] After filtering, only { len(chapters) } chapters are elegible for download.")
        print(f"{ colorama.Fore.CYAN }[kumanga][info] Downloading from chapter { colorama.Style.BRIGHT }{ chapters[0] }{ colorama.Style.NORMAL } to chapter { colorama.Style.BRIGHT }{ chapters[-1] }{ colorama.Style.NORMAL }.")
    
    for chapterN in chapters:
        retries = 0
        print(f"{ colorama.Fore.WHITE }[kumanga][info] Starting scanning chapter { chapterN }.")
        tempUrl = createChapterUrl(mangaId=mId, chapterN=chapterN)
        urlList = fetchChapterRealUrl(tempUrl)
        if not urlList: continue
        
        for url in urlList:
            cId = re.search(r"\/([0-9.]+)$", url)
            if cId: cId = cId.group(1).strip()
            else: cId = url

            url = createReadUrl(cId)
            group, imageUrls = parseChapterData(url=url)
            if not group and not imageUrls: continue

            downloadChapter(mId=mId, title=title, group=group, chapter=chapterN, images=imageUrls)



if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso incorrecto. Debes proporcionar la URL del manga.")
        print("Ejemplo: python kumanga.py https://www.kumanga.com/manga/1498/honey-lemon-soda")
        sys.exit(1)

    parser = argparse.ArgumentParser(prog="Kumanga downloader", description="Download manga chapters from kumanga.com")
    parser.add_argument("url", help="The manga URL to download chapters from")
    parser.add_argument("-cm", "--chapter-minimum",
                        type=float,
                        default=0,
                        help="The minimum chapter from where to download (included)")
    
    parser.add_argument("-cx", "--chapter-maximum",
                        type=float,
                        default=float("inf"),
                        help="The maximum chapter until where to download (included)")
    
    parser.add_argument("--max-retries",
                        type=int,
                        default=5,
                        help="The maximum number of retries to do for fetching URLs")
    
    parser.add_argument("--archive",
                        action="store_true",
                        help="Archive into a CBZ file when a chapter finishes downloading")
    
    args = parser.parse_args()
    colorama.init(autoreset=True)
    MAX_RETRIES = args.max_retries
    ARCHIVAL = args.archive
    
    main(mangaUrl=args.url, chapterMin=args.chapter_minimum, chapterMax=args.chapter_maximum)