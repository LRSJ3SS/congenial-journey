/* UABE Web (Python/Pyodide) - UI glue */
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var pyodide = null;
  var state = { data: null, fileName: '' };

  function setStatus(msg, cls) {
    $('statusMain').innerHTML = (cls === 'err' ? '<span class="err">' : cls === 'ok' ? '<span class="ok">' : '') + msg + (cls ? '</span>' : '');
  }
  function setExtra(m) { $('statusExtra').textContent = m || ''; }
  function fmtSize(n) {
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KiB';
    if (n < 1073741824) return (n / 1048576).toFixed(2) + ' MiB';
    return (n / 1073741824).toFixed(2) + ' GiB';
  }
  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function downloadBase64(b64, name) {
    var bin = atob(b64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    var blob = new Blob([bytes], { type: 'application/octet-stream' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
  }

  // ---------- Pyodide init ----------
  async function init() {
    try {
      setStatus('<span class="spinner"></span>Carregando Pyodide (WebAssembly)...');
      pyodide = await loadPyodide();
      setStatus('<span class="spinner"></span>Carregando Pillow (imagens)...');
      try {
        await pyodide.loadPackage('pillow');
      } catch (pillowErr) {
        // Pillow optional — parsing still works, only texture PNG preview is disabled.
        console.warn('Pillow não disponível:', pillowErr);
      }
      setStatus('<span class="spinner"></span>Carregando parser Python...');
      var resp = await fetch('py/app.py');
      if (!resp.ok) {
        throw new Error('Não foi possível carregar py/app.py (HTTP ' + resp.status + '). Verifique se a pasta py/ foi enviada ao repositório e se o .nojekyll existe.');
      }
      var code = new TextDecoder('utf-8').decode(await resp.arrayBuffer());
      try {
        pyodide.runPython(code);
      } catch (pyErr) {
        var full = (pyErr.message || String(pyErr)).slice(0, 1200);
        $('dzTitle').textContent = 'Erro no código Python';
        $('dzSub').innerHTML = '<pre style="text-align:left;max-width:560px;overflow:auto;max-height:200px;background:#1a1b21;padding:12px;border-radius:6px;font-size:11px;color:#f0a0a0;white-space:pre-wrap;">' + escapeHtml(full) + '</pre>';
        setStatus('Erro ao interpretar app.py — veja detalhes acima.', 'err');
        return;
      }
      $('btnOpen').disabled = false;
      $('dzTitle').textContent = 'Arraste um arquivo aqui';
      $('dzSub').textContent = 'ou clique para selecionar. Processamento em Python, 100% local no navegador.';
      $('dzFormats').style.display = 'block';
      setStatus('Pronto. Python carregado. Arraste um bundle.', 'ok');
    } catch (e) {
      setStatus('Erro: ' + e.message, 'err');
      $('dzTitle').textContent = 'Falha ao carregar';
      $('dzSub').innerHTML = '<div style="max-width:520px;">' + escapeHtml(e.message) + '<br><br>Verifique sua conexão (Pyodide é carregado via CDN) e se a pasta <b>py/</b> foi enviada ao repositório.</div>';
    }
  }

  // ---------- File handling ----------
  function handleFile(file) {
    state.fileName = file.name;
    $('fileName').textContent = file.name;
    setStatus('<span class="spinner"></span>Processando ' + file.name + ' em Python...');
    var reader = new FileReader();
    reader.onload = function (e) {
      try {
        var u8 = new Uint8Array(e.target.result);
        var handle = pyodide.globals.get('handle_file');
        var jsonStr = handle(u8);
        var result = JSON.parse(jsonStr);
        if (result.error) {
          setStatus('Não foi possível abrir: ' + result.error, 'err');
          return;
        }
        state.data = result;
        $('dropzone').classList.add('hidden');
        $('app').classList.add('visible');
        $('btnClose').classList.remove('hidden');
        setStatus('Arquivo carregado: ' + (result.kind === 'bundle' ? result.info.entryCount + ' entradas' : result.info.assetCount + ' assets'), 'ok');
        setExtra((result.info.engine || result.info.unityVersion || ''));
        buildTree();
        showBundleInfo();
      } catch (err) {
        setStatus('Erro: ' + err.message, 'err');
      }
    };
    reader.readAsArrayBuffer(file);
  }

  // ---------- Tree ----------
  function nodeEl(icon, name, badge, onclick, key) {
    var d = document.createElement('div');
    d.className = 'tree-node';
    d.dataset.key = key;
    d.innerHTML = '<span class="t-icon">' + icon + '</span><span class="t-name" title="' + escapeHtml(name) + '">' + escapeHtml(name) + '</span>' + (badge ? '<span class="t-badge">' + badge + '</span>' : '');
    d.addEventListener('click', function () {
      document.querySelectorAll('.tree-node.active').forEach(function (n) { n.classList.remove('active'); });
      d.classList.add('active');
      onclick();
    });
    return d;
  }

  function buildTree() {
    var tree = $('tree');
    tree.innerHTML = '';
    var r = state.data;
    if (r.kind === 'bundle') {
      tree.appendChild(nodeEl('&#128230;', state.fileName, r.info.entryCount + ' entradas', showBundleInfo, 'root'));
      var wrap = document.createElement('div');
      wrap.className = 'tree-child';
      r.entries.forEach(function (e, ei) {
        var icon = e.isAssets ? '&#128193;' : '&#128196;';
        wrap.appendChild(nodeEl(icon, e.name, fmtSize(e.size), function () { showEntry(ei); }, 'e' + ei));
        if (e.isAssets && e.assets) {
          var sub = document.createElement('div');
          sub.className = 'tree-child';
          e.assets.forEach(function (a, ai) {
            sub.appendChild(nodeEl('&#9654;', (a.name || a.typeName) + ' #' + a.pathId, fmtSize(a.size), function () { showAsset(ei, ai); }, 'a' + ei + '-' + ai));
          });
          wrap.appendChild(sub);
        }
      });
      tree.appendChild(wrap);
    } else {
      tree.appendChild(nodeEl('&#128193;', state.fileName, r.info.assetCount + ' assets', showBundleInfo, 'root'));
      var sub2 = document.createElement('div');
      sub2.className = 'tree-child';
      r.assets.forEach(function (a, ai) {
        sub2.appendChild(nodeEl('&#9654;', (a.name || a.typeName) + ' #' + a.pathId, fmtSize(a.size), function () { showAsset(-1, ai); }, 'a-' + ai));
      });
      tree.appendChild(sub2);
    }
  }

  function panel(title, body) {
    var p = document.createElement('div');
    p.className = 'panel';
    p.innerHTML = '<h3>' + title + '</h3>' + body;
    return p;
  }
  function kv(k, v, tag) {
    return '<div class="k">' + k + '</div><div class="v">' + (tag ? '<span class="tag ' + tag + '">' + v + '</span>' : escapeHtml(String(v))) + '</div>';
  }

  function showBundleInfo() {
    var r = state.data, i = r.info, html;
    if (r.kind === 'bundle') {
      html = '<div class="kv">' + kv('Assinatura', i.signature, 'tag info') + kv('Versão do bundle', i.fileVersion) + kv('Engine', i.engine) + kv('Compressão', i.compression, 'tag ok') + kv('Tamanho total', fmtSize(i.totalSize)) + kv('Blocos', i.blockCount) + kv('Entradas', i.entryCount) + '</div>';
      $('details').innerHTML = '';
      $('details').appendChild(panel('&#128230; Bundle', html));
    } else {
      html = '<div class="kv">' + kv('Formato', i.format) + kv('Unity', i.unityVersion) + kv('Plataforma', i.platform) + kv('Assets', i.assetCount, 'tag ok') + '</div>';
      $('details').innerHTML = '';
      $('details').appendChild(panel('&#128193; Arquivo .assets', html));
      $('details').appendChild(assetsTable(r.assets, -1));
    }
  }

  function showEntry(ei) {
    var e = state.data.entries[ei];
    var html = '<div class="kv">' + kv('Nome', e.name) + kv('Tipo', e.isAssets ? '<span class="tag ok">Arquivo .assets</span>' : '<span class="tag info">Dados</span>') + kv('Tamanho', fmtSize(e.size)) + '</div>' +
      '<div style="margin-top:14px;"><button class="btn primary" id="expEntry">Exportar entrada (bruto)</button></div>';
    $('details').innerHTML = '';
    $('details').appendChild(panel('&#128196; Entrada: ' + escapeHtml(e.name), html));
    if (e.assets) $('details').appendChild(assetsTable(e.assets, ei));
    document.getElementById('expEntry').addEventListener('click', function () {
      var b64 = pyodide.globals.get('get_entry_bytes')(ei);
      downloadBase64(b64, e.name.replace(/[\\/:*?"<>|]/g, '_'));
    });
  }

  function doExport(entryIdx, assetIdx, a) {
    if (a && a.classId === 28) {
      try {
        var r = JSON.parse(pyodide.globals.get('export_texture')(entryIdx, assetIdx));
        if (r.base64) {
          downloadBase64(r.base64, r.filename);
          setStatus('Exportado: ' + r.filename + ' (' + r.kind + ')', 'ok');
          return;
        }
      } catch (e) { /* fall through to bin */ }
    }
    var b64 = pyodide.globals.get('get_asset_bytes')(entryIdx, assetIdx);
    downloadBase64(b64, (a && a.name ? a.name : (a ? a.typeName : 'asset')) + '_' + (a ? a.pathId : assetIdx) + '.bin');
  }

  function assetsTable(assets, entryIdx) {
    var p = panel('&#128203; Assets (' + assets.length + ')', '<div style="overflow-x:auto;max-height:480px;overflow-y:auto;"><table class="assets"><thead><tr><th>#</th><th>Path ID</th><th>Nome</th><th>Tipo</th><th class="num">Tamanho</th><th></th></tr></thead><tbody id="assetTbody"></tbody></table></div>');
    setTimeout(function () {
      var tb = document.getElementById('assetTbody');
      if (!tb) return;
      var frag = document.createDocumentFragment();
      assets.forEach(function (a, i) {
        var tr = document.createElement('tr');
        tr.innerHTML = '<td>' + i + '</td><td class="mono">' + a.pathId + '</td><td>' + (a.name ? escapeHtml(a.name) : '<span style="color:var(--muted)">—</span>') + '</td><td>' + escapeHtml(a.typeName) + '</td><td class="num">' + fmtSize(a.size) + '</td><td><button class="export-btn">Exportar</button></td>';
        tr.querySelector('.export-btn').addEventListener('click', function () { doExport(entryIdx, i, a); });
        frag.appendChild(tr);
      });
      tb.appendChild(frag);
    }, 0);
    return p;
  }

  function showAsset(entryIdx, assetIdx) {
    var assets = state.data.kind === 'bundle' ? state.data.entries[entryIdx].assets : state.data.assets;
    var a = assets[assetIdx];
    var html = '<div class="kv">' + kv('Path ID', a.pathId) + kv('Tipo', a.typeName, 'tag info') + kv('Class ID', a.classId) + kv('Tamanho', fmtSize(a.size)) + (a.name ? kv('Nome', a.name) : '') + '</div>' +
      '<div style="margin-top:14px;"><button class="btn primary" id="expAsset">Exportar asset (.bin)</button></div>';
    $('details').innerHTML = '';
    $('details').appendChild(panel('&#9654; ' + escapeHtml(a.typeName) + ' #' + a.pathId, html));
    document.getElementById('expAsset').addEventListener('click', function () { doExport(entryIdx, assetIdx, a); });
    if (a.classId === 28) {
      var prev = panel('&#128444; Pré-visualização', '<p><span class="spinner"></span> Decodificando textura em Python...</p>');
      $('details').appendChild(prev);
      setTimeout(function () {
        try {
          var tex = JSON.parse(pyodide.globals.get('get_texture_preview')(entryIdx, assetIdx));
          if (tex.error) {
            prev.innerHTML = '<h3>&#128444; Textura</h3><p style="color:var(--warn);">' + escapeHtml(tex.error) + '</p>';
          } else if (tex.png) {
            prev.innerHTML = '<h3>&#128444; Textura: ' + escapeHtml(tex.name || '') + '</h3><img src="' + tex.png + '" style="max-width:100%;image-rendering:pixelated;border:1px solid var(--border);border-radius:6px;background:repeating-conic-gradient(#333 0% 25%,#444 0% 50%) 50% / 16px 16px;"><div style="margin-top:10px;font-size:12px;color:var(--muted);font-family:var(--mono);">' + tex.width + '×' + tex.height + ' · ' + tex.format + '</div>';
          } else {
            prev.innerHTML = '<h3>&#128444; Textura identificada</h3><p style="color:var(--warn);">Formato ' + escapeHtml(tex.format) + ' (' + tex.width + '×' + tex.height + ') ainda não tem decodificador. Use a exportação bruta.</p>';
          }
        } catch (e) {
          prev.innerHTML = '<h3>&#128444; Textura</h3><p style="color:var(--err);">Erro: ' + escapeHtml(e.message) + '</p>';
        }
      }, 50);
    }
    if (a.classId === 49) {
      // TextAsset: read text from asset bytes
      try {
        var b64 = pyodide.globals.get('get_asset_bytes')(entryIdx, assetIdx);
        var bin = atob(b64);
        var bytes = new Uint8Array(bin.length);
        for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
        // skip first aligned string (m_Name), second is the text
        var dv = new DataView(bytes.buffer);
        var ln = dv.getInt32(0, true);
        var off = 4 + ln; off = (off + 3) & ~3;
        var ln2 = dv.getInt32(off, true);
        var text = new TextDecoder('utf-8').decode(bytes.subarray(off + 4, off + 4 + ln2));
        var tp = panel('&#128221; TextAsset (' + ln2 + ' bytes)', '<pre style="background:#16171d;padding:12px;border-radius:6px;overflow:auto;max-height:360px;font-size:12px;white-space:pre-wrap;word-break:break-word;color:#c8ccd4;">' + escapeHtml(text.length > 100000 ? text.slice(0, 100000) + '\n... (truncado)' : text) + '</pre>');
        $('details').appendChild(tp);
      } catch (e) { /* ignore */ }
    }
  }

  // ---------- Events ----------
  $('dzInner').addEventListener('click', function () { if (!$('btnOpen').disabled) $('fileInput').click(); });
  $('btnOpen').addEventListener('click', function () { $('fileInput').click(); });
  $('btnClose').addEventListener('click', function () {
    state.data = null;
    $('app').classList.remove('visible');
    $('dropzone').classList.remove('hidden');
    $('btnClose').classList.add('hidden');
    $('tree').innerHTML = '';
    setStatus('Pronto.');
    $('fileInput').value = '';
  });
  $('fileInput').addEventListener('change', function (e) {
    if (e.target.files && e.target.files[0]) handleFile(e.target.files[0]);
  });
  ['dragover', 'dragenter'].forEach(function (ev) {
    document.addEventListener(ev, function (e) { e.preventDefault(); $('dropzone').classList.add('dragover'); });
  });
  ['dragleave', 'drop'].forEach(function (ev) {
    document.addEventListener(ev, function (e) { e.preventDefault(); $('dropzone').classList.remove('dragover'); });
  });
  document.addEventListener('drop', function (e) {
    if (e.dataTransfer.files && e.dataTransfer.files[0] && !$('btnOpen').disabled) handleFile(e.dataTransfer.files[0]);
  });

  init();
})();
