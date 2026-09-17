# UABE Web (Python / Pyodide) — Unity Asset Bundle Explorer

Versão web do **UABE (Unity Assets Bundle Extractor)** onde a lógica é escrita em **Python** e roda no navegador via **Pyodide** (Python compilado para WebAssembly). A página é 100% estática — funciona no **GitHub Pages** sem servidor backend.

## Como funciona
- `index.html` + `js/app.js` — interface (arrastar & soltar, árvore, preview, exportar)
- `py/app.py` — parser completo em Python: UnityFS/LZ4/LZMA, `.assets`, texturas (DXT/RGBA → PNG via Pillow)
- **Pyodide** é carregado de CDN (`cdn.jsdelivr.net`) no primeiro acesso (~10 MB, depois fica em cache). Pillow incluso.
- Tudo roda no navegador do usuário — nenhum dado é enviado a servidores.

## Funcionalidades
- Abrir `.unity3d`, `.bundle`, `.assetbundle`, `.assets` (UnityFS v6/v7, LZ4/LZ4HC/LZMA)
- Árvore: bundle → entradas → assets, com **nomes** dos assets (`m_Name`)
- **Pré-visualização de texturas** (Texture2D): RGBA32/RGB24/ARGB32/BGRA32/RGB565/ARGB4444/Alpha8/DXT1/DXT5 → PNG (Pillow)
- **Pré-visualização de TextAsset** (scripts/JSON/txt)
- Exportar asset individual ou entrada inteira (bruto, `.bin`)

## Deploy no GitHub Pages
1. Crie um repositório e faça upload de **todo o conteúdo** desta pasta (incluindo `.nojekyll`, `py/`, `js/`, `css/`).
2. **Settings → Pages** → Source: `Deploy from a branch` → Branch: `main` / `/ (root)` → Save.
3. Acesse `https://SEU-USUARIO.github.io/NOME-REPO/`.

Requer internet no primeiro acesso (para carregar Pyodide do CDN).

## Limitações
- Texturas PVRTC/ETC/ASTC/BC7 são **identificadas** mas ainda não decodificadas (exporte em bruto).
- Sem edição/substituição de assets (é leitor/extrator).
- Áudio e malhas 3D não são pré-visualizados.
