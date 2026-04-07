# DKumanga

DKumanga es un script de línea de comandos desarrollado en Python para descargar capítulos de manga desde [enlace sospechoso eliminado]. El script opera exclusivamente mediante peticiones HTTP, sin depender de automatización de navegadores en segundo plano.

## Funcionalidades implementadas

  * **Conexiones HTTP:** Utiliza la librería `requests` con manejo de sesiones (`requests.Session()`) para la comunicación con el servidor.
  * **Extracción de URLs:** Localiza las rutas de las imágenes en el código fuente y las procesa mediante decodificación Base64 y operaciones lógicas XOR para obtener los enlaces finales.
  * **Asignación de formato por Magic Numbers:** Lee la firma de archivo (primeros bytes) del contenido descargado en memoria para determinar y asignar la extensión real (`.jpg`, `.png`, `.webp`, `.gif`), independientemente del nombre en la URL.
  * **Descarga selectiva:** Incluye parámetros en la línea de comandos para limitar la ejecución a un rango específico de capítulos.
  * **Empaquetado:** Cuenta con un flag de ejecución que comprime el directorio de imágenes resultante en un archivo `.cbz` al finalizar la descarga del capítulo.
  * **Validación de archivos locales:** Comprueba la existencia de los archivos en el directorio de destino antes de ejecutar la petición HTTP, omitiendo la descarga si el archivo ya está en disco.

## Requisitos

El script requiere Python 3.x y las siguientes dependencias:

```bash
pip install requests colorama tqdm
```

## Uso

La sintaxis básica requiere que pases la URL del manga como argumento principal.

```bash
python dkumanga.py <URL> [opciones]
```

### Ejemplos de uso

Descargar un manga completo:
```bash
python dkumanga.py https://www.kumanga.com/manga/1498/honey-lemon-soda
```

Descargar desde el capítulo 10 hasta el 25.5 y comprimirlos en `.cbz`:
```bash
python dkumanga.py https://www.kumanga.com/manga/1498/honey-lemon-soda -cm 10 -cx 25.5 --archive
```

## Argumentos disponibles

| Comando | Argumento largo | Descripción | Valor por defecto |
| :--- | :--- | :--- | :--- |
| `url` | - | **(Requerido)** La URL principal del manga en Kumanga. | - |
| `-cm` | `--chapter-minimum` | Capítulo mínimo desde donde empezar a descargar (incluido). | `0` |
| `-cx` | `--chapter-maximum` | Capítulo máximo hasta donde descargar (incluido). | `inf` (infinito) |
| | `--archive` | Comprime automáticamente las imágenes de cada capítulo en un archivo `.cbz`. | `False` |
| | `--max-retries` | Número máximo de reintentos si una petición falla (timeout o error HTTP). | `5` |

## Estructura de carpetas

El script creará un directorio base llamado `Descargas_Kumanga` en la misma ruta donde se ejecute. Dentro, organizará los archivos de la siguiente manera para soportar múltiples versiones/fansubs del mismo capítulo:

```text
Descargas_Kumanga/
└── Nombre del Manga/
    └── Nombre del Fansub/
        ├── ch01.0_p01.jpg
        ├── ch01.0_p02.webp
        ├── ...
        └── Nombre del Manga - Ch. 01.0.cbz (Si se usa --archive)
```

## Notas
No me hago responsable de lo que hagas con este script. Utilízalo bajo tu propia responsabilidad.
